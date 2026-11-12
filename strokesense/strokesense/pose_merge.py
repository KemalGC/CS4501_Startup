"""Shared-landmark duplicate suppression for local pose crops."""
import numpy as np

VERSION = "torso-landmarks-v4-crop-edges"


def crop_edge_flags(boxes, crop, frame_width, frame_height):
    """Mark internal crop boundaries, never the actual source-image boundary.

    Input boxes are local to the crop. This records possible truncation; it is
    not grounds to discard a detection without a stronger matching alternative.
    """
    boxes = np.asarray(boxes)
    x0, y0, x1, y1 = crop
    width, height = x1-x0, y1-y0
    margin = max(2., .01*min(width, height))
    return (((boxes[:, 0] <= margin) & (x0 > 0))
            | ((boxes[:, 1] <= margin) & (y0 > 0))
            | ((boxes[:, 2] >= width-margin) & (x1 < frame_width))
            | ((boxes[:, 3] >= height-margin) & (y1 < frame_height)))


def merge_refined_detections(boxes, scores, keypoints, *, conf=.25, iou=.5,
                             crop_truncated=None):
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
    if crop_truncated is None:
        crop_truncated = np.zeros(len(scores), dtype=bool)
    crop_truncated = np.asarray(crop_truncated)
    if crop_truncated.shape != scores.shape or crop_truncated.dtype != np.bool_:
        raise ValueError('invalid_crop_truncation')
    valid = (np.isfinite(boxes).all(1) & np.isfinite(scores)
             & np.isfinite(keypoints).all((1, 2))
             & (boxes[:, 2:] > boxes[:, :2]).all(1) & (scores > conf))
    boxes, scores, keypoints = boxes[valid], scores[valid], keypoints[valid]
    crop_truncated = crop_truncated[valid]
    torso_quality = keypoints[:, [5, 6, 11, 12], 2].mean(1)
    area = np.prod(boxes[:, 2:] - boxes[:, :2], axis=1)
    core = keypoints[:, [0, 5, 6, 11, 12]]
    keep = []
    for i in np.argsort(-scores, kind='stable'):
        duplicate = False
        for position, j in enumerate(keep):
            inter = float(np.prod(np.maximum(0, np.minimum(boxes[i, 2:], boxes[j, 2:])
                                            - np.maximum(boxes[i, :2], boxes[j, :2]))))
            if inter == 0:
                continue
            shared = (core[i, :, 2] >= .35) & (core[j, :, 2] >= .35)
            anatomical = shared.sum() >= 3 or (shared[1:3].any() and shared[3:5].any())
            if anatomical:
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
                # Only an anatomically matched, materially stronger complete
                # torso may replace a truncated winner. Keep original scores
                # and a whole pose; never fuse unrelated joints or drop partials.
                if (anatomical and crop_truncated[j] and not crop_truncated[i]
                        and scores[i] >= .8*scores[j]
                        and torso_quality[i] >= torso_quality[j]+.1):
                    keep[position] = int(i)
                break
        if not duplicate:
            keep.append(int(i))
    indices = np.asarray(keep, dtype=int)
    return boxes[indices], scores[indices], keypoints[indices]


