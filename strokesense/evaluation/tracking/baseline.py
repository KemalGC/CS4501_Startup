"""Frozen pre-change cleanup and seat association; evaluation only."""
import numpy as np
from scipy.optimize import linear_sum_assignment
from strokesense.pose import Tracker, stitch, _facing

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


def crew_tracks(dets, fps, min_frac=0.3, expected_seats=None):
    """Seat-slot tracking for a crew shot side-on.

    Rowers sit in a fixed left-to-right order, so on frames where the whole crew is detected the
    order alone tells us who is who; on other frames each seat slot is matched to the nearest
    detection after compensating for camera pan. The cox (facing the other way) is removed using
    the generic tracker first."""
    if expected_seats is not None and expected_seats not in (1, 2, 4, 8):
        raise ValueError("unsupported crew size")
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
        b, k = b[o], k[o]
        # With a declared shell size, exclude the cox end when a complete
        # aligned crew plus cox is observed. Never create missing detections.
        if expected_seats is not None and len(b) == expected_seats + 1:
            keep = slice(0, expected_seats) if crew_dir > 0 else slice(1, None)
            b, k = b[keep], k[keep]
        rowers.append((b, k))

    counts = np.array([len(b) for b, _ in rowers])
    if counts.max(initial=0) == 0:
        return {}, 1, 0
    n_seats = expected_seats or int(min(9, np.bincount(counts[counts > 0]).argmax()))
    if n_seats == 0:
        return {}, 1, 0

    def centres(boxes, keypoints):
        hips = keypoints[:, [11, 12]]
        weights = hips[:, :, 2] * (hips[:, :, 2] >= .25)
        total = weights.sum(1)
        fallback = (boxes[:, :2] + boxes[:, 2:]) / 2
        return np.where((total > 0)[:, None],
                        (hips[:, :, :2] * weights[:, :, None]).sum(1) / np.maximum(total[:, None], 1e-9),
                        fallback)

    complete = np.flatnonzero(counts == n_seats)
    if not len(complete):
        return {}, int(crew_dir), n_seats
    def anchor_quality(fi):
        b, k = rowers[fi]
        c = centres(b, k)
        gaps = np.diff(c[:, 0])
        if len(gaps) and gaps.min() <= 0:
            return -np.inf
        regularity = np.std(gaps) / max(np.mean(gaps), 1) if len(gaps) else 0
        facing = np.array([_facing(person) for person in k])
        facing_penalty = np.mean(facing != crew_dir)
        return float(k[:, [5, 6, 11, 12], 2].mean()) - regularity - 2 * facing_penalty
    anchor = int(max(complete, key=anchor_quality))
    out = {s: {"frames": [], "boxes": [], "kpts": []} for s in range(n_seats)}
    for indices in (range(anchor, n_frames), range(anchor, -1, -1)):
        ab, ak = rowers[anchor]
        slots = centres(ab, ak)
        pitch = np.median(np.diff(slots[:, 0])) if n_seats > 1 else np.median(ab[:, 2]-ab[:, 0])
        for fi in indices:
            b, k = rowers[fi]
            if not len(b):
                continue
            dc = centres(b, k)
            distances = np.linalg.norm(slots[:, None] - dc[None], axis=2)
            nearest = distances.argmin(1)
            mutual = distances.argmin(0)
            inliers = [i for i, j in enumerate(nearest)
                       if mutual[j] == i and distances[i, j] < .45 * pitch]
            shift = np.median(dc[nearest[inliers]] - slots[inliers], axis=0) if inliers else np.zeros(2)
            predicted = slots + shift
            delta = predicted[:, None] - dc[None]
            cost = np.linalg.norm(delta, axis=2) / max(pitch, 1)
            r, c = linear_sum_assignment(cost)
            accepted = [(si, di) for si, di in zip(r, c) if cost[si, di] < .45]
            if any(d2 <= d1 for (_, d1), (_, d2) in zip(accepted, accepted[1:])):
                continue
            slots = predicted
            for si, di in accepted:
                slots[si] = dc[di]
                out[si]["frames"].append(fi)
                out[si]["boxes"].append(b[di])
                out[si]["kpts"].append(k[di])
    tracks = {}
    for si, t in out.items():
        _, order = np.unique(t["frames"], return_index=True)
        if len(order) >= min_frac * n_frames:
            tracks[si] = {kk: np.array(v)[order] for kk, v in t.items()}
    return tracks, int(crew_dir), n_seats
