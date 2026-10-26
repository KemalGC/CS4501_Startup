"""Markerless 2D pose estimation + multi-person tracking.

Uses the Ultralytics YOLO11-pose network exported to ONNX and runs it with
onnxruntime, so the only heavy dependency is onnxruntime (no PyTorch needed).

For launch footage of a full crew, each rower is small in frame, so the frame is
optionally split into overlapping tiles that are each fed to the network at full
resolution. Detections from all tiles are merged with NMS.
"""
from __future__ import annotations

import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.onnx"
DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "models" / "yolo11n-pose.onnx"


def ensure_model(path: Path = DEFAULT_MODEL) -> Path:
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading pose model to {path} ...")
        urllib.request.urlretrieve(MODEL_URL, path)
    return path


# ----------------------------------------------------------------------------- detector

class PoseDetector:
    def __init__(self, model_path: Path | str = DEFAULT_MODEL, conf: float = 0.25, iou: float = 0.5):
        import onnxruntime as ort
        model_path = ensure_model(Path(model_path))
        providers = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider")
                     if p in ort.get_available_providers()] + ["CPUExecutionProvider"]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2))
        self.sess = ort.InferenceSession(str(model_path), opts, providers=providers)
        self.inp = self.sess.get_inputs()[0].name
        self.size = 640
        self.conf, self.iou = conf, iou

    def _letterbox(self, img):
        h, w = img.shape[:2]
        r = self.size / max(h, w)
        nh, nw = int(round(h * r)), int(round(w * r))
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        top, left = (self.size - nh) // 2, (self.size - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return canvas, r, left, top

    def _infer(self, img):
        """Returns boxes (M,4 xyxy), scores (M,), kpts (M,17,3) in img pixel coords."""
        lb, r, dx, dy = self._letterbox(img)
        blob = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = self.sess.run(None, {self.inp: blob})[0][0].T          # (8400, 56)
        scores = out[:, 4]
        keep = scores > self.conf
        out, scores = out[keep], scores[keep]
        if len(out) == 0:
            return np.zeros((0, 4)), np.zeros(0), np.zeros((0, 17, 3))
        cx, cy, bw, bh = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
        kpts = out[:, 5:].reshape(-1, 17, 3).copy()
        # undo letterbox
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - dx) / r
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - dy) / r
        kpts[..., 0] = (kpts[..., 0] - dx) / r
        kpts[..., 1] = (kpts[..., 1] - dy) / r
        return boxes, scores, kpts

    @staticmethod
    def tile_grid(W, H, roi=None, tile=640, overlap=0.3):
        """Square crops of `tile` native pixels covering roi=(y0,y1) (full height if None).
        Native-resolution tiles mean small, distant rowers are not shrunk before the network."""
        y0, y1 = roi if roi else (0, H)
        tile = min(tile, W, H)
        step = int(tile * (1 - overlap))
        xs = list(range(0, max(1, W - tile) + 1, step))
        if xs[-1] + tile < W:
            xs.append(W - tile)
        cy = (y0 + y1) / 2
        if y1 - y0 <= tile:
            ys = [int(np.clip(cy - tile / 2, 0, H - tile))]
        else:
            ys = list(range(int(y0), int(y1 - tile) + 1, step))
            if ys[-1] + tile < y1:
                ys.append(int(min(H - tile, y1 - tile)))
        return [(x, y, x + tile, y + tile) for y in ys for x in xs]

    def __call__(self, frame, tiles=None):
        """Detect people. tiles: None = whole frame only; otherwise a list of (x0,y0,x1,y1) crops."""
        H, W = frame.shape[:2]
        all_b, all_s, all_k = [], [], []
        crops = [(0, 0, W, H)] + list(tiles or [])
        for x0, y0, x1, y1 in crops:
            b, s, k = self._infer(frame[y0:y1, x0:x1])
            b[:, [0, 2]] += x0; b[:, [1, 3]] += y0
            k[..., 0] += x0; k[..., 1] += y0
            all_b.append(b); all_s.append(s); all_k.append(k)
        boxes, scores, kpts = np.concatenate(all_b), np.concatenate(all_s), np.concatenate(all_k)
        if len(boxes) == 0:
            return boxes, scores, kpts
        idx = cv2.dnn.NMSBoxes([[float(x0), float(y0), float(x1 - x0), float(y1 - y0)] for x0, y0, x1, y1 in boxes],
                               scores.astype(float).tolist(), self.conf, self.iou)
        idx = np.array(idx).reshape(-1)
        idx = idx[np.argsort(-scores[idx])]
        # drop fragments cut off at tile edges: boxes mostly contained inside a stronger box
        keep = []
        for i in idx:
            bi = boxes[i]
            ai = (bi[2] - bi[0]) * (bi[3] - bi[1]) + 1e-9
            frag = False
            for j in keep:
                bj = boxes[j]
                iw = max(0, min(bi[2], bj[2]) - max(bi[0], bj[0]))
                ih = max(0, min(bi[3], bj[3]) - max(bi[1], bj[1]))
                if iw * ih / ai > 0.6:
                    frag = True
                    break
            if not frag:
                keep.append(i)
        keep = np.array(keep, int)
        return boxes[keep], scores[keep], kpts[keep]


# ----------------------------------------------------------------------------- tracking

def _iou(a, b):
    """IoU matrix between (A,4) and (B,4) xyxy boxes."""
    x0 = np.maximum(a[:, None, 0], b[None, :, 0]); y0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2]); y1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    area = lambda z: (z[:, 2] - z[:, 0]) * (z[:, 3] - z[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


@dataclass
class Track:
    tid: int
    frames: list = field(default_factory=list)
    boxes: list = field(default_factory=list)
    kpts: list = field(default_factory=list)
    last_box: np.ndarray | None = None
    vel: np.ndarray = field(default_factory=lambda: np.zeros(4))
    missed: int = 0


class Tracker:
    """Centre-distance tracker with damped constant-velocity prediction.

    Rowers sit in a line ~1 box-width apart, so matching on box centres (gated at half a box
    width) is more reliable than IoU for small, overlapping boxes. Tracks survive gaps of up to
    `max_missed` frames (splash, an oar or the launch's gunwale hiding someone)."""

    def __init__(self, gate: float = 0.5, max_missed: int = 45):
        self.gate, self.max_missed = gate, max_missed
        self.active: list[Track] = []
        self.done: list[Track] = []
        self.next_id = 0

    @staticmethod
    def _global_shift(pc, dc, w):
        """Camera motion between frames: the 2D shift that best overlays last frame's people
        on this frame's (all rowers move together on screen when the launch pans)."""
        if len(pc) == 0 or len(dc) == 0:
            return np.zeros(2)
        cands = (dc[None, :, :] - pc[:, None, :]).reshape(-1, 2)
        cands = np.vstack([np.zeros((1, 2)), cands])
        best, best_cost = np.zeros(2), np.inf
        cap = 0.5 * np.median(w)
        for c in cands:
            d = np.linalg.norm((pc + c)[:, None] - dc[None], axis=2).min(1)
            cost = np.minimum(d, cap).sum()
            if cost < best_cost - 1e-6 or (abs(cost - best_cost) < 1e-6 and np.abs(c).sum() < np.abs(best).sum()):
                best, best_cost = c, cost
        # refine: mean residual of the inliers
        d = (pc + best)[:, None] - dc[None]
        j = np.linalg.norm(d, axis=2).argmin(1)
        res = dc[j] - pc
        inl = np.linalg.norm(res - best, axis=1) < cap
        return res[inl].mean(0) if inl.any() else best

    def update(self, fi: int, boxes, kpts):
        matched_t, matched_d = set(), set()
        if self.active and len(boxes):
            prev = np.array([t.last_box for t in self.active])
            pc = (prev[:, :2] + prev[:, 2:]) / 2
            dc = (boxes[:, :2] + boxes[:, 2:]) / 2
            # typical width of each track (one narrow, partial box must not shrink the gate)
            w = np.array([max(np.median([bb[2] - bb[0] for bb in t.boxes[-15:]]), 1) for t in self.active])
            recent = np.array([t.missed == 0 for t in self.active])
            shift = self._global_shift(pc[recent] if recent.any() else pc, dc, w)
            for t in self.active:
                t.last_box = t.last_box + np.r_[shift, shift]
            pc = pc + shift
            dw = boxes[:, 2] - boxes[:, 0]
            cost = np.linalg.norm(pc[:, None] - dc[None], axis=2) / np.maximum(w[:, None], dw[None, :])
            r, c = linear_sum_assignment(cost)
            for ti, di in zip(r, c):
                if cost[ti, di] <= self.gate:
                    t = self.active[ti]
                    t.last_box = boxes[di]
                    t.frames.append(fi); t.boxes.append(boxes[di]); t.kpts.append(kpts[di])
                    t.missed = 0
                    matched_t.add(ti); matched_d.add(di)
        still = []
        for ti, t in enumerate(self.active):
            if ti not in matched_t:
                t.missed += 1
            (self.done if t.missed > self.max_missed else still).append(t)
        self.active = still
        for di in range(len(boxes)):
            if di not in matched_d:
                t = Track(self.next_id, [fi], [boxes[di]], [kpts[di]], boxes[di])
                self.next_id += 1
                self.active.append(t)

    def finish(self) -> list[Track]:
        return self.done + self.active


def _centre_x(t: Track, f: int):
    i = int(np.argmin(np.abs(np.array(t.frames) - f)))
    b = t.boxes[i]
    return (b[0] + b[2]) / 2, b[2] - b[0]


def stitch(tracks: list[Track], fps: float, max_gap_s: float = 6.0) -> list[Track]:
    """Join fragments of the same rower that the tracker split (rower hidden, camera jolt).

    A later fragment B continues an earlier fragment A when they never overlap in time and B's
    first position matches A's last position after correcting for camera pan, estimated from
    tracks that are visible at both moments."""
    tracks = sorted(tracks, key=lambda t: t.frames[0])
    merged = True
    while merged:
        merged = False
        best = None
        for a in tracks:
            for b in tracks:
                if a is b or b.frames[0] <= a.frames[-1]:
                    continue
                gap = b.frames[0] - a.frames[-1]
                if gap > max_gap_s * fps:
                    continue
                fa, fb = a.frames[-1], b.frames[0]
                refs = [t for t in tracks if t is not a and t is not b
                        and t.frames[0] <= fa and t.frames[-1] >= fb]
                shift = np.median([_centre_x(t, fb)[0] - _centre_x(t, fa)[0] for t in refs]) if refs else 0.0
                xa, _ = _centre_x(a, fa)
                xb, _ = _centre_x(b, fb)
                wa = max(np.median([bb[2] - bb[0] for bb in a.boxes[-15:]]),
                         np.median([bb[2] - bb[0] for bb in b.boxes[:15]]), 1)
                d = abs(xb - (xa + shift)) / wa
                if d < 0.6 and (best is None or d < best[0]):
                    best = (d, a, b)
        if best:
            _, a, b = best
            a.frames += b.frames; a.boxes += b.boxes; a.kpts += b.kpts
            tracks.remove(b)
            merged = True
    return tracks


# ----------------------------------------------------------------------------- video → tracks

@dataclass
class PoseResult:
    fps: float
    n_frames: int
    width: int
    height: int
    tracks: dict          # tid -> dict(frames=(K,), boxes=(K,4), kpts=(K,17,3))
    start: float = 0.0    # seconds into the source video where analysis began
    stride: int = 1       # source frames per analysed frame

    def dense(self, tid: int) -> np.ndarray:
        """(n_frames,17,3) keypoints for a track; confidence 0 where not detected."""
        out = np.zeros((self.n_frames, 17, 3))
        t = self.tracks[tid]
        out[t["frames"]] = t["kpts"]
        return out


def clean_detections(boxes, kpts, min_kconf=0.25):
    """Drop junk: low-confidence skeletons, and slivers / partial boxes lying mostly inside a
    bigger box (tile-edge fragments, a person detected twice)."""
    if len(boxes) == 0:
        return boxes, kpts
    kc = kpts[:, 5:13, 2].mean(1)                     # shoulders, elbows, wrists, hips
    ok = kc >= min_kconf
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    order = np.argsort(-area)
    keep = []
    for i in order:
        if not ok[i]:
            continue
        bi = boxes[i]
        frag = False
        for j in keep:
            bj = boxes[j]
            iw = max(0, min(bi[2], bj[2]) - max(bi[0], bj[0]))
            ih = max(0, min(bi[3], bj[3]) - max(bi[1], bj[1]))
            if iw * ih / (area[i] + 1e-9) > 0.55:
                frag = True
                # the smaller box is the better skeleton when it is the confident one
                if kc[i] > kc[j] + 0.15 and area[i] > 0.5 * area[j]:
                    keep[keep.index(j)] = i
                break
        if not frag:
            keep.append(i)
    keep = np.array(sorted(keep), int)
    return boxes[keep], kpts[keep]


def build_tracks(dets, fps, n_frames, min_track_frac=0.3):
    """dets: list over frames of (boxes, kpts). Returns tid -> track dict."""
    tr = Tracker()
    for fi, (b, k) in enumerate(dets):
        b, k = clean_detections(b, k)
        tr.update(fi, b, k)
    tracks = stitch(tr.finish(), fps)
    out = {}
    for t in tracks:
        if len(t.frames) >= min_track_frac * n_frames:
            order = np.argsort(t.frames)
            out[t.tid] = {"frames": np.array(t.frames)[order], "boxes": np.array(t.boxes)[order],
                          "kpts": np.array(t.kpts)[order]}
    return out


def save_detections(path, dets, meta):
    flat = {k: np.asarray(v) for k, v in meta.items()}
    flat["counts"] = np.array([len(b) for b, _ in dets], dtype=np.int64)
    flat["boxes"] = np.concatenate([b for b, _ in dets]) if dets else np.zeros((0, 4))
    flat["kpts"] = np.concatenate([k for _, k in dets]) if dets else np.zeros((0, 17, 3))
    # Replace only after the complete archive is written; an interrupted run must
    # not destroy a previous usable cache or leave a partially written archive.
    path = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            np.savez_compressed(stream, **flat)
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load_detections(path):
    archive = np.load(path, allow_pickle=False)
    if not isinstance(archive, np.lib.npyio.NpzFile):
        raise ValueError("Pose cache must be an NPZ archive")
    with archive as z:
        counts, boxes, kpts = z["counts"], z["boxes"], z["kpts"]
        if counts.ndim != 1 or not np.issubdtype(counts.dtype, np.integer) or np.any(counts < 0):
            raise ValueError("Invalid cached detection counts")
        total = sum(int(count) for count in counts)
        if boxes.shape != (total, 4) or kpts.shape != (total, 17, 3):
            raise ValueError("Cached detection arrays do not match the frame counts")
        for array in (boxes, kpts):
            if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
                raise ValueError("Cached detections contain invalid coordinates")
        meta = {k: z[k].item() for k in ("fps", "width", "height", "start", "stride")}
        if not all(isinstance(v, (int, float)) and np.isfinite(v) for v in meta.values()):
            raise ValueError("Invalid cached video metadata")
        if meta["fps"] <= 0 or meta["start"] < 0 or meta["stride"] < 1:
            raise ValueError("Invalid cached frame timing")
        if any(meta[key] != int(meta[key]) for key in ("width", "height", "stride")):
            raise ValueError("Invalid cached video dimensions or stride")
        if min(meta["width"], meta["height"]) < (1 if len(counts) else 0):
            raise ValueError("Invalid cached video dimensions")
        if "cache_identity" in z:
            identity = z["cache_identity"].item()
            if not isinstance(identity, str):
                raise ValueError("Invalid cached source identity")
            meta["cache_identity"] = identity
        idx = np.concatenate([[0], np.cumsum(counts)])
        dets = [(boxes[a:b], kpts[a:b]) for a, b in zip(idx[:-1], idx[1:])]
    return dets, meta


def result_from_detections(dets, meta, min_track_frac=0.3) -> PoseResult:
    n = len(dets)
    tracks = build_tracks(dets, meta["fps"], n, min_track_frac)
    return PoseResult(fps=float(meta["fps"]), n_frames=n, width=int(meta["width"]), height=int(meta["height"]),
                      tracks=tracks, start=float(meta["start"]), stride=int(meta["stride"]))


def auto_tiles(video_path, detector, start, src_fps, max_width, samples=8):
    """Find the horizontal band where people are and cover it with native-resolution tiles."""
    cap = cv2.VideoCapture(str(video_path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    s0 = int(start * src_fps)
    ys, hs = [], []
    W = H = None
    for f in np.linspace(s0, max(s0, n - 1), samples + 2)[1:-1].astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, fr = cap.read()
        if not ok:
            continue
        if fr.shape[1] > max_width:
            s = max_width / fr.shape[1]
            fr = cv2.resize(fr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        H, W = fr.shape[:2]
        coarse = PoseDetector.tile_grid(W, H, None, tile=min(W, H), overlap=0.3)
        b, sc, _ = detector(fr, tiles=coarse)
        for bb in b:
            ys.append((bb[1] + bb[3]) / 2); hs.append(bb[3] - bb[1])
    cap.release()
    if W is None:
        return None
    if len(ys) < 3:
        return PoseDetector.tile_grid(W, H)
    lo, hi = np.percentile(ys, [10, 90])
    h = np.median(hs)
    roi = (max(0, lo - 1.2 * h), min(H, hi + 1.2 * h))
    tile = int(np.clip(h * 4, 320, 640))          # people ~1/4 of tile height suits the network
    return PoseDetector.tile_grid(W, H, roi, tile=tile)


def run_video(video_path, detector: PoseDetector | None = None, tiles: int | str = "auto",
              start: float = 0.0, duration: float | None = None, max_width: int = 1920,
              target_fps: float = 15.0, progress=None):
    """Run pose detection over a video. Returns (detections per frame, meta).

    Frames are subsampled to ~target_fps (15 fps is plenty for stroke rates up to ~45 spm)."""
    detector = detector or PoseDetector()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"Could not open {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride = max(1, int(round(src_fps / target_fps))) if target_fps else 1
    fps = src_fps / stride
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * src_fps))
    src_max = int(duration * src_fps) if duration else total - int(start * src_fps)
    n_max = (src_max + stride - 1) // stride

    dets = []
    fi, src_i, W, H = 0, 0, None, None
    while fi < n_max:
        ok, frame = cap.read()
        if not ok:
            break
        src_i += 1
        if (src_i - 1) % stride:
            continue
        if frame.shape[1] > max_width:
            s = max_width / frame.shape[1]
            frame = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        H, W = frame.shape[:2]
        if tiles == "auto":
            tiles = auto_tiles(video_path, detector, start, src_fps, max_width)
        boxes, _, kpts = detector(frame, tiles=tiles)
        dets.append((boxes, kpts))
        fi += 1
        if progress and fi % 10 == 0:
            progress(fi, n_max)
    cap.release()

    meta = {"fps": fps, "width": W or 0, "height": H or 0, "start": start, "stride": stride}
    return dets, meta


# ----------------------------------------------------------------------------- crew mode

def _facing(kpts: np.ndarray) -> int:
    """+1 if knees are to the right of hips (person faces image-right), -1 if left, 0 unknown."""
    hip = kpts[[11, 12]]; knee = kpts[[13, 14]]
    ok = (hip[:, 2] > 0.3) & (knee[:, 2] > 0.3)
    if not ok.any():
        return 0
    return int(np.sign(np.mean(knee[ok, 0] - hip[ok, 0])))


def crew_tracks(dets, fps, min_frac=0.3):
    """Seat-slot tracking for a crew shot side-on.

    Rowers sit in a fixed left-to-right order, so on frames where the whole crew is detected the
    order alone tells us who is who; on other frames each seat slot is matched to the nearest
    detection after compensating for camera pan. The cox (facing the other way) is removed using
    the generic tracker first."""
    n_frames = len(dets)
    clean = [clean_detections(b, k) for b, k in dets]

    # 1) generic tracks -> find the crew's facing and the cox
    tr = Tracker()
    for fi, (b, k) in enumerate(clean):
        tr.update(fi, b, k)
    generic = stitch(tr.finish(), fps)
    facings = {t.tid: np.sign(np.sum([_facing(k) for k in t.kpts])) for t in generic}
    weight = {t.tid: len(t.frames) for t in generic}
    crew_dir = np.sign(sum(facings[t] * weight[t] for t in facings)) or 1
    exclude = set()
    for t in generic:
        if facings[t.tid] == -crew_dir and len(t.frames) > 0.1 * n_frames:
            for f, bb in zip(t.frames, t.boxes):
                exclude.add((f, tuple(np.round(bb, 1))))

    rowers = []
    for fi, (b, k) in enumerate(clean):
        keep = [i for i in range(len(b)) if (fi, tuple(np.round(b[i], 1))) not in exclude]
        b, k = b[keep], k[keep]
        o = np.argsort((b[:, 0] + b[:, 2]) / 2) if len(b) else np.array([], int)
        rowers.append((b[o], k[o]))

    counts = np.array([len(b) for b, _ in rowers])
    if counts.max(initial=0) == 0:
        return {}, 1, 0
    n_seats = int(min(9, np.bincount(counts).argmax()))
    if n_seats == 0:
        return {}, 1, 0

    # 2) slot tracking
    slots = None
    out = {s: {"frames": [], "boxes": [], "kpts": []} for s in range(n_seats)}
    for fi, (b, k) in enumerate(rowers):
        if len(b) == 0:
            continue
        dc = (b[:, :2] + b[:, 2:]) / 2
        if slots is None:
            if len(b) != n_seats:
                continue
            slots = b.copy()
            assign = list(range(n_seats))
        else:
            sc = (slots[:, :2] + slots[:, 2:]) / 2
            w = np.maximum(slots[:, 2] - slots[:, 0], 1)
            shift = Tracker._global_shift(sc, dc, w)
            slots = slots + np.r_[shift, shift]
            sc = sc + shift
            if len(b) == n_seats:
                assign = list(range(n_seats))
                # reject an order-based assignment that disagrees badly with the motion model
                err = np.linalg.norm(sc - dc, axis=1) / w
                if np.median(err) > 0.6:
                    assign = None
            else:
                assign = None
            if assign is None:
                cost = np.linalg.norm(sc[:, None] - dc[None], axis=2) / w[:, None]
                r, c = linear_sum_assignment(cost)
                assign = [None] * n_seats
                for si, di in zip(r, c):
                    if cost[si, di] <= 0.6:
                        assign[si] = di
                # keep left-to-right order consistent
                got = [(si, di) for si, di in enumerate(assign) if di is not None]
                if any(d2 <= d1 for (_, d1), (_, d2) in zip(got, got[1:])):
                    continue
                assign = [assign[s] for s in range(n_seats)]
        for si, di in enumerate(assign):
            if di is None:
                continue
            slots[si] = b[di]
            out[si]["frames"].append(fi); out[si]["boxes"].append(b[di]); out[si]["kpts"].append(k[di])
    tracks = {}
    for si, t in out.items():
        if len(t["frames"]) >= min_frac * n_frames:
            tracks[si] = {kk: np.array(v) for kk, v in t.items()}
    return tracks, int(crew_dir), n_seats

