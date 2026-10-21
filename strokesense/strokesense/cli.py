"""StrokeSense command line.

    python -m strokesense.cli VIDEO [--start 5 --duration 30] [--out results/]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from . import crew, render, report
from .pose import (PoseDetector, PoseResult, run_video, save_detections, load_detections,
                   result_from_detections, crew_tracks)


def analyse_video(video, out_dir="results", start=0.0, duration=None, tiles="auto", fps=15.0,
                  model=None, single=False, reuse=True, log=print):
    video = Path(video)
    out = Path(out_dir) / video.stem
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "detections.npz"

    t0 = time.time()
    if reuse and cache.exists():
        dets, meta = load_detections(cache)
        log(f"[1/4] Loaded cached pose ({len(dets)} frames)")
    else:
        log(f"[1/4] Running pose estimation on {video.name} ...")
        det = PoseDetector(model) if model else PoseDetector()

        def prog(i, n):
            log(f"      frame {i}/{n}  ({time.time() - t0:.0f}s)")
        dets, meta = run_video(video, det, tiles=tiles, start=start, duration=duration, target_fps=fps, progress=prog)
        save_detections(cache, dets, meta)
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
    report.build_json(rowers, sync, out / "metrics.json")
    log(f"Done in {time.time() - t0:.0f}s → {out}")
    return {"dir": out, "video": vid, "report": html_path, "rowers": rowers, "sync": sync, "pose": pose}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Markerless rowing technique analysis")
    ap.add_argument("video")
    ap.add_argument("--out", default="results")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the video to start")
    ap.add_argument("--duration", type=float, default=None, help="seconds to analyse")
    ap.add_argument("--tiles", default="auto", help="'auto' (find the boat and tile it at full resolution) or 'none'")
    ap.add_argument("--fps", type=float, default=15.0, help="analysis frame rate")
    ap.add_argument("--single", action="store_true", help="analyse only the clearest rower (erg / single scull)")
    ap.add_argument("--fresh", action="store_true", help="ignore cached pose results")
    a = ap.parse_args(argv)
    tiles = "auto" if a.tiles == "auto" else None
    res = analyse_video(a.video, a.out, a.start, a.duration, tiles, a.fps, single=a.single, reuse=not a.fresh)
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
