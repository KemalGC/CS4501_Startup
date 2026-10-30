"""Annotated video + key-frame snapshots."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .strokes import FAULTS

SEG = [("shoulder", "elbow"), ("elbow", "wrist"), ("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle")]
PALETTE = [(80, 200, 255), (120, 230, 120), (255, 170, 90), (230, 120, 230), (90, 220, 220),
           (255, 120, 120), (160, 160, 255), (220, 220, 120), (255, 255, 255)]
GOOD, WARN, BAD = (90, 220, 120), (60, 190, 255), (80, 80, 255)


def _txt(img, s, org, scale=0.6, color=(255, 255, 255), thick=1, bg=(0, 0, 0)):
    (w, h), base = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x, y = int(org[0]), int(org[1])
    if bg is not None:
        overlay = img.copy()
        cv2.rectangle(overlay, (x - 4, y - h - 6), (x + w + 4, y + base + 2), bg, -1)
        cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _phase(rower, fi):
    for s in rower.strokes:
        if s.catch <= fi < s.finish:
            return "DRIVE", s
        if s.finish <= fi < s.next_catch:
            return "RECOVERY", s
    return None, None


def draw_rower(img, rower, fi, color, thickness=2, show_angles=True):
    k = rower.k
    if not k.visible[fi]:
        return
    p = {j: tuple(int(v) for v in k.px[j][fi]) for j in k.px}
    for a, b in SEG:
        if (a == "ankle" or b == "ankle") and not k.reliable["ankle"]:
            continue
        if (a == "knee" or b == "knee") and not k.reliable["knee"]:
            continue
        cv2.line(img, p[a], p[b], color, thickness + 1, cv2.LINE_AA)
    for j, q in p.items():
        if j == "ankle" and not k.reliable["ankle"]:
            continue
        cv2.circle(img, q, thickness + 2, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(img, q, thickness + 1, color, -1, cv2.LINE_AA)
    # label above the head
    sc = max(0.9, k.scale_px / 45)           # text scales with the rower's size in frame
    top = min(p["shoulder"][1], p["wrist"][1]) - int(40 * sc)
    phase, s = _phase(rower, fi)
    _txt(img, rower.seat, (p["shoulder"][0] - int(15 * sc), top), 0.55 * sc, color, 2)
    if show_angles:
        tr = k.angles["trunk"][fi]
        _txt(img, f"{tr:+.0f}\u00b0".replace("\u00b0", ""), (p["hip"][0] + 6, p["hip"][1] + int(28 * sc)), 0.5 * sc,
             (255, 255, 255), 2 if sc > 1.2 else 1)
    if s is not None and s.faults and phase is not None:
        # flash the first fault of the current stroke under the rower
        _txt(img, "!", (p["hip"][0] - 4, p["hip"][1] + 36), 0.6, BAD, 2)


def _open_writer(path: Path, fps, size):
    tmp = path.with_suffix(".tmp.mp4")
    w = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if w.isOpened():
        return w, tmp
    webm = path.with_suffix(".webm")
    return cv2.VideoWriter(str(webm), cv2.VideoWriter_fourcc(*"VP80"), fps, size), webm


def _finalise(tmp: Path, out: Path) -> Path:
    """Re-encode to browser-playable H.264 if ffmpeg is available; otherwise fall back to VP8 webm."""
    if tmp.suffix == ".webm":
        return tmp
    ff = shutil.which("ffmpeg")
    if ff is None:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ff = None
    if ff:
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(tmp), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", str(out)])
        if r.returncode == 0:
            tmp.unlink(missing_ok=True)
            return out
    # no ffmpeg: transcode via OpenCV to VP8 webm (plays in Chrome / Firefox / Edge)
    cap = cv2.VideoCapture(str(tmp))
    fps = cap.get(cv2.CAP_PROP_FPS)
    webm = out.with_suffix(".webm")
    w = None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if w is None:
            w = cv2.VideoWriter(str(webm), cv2.VideoWriter_fourcc(*"VP80"), fps, (fr.shape[1], fr.shape[0]))
        w.write(fr)
    cap.release()
    if w is not None:
        w.release()
    tmp.unlink(missing_ok=True)
    return webm


def iter_frames(video_path, pose):
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(pose.start * src_fps))
    fi, si = 0, 0
    while fi < pose.n_frames:
        ok, fr = cap.read()
        if not ok:
            break
        si += 1
        if (si - 1) % pose.stride:
            continue
        if fr.shape[1] != pose.width:
            fr = cv2.resize(fr, (pose.width, pose.height), interpolation=cv2.INTER_AREA)
        yield fi, fr
        fi += 1
    cap.release()


def render_video(video_path, pose, rowers, out_path, sync=None, max_width=1920):
    out_path = Path(out_path)
    scale = min(1.0, max_width / pose.width)
    size = (int(pose.width * scale) // 2 * 2, int(pose.height * scale) // 2 * 2)
    writer, tmp = _open_writer(out_path, pose.fps, size)
    colors = {r.tid: PALETTE[i % len(PALETTE)] for i, r in enumerate(rowers)}
    ref = max(rowers, key=lambda r: len(r.strokes)) if rowers else None
    for fi, fr in iter_frames(video_path, pose):
        for r in rowers:
            draw_rower(fr, r, fi, colors[r.tid], thickness=2 if pose.width < 1400 else 3)
        fr = cv2.resize(fr, size, interpolation=cv2.INTER_AREA)
        # HUD
        if ref is not None:
            phase, s = _phase(ref, fi)
            n_done = sum(1 for st in ref.strokes if st.catch <= fi)
            rate = f"{s.rate:.0f} spm" if s else "--"
            hs = size[0] / 1280
            _txt(fr, f"StrokeSense   stroke {n_done}   {rate}   {phase or ''}", (int(14 * hs), int(34 * hs)),
                 0.65 * hs, thick=2 if hs > 1.2 else 1)
            if sync and sync.get("per_seat"):
                y = int(70 * hs)
                for r in rowers:
                    v = sync["per_seat"].get(r.seat)
                    if v is None:
                        continue
                    col = GOOD if abs(v["mean_ms"]) <= 30 else (WARN if abs(v["mean_ms"]) <= 60 else BAD)
                    word = "late" if v["mean_ms"] > 0 else "early"
                    _txt(fr, f"{r.seat:>6}  catch {abs(v['mean_ms']):3.0f} ms {word}", (int(14 * hs), y),
                         0.5 * hs, col)
                    y += int(24 * hs)
            if s is not None and len(rowers) == 1 and s.faults:
                for i, f in enumerate(s.faults[:3]):
                    _txt(fr, FAULTS[f]["title"], (14, 62 + 28 * i), 0.55, BAD)
        writer.write(fr)
    writer.release()
    return _finalise(tmp, out_path)


def _crop_rower(fr, r, fi, pad=1.0, min_h=360):
    k = r.k
    pts = np.array([k.px[j][fi] for j in ("shoulder", "wrist", "hip", "knee", "elbow")])
    x0, y0 = pts.min(0); x1, y1 = pts.max(0)
    y0 -= 0.8 * k.scale_px                                # include the head
    s = max(x1 - x0, y1 - y0) * (1 + pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    X0, Y0 = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
    X1, Y1 = int(min(fr.shape[1], cx + s / 2)), int(min(fr.shape[0], cy + s / 2))
    out = fr[Y0:Y1, X0:X1]
    if out.shape[0] and out.shape[0] < min_h:
        f = min_h / out.shape[0]
        out = cv2.resize(out, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return out


def snapshots(video_path, pose, rowers, requests):
    """requests: list of (frame_idx, rower_or_None, out_path). One pass over the video."""
    want = {}
    written = set()
    for fi, r, path in requests:
        want.setdefault(fi, []).append((r, path))
    colors = {r.tid: PALETTE[i % len(PALETTE)] for i, r in enumerate(rowers)}
    last = max(want) if want else -1
    for fi, fr in iter_frames(video_path, pose):
        if fi > last:
            break
        for r, path in want.get(fi, []):
            img = fr.copy()
            if r is None:
                for rr in rowers:
                    draw_rower(img, rr, fi, colors[rr.tid], thickness=3)
            else:
                draw_rower(img, r, fi, colors[r.tid], thickness=2)
                img = _crop_rower(img, r, fi)
            if img.size == 0:
                continue
            if max(img.shape[:2]) > 720:
                scale = 720 / max(img.shape[:2])
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            if cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85]):
                written.add(Path(path))
    return written


def fault_snapshot_requests(rower, pose, out_dir):
    """One visible evidence-context photo per actual flagged code (not generic catch).

    Phase-specific measurements use the same smoothed signals as the detector.
    Timing/sequence faults still require surrounding frames; a still image does
    not prove a diagnosis or coach approval. Missing target frames are omitted.
    """
    from .kinematics import smooth
    from .strokes import _progress, _first_at
    k = rower.k
    angles = {name: smooth(v, k.fps, .2) for name, v in k.angles.items()}
    shots, requests = {}, []
    for stroke in rower.strokes:
        c, f, n = stroke.catch, stroke.finish, stroke.next_catch
        if not 0 <= c < f < n < k.n:
            continue
        legs = _progress(angles['thigh'], c, f)
        drive30 = c + _first_at(legs, .3)
        drive70 = c + _first_at(legs, .7)
        recovery30 = f + _first_at(_progress(angles['thigh'], f, n), .3)
        phase = {
            'short_catch': c, 'overreach': c, 'over_compression': c,
            'excess_layback': f, 'no_layback': f,
            'shooting_slide': c + int(np.argmax(angles['trunk'][c:drive30+1])),
            'early_arms': c + int(np.argmin(angles['elbow'][c:drive70+1])),
            'early_body': c + _first_at(legs, .4),
            'late_body_prep': recovery30,
            'rushed_recovery': (f+n)//2,
        }
        for code in stroke.faults:
            if code in shots or code not in FAULTS:
                continue
            fi = int(phase[code])
            if not k.visible[fi]:
                continue
            path = Path(out_dir) / f'fault_{int(rower.tid)}_{code}.jpg'
            shots[code] = {'stroke': stroke.idx, 'frame': fi,
                           'seconds': float(pose.start + fi / pose.fps), 'path': path}
            requests.append((fi, rower, path))
    return shots, requests
