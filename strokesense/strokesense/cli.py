"""StrokeSense command line.

    python -m strokesense.cli VIDEO [--start 5 --duration 30] [--out results/]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import zlib
from pathlib import Path
from zipfile import BadZipFile

import numpy as np

from . import __version__ as PACKAGE_VERSION
from . import cadence, crew, render, report
from .selection import validate_selection, locked_tracks, SelectionError
from .dynamic_crew import EXTRACTION_VERSION, run_selected_video, rowers_from_selected
from .pose import (DEFAULT_MODEL, MODEL_URL, PoseDetector, PoseResult, run_video,
                   save_detections, load_detections, result_from_detections, crew_tracks)

from .pose_merge import VERSION as DETECTION_POSTPROCESS_VERSION

# Bump this when pose preprocessing or detector defaults change. Downstream
# technique/report changes can reuse detections because they run again each time.
POSE_CACHE_VERSION = 3


def _file_identity(path, *, hash_content=False):
    """Return stable metadata and optionally a streamed SHA-256 fingerprint.

    Read in 1 MiB chunks: never load an entire video into memory. A post-hash
    stat check rejects detectable concurrent edits (not an adversarial lock).
    """
    path = Path(path).expanduser().resolve()
    stat = path.stat()
    identity = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_content:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                stat.st_dev, stat.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns,
                after.st_dev, after.st_ino):
            raise OSError("media changed while computing SHA-256")
        identity["sha256"] = digest.hexdigest()
    return identity


def _cache_identity(video, start, duration, tiles, fps, model, selection=None, dominant=False):
    """Identify source bytes, request settings, and actual model bytes.

    Strong content fingerprints prevent same-size/same-mtime replacements from
    silently reusing stale detections; this incurs linear read I/O per check.
    """
    model_path = Path(model if model is not None else DEFAULT_MODEL).expanduser().resolve()
    try:
        model_id = _file_identity(model_path, hash_content=True)
    except FileNotFoundError:
        model_id = {"path": str(model_path), "missing": True, "download_url": MODEL_URL}
    identity = {
        "version": POSE_CACHE_VERSION,
        "source": _file_identity(video, hash_content=True),
        "settings": {
            "start": float(start), "duration": None if duration is None else float(duration),
            "tiles": tiles if isinstance(tiles, (str, type(None))) else np.asarray(tiles).tolist(),
            "target_fps": None if fps is None else float(fps),
            "detector_postprocess": DETECTION_POSTPROCESS_VERSION,
        },
        "model": model_id,
    }
    if dominant:
        from .dominant import VERSION
        identity['settings']['dominant_crew'] = VERSION
    if selection is not None:
        identity["selection"] = validate_selection(selection)
        identity["settings"]["selected_extraction"] = EXTRACTION_VERSION
        if selection["version"] == 2:
            identity["settings"]["refined_merge"] = DETECTION_POSTPROCESS_VERSION
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _result_directory(video, out_dir):
    """Path-scoped results for one canonical clip, independent of filename collisions.

    The suffix is a stable hash of the *canonical source path*, not footage data:
    it avoids disclosing the source's parent directory and does not read large
    video files. Results from a prior results/<stem> layout remain untouched.
    Source changes at the same path invalidate pose caches via _cache_identity.
    """
    video = Path(video).expanduser().resolve()
    source_key = hashlib.sha256(str(video).encode("utf-8")).hexdigest()[:20]
    return Path(out_dir) / f"{video.stem[:72]}--{source_key}"


def _write_mistake_gallery(out, rowers, snaps, written):
    """Publish only image files written in this run, never stale captures.

    Keeping a small file of relative JPEG basenames lets the HTTPS dashboard
    offer genuine, timestamped photo sequences without embedding huge data
    URLs in its JSON response. Unrelated local CLI reports are unaffected.
    """
    written = {Path(path) for path in (written or ())}
    manifest = {'version': 1, 'rowers': {}}
    for rower in rowers:
        seat = rower.seat
        if not isinstance(seat, str) or not re.fullmatch(r'R(?:[1-9]|1[0-6])', seat):
            continue
        item = snaps.get(rower.tid, {})
        pictures = []
        for kind, label in (('catch', 'Catch reference'), ('finish', 'Finish reference')):
            path = item.get(kind)
            if path is not None and Path(path) in written:
                pictures.append({
                    'label': label, 'time_seconds': item.get(kind + '_seconds'),
                    'filename': Path(path).name,
                })
        sequences = []
        for progression in item.get('progressions', [])[:3]:
            frames = [
                {'label': photo['label'], 'time_seconds': photo['time_seconds'],
                 'filename': Path(photo['path']).name}
                for photo in progression['frames']
                if Path(photo['path']) in written
            ]
            # A context-only image is not evidence of the candidate flag.
            if any(photo['label'] == 'Flagged moment' for photo in frames):
                sequences.append({
                    'code': progression['code'], 'stroke': progression['stroke'],
                    'frames': frames,
                })
        manifest['rowers'][seat] = {
            'snapshots': pictures, 'mistake_sequences': sequences,
        }
    target = Path(out) / 'mistake_frames.json'
    pending = Path(out) / '.mistake_frames.tmp'
    try:
        pending.write_text(json.dumps(manifest, allow_nan=False), encoding='utf-8')
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def analyse_video(video, out_dir="results", start=0.0, duration=None, tiles="auto", fps=15.0,
                  model=None, single=False, reuse=True, log=print, selection=None, dominant=False, threads=None, crew_size=None):
    if dominant and (selection is not None or single):
        raise ValueError('dominant mode cannot be combined with explicit selection or single')
    if selection is not None:
        selection = validate_selection(selection)
        if single or start != 0:
            raise SelectionError("selection_requires_first_frame_and_crew")
    video = Path(video).expanduser().resolve()
    model = Path(model).expanduser().resolve() if model is not None else None
    out = _result_directory(video, out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "detections.npz"

    t0 = time.time()
    identity = _cache_identity(video, start, duration, tiles, fps, model, selection=selection, dominant=dominant)
    dets = meta = None
    dominant_audit = None
    if reuse and cache.exists():
        try:
            cached_dets, cached_meta = load_detections(cache)
            if dominant and not (out / 'dominant.json').is_file():
                raise ValueError('dominant_audit_missing')
            if dominant:
                dominant_audit = json.loads((out / 'dominant.json').read_text())
            if cached_meta.get("cache_identity") == identity:
                dets, meta = cached_dets, cached_meta
                log(f"[1/4] Loaded cached pose ({len(dets)} frames)")
            else:
                log("[1/4] Pose cache is outdated or belongs to a different source/settings/model; recomputing.")
        except (OSError, ValueError, KeyError, EOFError, BadZipFile, zlib.error) as exc:
            log(f"[1/4] Could not read pose cache ({type(exc).__name__}); recomputing.")
    if dets is None:
        log(f"[1/4] Running pose estimation on {video.name} ...")
        detector_kwargs = {'threads': threads} if threads is not None else {}
        det = PoseDetector(model, **detector_kwargs) if model else PoseDetector(**detector_kwargs)
        # The detector may have downloaded the model, so capture its actual identity.
        identity = _cache_identity(video, start, duration, tiles, fps, model, selection=selection, dominant=dominant)

        def prog(i, n):
            log(f"      frame {i}/{n}  ({time.time() - t0:.0f}s)")
        if dominant:
            from .dominant import run_video as run_dominant_video
            dets, meta, dominant_audit = run_dominant_video(video, det, start=start,
                duration=duration, target_fps=fps, progress=prog)
            (out / 'dominant.json').write_text(json.dumps(dominant_audit, indent=2))
        elif selection is not None:
            dets, meta = run_selected_video(video, det, selection, tiles=tiles, start=start,
                                           duration=duration, target_fps=fps, progress=prog)
        else:
            dets, meta = run_video(video, det, tiles=tiles, start=start, duration=duration,
                                   target_fps=fps, progress=prog)
        if identity == _cache_identity(video, start, duration, tiles, fps, model, selection=selection, dominant=dominant):
            meta = {**meta, "cache_identity": identity}
            save_detections(cache, dets, meta)
        else:
            log("[1/4] Source or model changed during pose estimation; cache was not saved.")
    log("[2/4] Finding rowers and analysing strokes ...")
    rowers = []
    seat_mapping = None
    if selection is not None:
        tracks = locked_tracks(dets, meta, selection)
        pose = PoseResult(fps=float(meta['fps']), n_frames=len(dets), width=int(meta['width']),
                          height=int(meta['height']), tracks=tracks, start=float(meta['start']),
                          stride=int(meta['stride']))
        rowers = rowers_from_selected(pose)
    elif not single:
        if dominant:
            from .dominant import track_visible_window
            tracks, crew_dir, n_seats = track_visible_window(dets, meta['fps'])
        else:
            tracks, crew_dir, n_seats = crew_tracks(dets, meta["fps"], expected_seats=crew_size)
        pose = PoseResult(fps=float(meta["fps"]), n_frames=len(dets), width=int(meta["width"]),
                          height=int(meta["height"]), tracks=tracks, start=float(meta["start"]),
                          stride=int(meta["stride"]))
        if n_seats >= 2 and tracks:
            log(f"      crew of {n_seats} found, {len(tracks)} seats tracked")
            rowers = rowers_from_selected(pose) if dominant else crew.rowers_from_slots(pose, crew_dir, n_seats)
            if dominant:
                from .seat_orientation import infer_dominant_seats
                seat_mapping = infer_dominant_seats(
                    tracks, crew_facing=crew_dir, n_seats=n_seats)
                for rower in rowers:
                    rower.seat = f'R{rower.tid + 1}'
    if not rowers and selection is None and not dominant:
        pose = result_from_detections(dets, meta)
        log(f"      {len(pose.tracks)} people tracked")
        rowers = crew.find_rowers(pose, max_rowers=1 if single else 9)
    if not rowers:
        log("      No rowing motion found. Try a clip where the rower is side-on and at least ~150 px tall.")
        return None
    sync = crew.crew_sync(rowers, pose.fps)
    sync["cadence"] = cadence.estimate(rowers)
    if dominant:
        sync['crew_selection'] = dominant_audit
        sync['seat_mapping'] = seat_mapping
    if len(rowers) > 1:
        log("      " + cadence.description(sync["cadence"]))
    for r in rowers:
        s = r.summary
        if s.get("n_strokes"):
            iss = ", ".join(i["title"] for i in s["issues"][:2]) or "no consistent faults"
            sy = f"  catch {r.sync_ms:+.0f} ms" if r.sync_ms is not None else ""
            log(f"      {r.seat:>6}: score {s['score']:>3}  raw {s['rate']:.0f} spm ({cadence.qualification(sync['cadence'], r.seat)})  {s['n_strokes']} strokes{sy}  — {iss}")

    log("[3/4] Rendering annotated video ...")
    try:
        vid = render.render_video(video, pose, rowers, out / f"{video.stem}_annotated.mp4", sync)
    except render.RenderingUnavailable:
        vid = None
        log("      Annotated video unavailable; continuing with report and measurements.")
    sync['media'] = {'state': 'available' if vid is not None else 'unavailable',
                     'reason': None if vid is not None else 'browser_video_unavailable'}

    log("[4/4] Building report ...")
    snaps, reqs = {}, []
    for r in rowers:
        if not r.strokes:
            continue
        mid = r.strokes[len(r.strokes) // 2]
        c, f = out / f"seat_{r.seat}_catch.jpg", out / f"seat_{r.seat}_finish.jpg"
        faults, fault_requests = render.fault_snapshot_requests(r, pose, out)
        progressions, progress_requests = render.mistake_progression_requests(r, pose, faults, out)
        snaps[r.tid] = {
            "catch": c, "catch_seconds": float(pose.start + mid.catch / pose.fps),
            "finish": f, "finish_seconds": float(pose.start + mid.finish / pose.fps),
            "faults": faults, "progressions": progressions,
        }
        reqs += [(mid.catch, r, c), (mid.finish, r, f)] + fault_requests + progress_requests
    ref = max(rowers, key=lambda r: len(r.strokes))
    if ref.strokes:
        reqs.append((ref.strokes[len(ref.strokes) // 2].catch, None, out / "crew_catch.jpg"))
    written = render.snapshots(video, pose, rowers, reqs)
    # Never embed a stale photo left by a prior CLI run after decode/write failure.
    for sn in snaps.values():
        sn['faults'] = {code: shot for code, shot in sn.get('faults', {}).items()
                        if written is not None and shot['path'] in written}
    _write_mistake_gallery(out, rowers, snaps, written)
    html_path = report.build_html(video.name, pose, rowers, sync, snaps, out / "report.html")
    report.build_json(
        rowers, sync, out / "metrics.json",
        analysis_key=identity + f"|single={single}|crew_size={crew_size}|app={PACKAGE_VERSION}",
        fps=pose.fps, start_seconds=pose.start,
    )
    if dominant:
        from .dominant import validate_metrics, decorate_report
        metrics = json.loads((out / 'metrics.json').read_text())
        validation = validate_metrics(metrics, n_frames=pose.n_frames)
        (out / 'validation.json').write_text(json.dumps(validation, indent=2))
        decorate_report(html_path, metrics, validation)
    log(f"Done in {time.time() - t0:.0f}s → {out}")
    return {"dir": out, "video": vid, "report": html_path, "rowers": rowers, "sync": sync, "pose": pose}



def _finite_cli_value(text: str, *, name: str, allow_zero: bool) -> float:
    """Reject non-finite/negative input before model or file access."""
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a finite number") from exc
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        requirement = "nonnegative" if allow_zero else "positive"
        raise argparse.ArgumentTypeError(
            f"{name} must be a finite {requirement} number"
        )
    return value


def _start_arg(text):
    return _finite_cli_value(text, name="start", allow_zero=True)


def _duration_arg(text):
    return _finite_cli_value(text, name="duration", allow_zero=False)


def _fps_arg(text):
    return _finite_cli_value(text, name="fps", allow_zero=False)



def main(argv=None):
    ap = argparse.ArgumentParser(description="Markerless rowing technique analysis")
    ap.add_argument("video")
    ap.add_argument("--out", default="results")
    ap.add_argument("--start", type=_start_arg, default=0.0, help="seconds into the video to start")
    ap.add_argument("--duration", type=_duration_arg, default=None, help="seconds to analyse")
    ap.add_argument("--tiles", choices=("auto", "none"), default="auto",
                    help="'auto' (find the boat and tile it at full resolution) or 'none'")
    ap.add_argument("--fps", type=_fps_arg, default=15.0, help="analysis frame rate")
    ap.add_argument("--crew-size", type=int, choices=(1,2,4,8), help="known number of rowers, excluding cox")
    ap.add_argument("--single", action="store_true", help="analyse only the clearest rower (erg / single scull)")
    ap.add_argument('--dominant-crew', action='store_true', help='isolate the largest clear crew; gaps never recruit a different boat')
    ap.add_argument('--threads', type=int, default=None, help='ONNX CPU threads, 1–64')
    ap.add_argument("--fresh", action="store_true", help="ignore cached pose results")
    a = ap.parse_args(argv)
    tiles = "auto" if a.tiles == "auto" else None
    res = analyse_video(a.video, a.out, a.start, a.duration, tiles, a.fps, single=a.single, reuse=not a.fresh, dominant=a.dominant_crew, threads=a.threads, crew_size=a.crew_size)
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
