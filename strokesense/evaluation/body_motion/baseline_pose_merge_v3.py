"""Shared-landmark duplicate suppression for local pose crops."""
import numpy as np

VERSION = "torso-landmarks-v3"


def merge_refined_detections(boxes, scores, keypoints, *, conf=.25, iou=.5):
    """Merge crop duplicates using shared confident torso landmarks.

    Box-only NMS can keep a small torso crop and a full-body box for the same
    person, while dropping two genuinely overlapping people. Prefer agreement
    on three core landmarks or a visible shoulder–hip pair when available; otherwise keep the
    established IoU fallback. This is duplicate suppression, not re-identification.
    """
    boxes = np.asarray(boxes, float)
    scores = np.asarray(scores, float)
    keypoints = np.asarray(keypoints, float)
    if scores.ndim != 1 or boxes.shape != (len(scores), 4) or keypoints.shape != (len(scores), 17, 3):
        raise ValueError('invalid_detections')
    valid = (np.isfinite(boxes).all(1) & np.isfinite(scores)
             & np.isfinite(keypoints).all((1, 2))
             & (boxes[:, 2:] > boxes[:, :2]).all(1) & (scores > conf))
    boxes, scores, keypoints = boxes[valid], scores[valid], keypoints[valid]
    area = np.prod(boxes[:, 2:] - boxes[:, :2], axis=1)
    core = keypoints[:, [0, 5, 6, 11, 12]]
    keep = []
    for i in np.argsort(-scores, kind='stable'):
        duplicate = False
        for j in keep:
            inter = float(np.prod(np.maximum(0, np.minimum(boxes[i, 2:], boxes[j, 2:])
                                            - np.maximum(boxes[i, :2], boxes[j, :2]))))
            if inter == 0:
                continue
            shared = (core[i, :, 2] >= .35) & (core[j, :, 2] >= .35)
            if shared.sum() >= 3 or (shared[1:3].any() and shared[3:5].any()):
                # Torso lengths normalize the tolerance without using long oars,
                # limbs or full-box heights as identity evidence.
                scales = []
                for index in (i, j):
                    shoulders = keypoints[index, [5, 6]]
                    hips = keypoints[index, [11, 12]]
                    a, b = shoulders[:, 2] >= .35, hips[:, 2] >= .35
                    if a.any() and b.any():
                        scales.append(np.linalg.norm(shoulders[a, :2].mean(0) - hips[b, :2].mean(0)))
                scale = min(scales) if scales else min(boxes[i, 3]-boxes[i, 1], boxes[j, 3]-boxes[j, 1])*.3
                tolerance = max(3., .35 * float(scale))
                distances = np.linalg.norm(core[i, shared, :2] - core[j, shared, :2], axis=1)
                duplicate = (inter/min(area[i], area[j]) > .3
                             and float(np.median(distances)) < tolerance
                             and float(np.quantile(distances, .8)) < tolerance*1.5)
            else:
                duplicate = inter/(area[i]+area[j]-inter) > iou
            if duplicate:
                break
        if not duplicate:
            keep.append(int(i))
    indices = np.asarray(keep, dtype=int)
    return boxes[indices], scores[indices], keypoints[indices]
