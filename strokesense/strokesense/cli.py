"""StrokeSense command line.

    python -m strokesense.cli VIDEO [--start 5 --duration 30] [--out results/]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zlib
from pathlib import Path
from zipfile import BadZipFile

import numpy as np

from . import __version__ as PACKAGE_VERSION
from . import crew, render, report
from .pose import (DEFAULT_MODEL, MODEL_URL, PoseDetector, PoseResult, run_video,
                   save_detections, load_detections, result_from_detections, crew_tracks)


# Bump this when pose preprocessing or detector defaults change. Downstream
# technique/report changes can reuse detections because they run again each time.
POSE_CACHE_VERSION = 1


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


def _cache_identity(video, start, duration, tiles, fps, model):
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
        },
        "model": model_id,
    }
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


def analyse_video(video, out_dir="results", start=0.0, duration=None, tiles="auto", fps=15.0,
                  model=None, single=False, reuse=True, log=print):
    video = Path(video).expanduser().resolve()
    model = Path(model).expanduser().resolve() if model is not None else None
    out = _result_directory(video, out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "detections.npz"

    t0 = time.time()
    identity = _cache_identity(video, start, duration, tiles, fps, model)
    dets = meta = None
    if reuse and cache.exists():
        try:
            cached_dets, cached_meta = load_detections(cache)
            if cached_meta.get("cache_identity") == identity:
                dets, meta = cached_dets, cached_meta
                log(f"[1/4] Loaded cached pose ({len(dets)} frames)")
            else:
                log("[1/4] Pose cache is outdated or belongs to a different source/settings/model; recomputing.")
        except (OSError, ValueError, KeyError, EOFError, BadZipFile, zlib.error) as exc:
            log(f"[1/4] Could not read pose cache ({type(exc).__name__}); recomputing.")
    if dets is None:
        log(f"[1/4] Running pose estimation on {video.name} ...")
        det = PoseDetector(model) if model else PoseDetector()
        # The detector may have downloaded the model, so capture its actual identity.
        identity = _cache_identity(video, start, duration, tiles, fps, model)

        def prog(i, n):
            log(f"      frame {i}/{n}  ({time.time() - t0:.0f}s)")
        dets, meta = run_video(video, det, tiles=tiles, start=start, duration=duration, target_fps=fps, progress=prog)
        if identity == _cache_identity(video, start, duration, tiles, fps, model):
            meta = {**meta, "cache_identity": identity}
            save_detections(cache, dets, meta)
        else:
            log("[1/4] Source or model changed during pose estimation; cache was not saved.")
    log("[2/4] Finding rowers and analysing strokes ...")
    rowers = []
    if not single:
        tracks, crew_dir, n_seats = crew_tracks(dets, meta["fps"])
        pose = PoseResult(fps=float(meta["fps"]), n_frames=len(dets), width=int(meta["width"]),
                          height=int(meta["height"]), tracks=tracks, start=float(meta["start"]),
                          stride=int(meta["stride"]))
        if n_seats >= 2 and tracks:
            log(f"      crew of {n_seats} found, {len(tracks)} seats tracked")
            rowers = crew.rowers_from_slots(pose, crew_dir, n_seats)
    if not rowers:
        pose = result_from_detections(dets, meta)
        log(f"      {len(pose.tracks)} people tracked")
        rowers = crew.find_rowers(pose, max_rowers=1 if single else 9)
    if not rowers:
        log("      No rowing motion found. Try a clip where the rower is side-on and at least ~150 px tall.")
        return None
    sync = crew.crew_sync(rowers, pose.fps)
    for r in rowers:
        s = r.summary
        if s.get("n_strokes"):
            iss = ", ".join(i["title"] for i in s["issues"][:2]) or "no consistent faults"
            sy = f"  catch {r.sync_ms:+.0f} ms" if r.sync_ms is not None else ""
            log(f"      {r.seat:>6}: score {s['score']:>3}  {s['rate']:.0f} spm  {s['n_strokes']} strokes{sy}  — {iss}")

    log("[3/4] Rendering annotated video ...")
    vid = render.render_video(video, pose, rowers, out / f"{video.stem}_annotated.mp4", sync)

    log("[4/4] Building report ...")
    snaps, reqs = {}, []
    for r in rowers:
        if not r.strokes:
            continue
        mid = r.strokes[len(r.strokes) // 2]
        c, f = out / f"seat_{r.seat}_catch.jpg", out / f"seat_{r.seat}_finish.jpg"
        snaps[r.tid] = {"catch": c, "finish": f}
        reqs += [(mid.catch, r, c), (mid.finish, r, f)]
    ref = max(rowers, key=lambda r: len(r.strokes))
    if ref.strokes:
        reqs.append((ref.strokes[len(ref.strokes) // 2].catch, None, out / "crew_catch.jpg"))
    render.snapshots(video, pose, rowers, reqs)
    html_path = report.build_html(video.name, pose, rowers, sync, snaps, out / "report.html")
    report.build_json(
        rowers, sync, out / "metrics.json",
        analysis_key=identity + f"|single={single}|app={PACKAGE_VERSION}",
        fps=pose.fps, start_seconds=pose.start,
    )
    log(f"Done in {time.time() - t0:.0f}s → {out}")
    return {"dir": out, "video": vid, "report": html_path, "rowers": rowers, "sync": sync, "pose": pose}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Markerless rowing technique analysis")
    ap.add_argument("video")
    ap.add_argument("--out", default="results")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the video to start")
    ap.add_argument("--duration", type=float, default=None, help="seconds to analyse")
    ap.add_argument("--tiles", choices=("auto", "none"), default="auto",
                    help="'auto' (find the boat and tile it at full resolution) or 'none'")
    ap.add_argument("--fps", type=float, default=15.0, help="analysis frame rate")
    ap.add_argument("--single", action="store_true", help="analyse only the clearest rower (erg / single scull)")
    ap.add_argument("--fresh", action="store_true", help="ignore cached pose results")
    a = ap.parse_args(argv)
    tiles = "auto" if a.tiles == "auto" else None
    res = analyse_video(a.video, a.out, a.start, a.duration, tiles, a.fps, single=a.single, reuse=not a.fresh)
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())

