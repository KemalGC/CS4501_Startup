# Rowing tracking model revision — 2026-11-10

The core automatic crew tracker now retains seat identity through camera motion,
changing scale, perspective compression, short occlusions, and extra detections.
This revises the tracking/association model and pose postprocessing; it does not
train or replace the YOLO neural-network weights. No interface or product-flow
changes were made in this work.

## Measured comparison on the supplied footage

Replayed the **same cached real-model detections** through a frozen copy of the
pre-change tracker and the new tracker: 1,338 sampled frames, five boat segments,
three local videos. This isolates the tracking change from detector variation.

- Observed seat/frame coverage: **9,653/10,704 (90.2%) → 10,272/10,704 (96.0%)**.
- Hardest distant-crew segment: **963/1,544 (62.4%) → 1,489/1,544 (96.4%)**.
- Visual development audit, 20 frames and 160 physical seat/frame cases:
  **141 → 153 correct**, **3 → 0 wrong-seat associations**, **16 → 7 missing**.
  Five of those 160 cases have no usable detector observation, including a seat
  outside the frame. Detector misses cannot be recovered by association alone.
- All predictions preserve original detector boxes/keypoints; no missing pose is
  fabricated, interpolated into observation history, or counted as measured.

| Segment | Baseline coverage | Revised coverage | Correct audit cases |
|---|---:|---:|---:|
| 0185-boat1 | 62.4% | 96.4% | 16 → 28 / 32 |
| 0185-boat2 | 92.0% | 94.2% | 30 → 32 / 32 |
| 9673-boat1 | 91.6% | 94.1% | 31 → 31 / 32 |
| 9674-boat1 | 97.5% | 97.7% | 32 → 30 / 32 |
| 9674-boat2 | 99.9% | 98.2% | 32 → 32 / 32 |

Coverage is not identity accuracy. Audit labels were made by the assistant from
source-video contact sheets, with duplicate crop detections mapped to the same
physical rower. This is a small development audit, not independent ground truth
or a held-out validation set. The clearer first 9674 segment loses two audit
observations to conservative rejection; the oblique second segment also has a
small total coverage reduction. The improvement is not uniform across clips.

## Core changes

- Skeleton-aware cleanup retains overlapping rowers instead of deleting the
  smaller body box. A confident shoulder/hip pair can suppress a one-sided crop
  duplicate even when its other joints are occluded.
- Ordered dynamic-programming association explicitly permits missing seats and
  extra detections. It gates before assignment and rejects nearly equivalent
  alternatives instead of assigning a convenient neighbour.
- Shared camera motion and bounded robust scale estimation update seat positions.
  Local seat spacing sets each horizontal gate, accommodating an oblique shell.
- Seat geometry remains available during an individual rower's absence only
  while other rowers provide continuing support. Loss of crew support for
  approximately 0.75 seconds retires the tracker in that direction.
- An extra detection no longer causes an end rower to be deleted just to force
  eight seats; cox exclusion requires facing evidence.
- Pose cache version is 3, with a shared postprocessing version. New runs cannot
  silently reuse old extraction as if it included the revised duplicate logic.

`rowing_tracker.py` is used by the existing automatic `crew_tracks` path, including
its forward/backward passes. Explicit operator-selected identity tracking and
vision-language blade/contact classification retain their existing association
policies. Long-gap geometric seat recovery is not appearance-based person
re-identification, and camera cuts must still be segmented upstream.

## Validation and artifacts

**79 focused core tests pass**, including seven new regressions for camera jolts,
zoom/perspective, missing seats, clutter, ambiguous duplicates, returning end
seats, retirement after loss, and overlapping people. Fresh ONNX inference also
completed locally on one source frame from each of the three clips.

The full suite ran 765 tests: 754 passed, 10 failures and one timeout remained.
The ten failures also occur with the frozen original tracker (existing job/path
and upload assumptions on macOS). The preview timeout also reproduces with the
original tracker when pointed at the same installed ONNX model. These application
issues were left outside the requested model-only scope. Full logs are saved
alongside the local comparison artifacts.

Replay commands, from `app/strokesense`:

```sh
.venv/bin/python evaluation/tracking/compare.py
.venv/bin/python evaluation/tracking/render_comparison.py --videos
.venv/bin/python -m unittest discover -s tests -p test_rowing_tracker.py -v
```

`baseline.py` preserves the starting cleanup/association implementation.
`labels.json` records audit provenance and raw detection-index labels; cache
SHA-256 checks reject evaluation against regenerated or different detections.
`results.json` records the measured comparison. Private detection arrays, five
before/after MP4s, contact sheets, fresh inference images, and test logs are in
`results/model-tracking-evaluation/` (ignored by Git). No footage was uploaded.

The next accuracy bottleneck is the detector itself on very small or blurred
rowers. Fine-tuning neural weights would require a larger, independently labeled
set of rower boxes/keypoints and held-out boat/video splits; this revision does
not claim that training or validation has happened.
