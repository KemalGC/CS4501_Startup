# Body-motion conditioning — development evaluation

This revision targets clear, side-on rowing body motion. It changes pose-to-motion
conditioning, not app features, technique thresholds, or the detector's weights.
The original implementation is preserved in `baseline_kinematics.py`.

## Changes

- Select a fixed anatomical chain from torso/arm/knee confidence, excluding the
  typically hidden ankles from the side decision. No left/right joint splicing.
- Use confidence-weighted centered quadratic fits. Uniform-confidence clean
  trajectories retain the previous Savitzky–Golay behavior, including endpoints.
- Filter body shape relative to the hip so different joint confidence weights
  cannot turn shared camera translation into apparent body motion.
- Reject only isolated, large, joint-specific reversals with temporal support.
  Shared camera jumps and ambiguous clusters of inconsistent estimates are not
  rejected. Rejected detections become gaps, with existing bounded interpolation
  recorded as estimates, never as direct observations.
- Retain rejection masks in `Kinematics`, preserve them when slicing, and record
  their counts and the conditioning version in the existing measurement JSON.

No anatomical lengths are forced, no ideal stroke is imposed, and real slow
posture changes are retained. The 2D angles remain projected measurements.

## Known-motion benchmark

`compare.py` tests 24 combinations of 15/30 fps, 20/32/40 spm, and clean motion,
confidence-dependent noise, isolated joint jumps, or noise plus camera motion.
The synthetic generator supplies exact reference joint positions. Confidence
correlated with noise is an explicit simulation assumption, not a claim about
YOLO confidence calibration.

Mean RMSE across the six rate/fps settings:

| Corruption | Signal | Original | Revised |
|---|---|---:|---:|
| Clean | Trunk angle | 0.1895° | 0.1895° |
| Variable noise | Trunk angle | 3.2922° | 2.1421° |
| Variable noise | Elbow angle | 8.7185° | 5.7523° |
| Variable noise | Thigh angle | 3.9471° | 2.4791° |
| Variable noise | Hip-relative hand position | 0.0549 torso lengths | 0.0349 torso lengths |
| Isolated joint jumps | Trunk angle | 3.5930° | 0.2239° |
| Isolated joint jumps | Elbow angle | 8.5273° | 0.5754° |

Noise-plus-camera results are similar. These are controlled motion errors, not
independently measured real-video errors. The benchmark includes estimated
positions in RMSE; observation coverage/rejection counts are separately retained.

## Real-footage check and limits

`real_footage.py` applies both versions to the same previously evaluated seat
tracks from all five local boat segments. The revised version rejects 79 joint
samples; usable upper-body frame counts change from 10,139 to 10,093. Accepted
rower-cycle counts change from 204 to 194. Fewer cycles can reflect withholding
unreliable evidence, but that count alone does not prove improved timing.

Visual inspection found alternating wrist localization errors in clear footage.
These cannot safely be resolved by assuming the middle observation is wrong.
Clustered disagreement is therefore retained, rather than silently corrected.
Detector localization and stroke-event timing remain active work items.

77 focused tests pass, including nine new body-motion regressions, physical-angle
preservation, gap provenance, canonical measurement/report equality, tracking,
and evidence integrity. Full results are in `synthetic-comparison.json` and
`real-footage.json`; local logs are in `results/body-motion-evaluation/`.

Run from `app/strokesense`:

```sh
.venv/bin/python evaluation/body_motion/compare.py
.venv/bin/python evaluation/body_motion/real_footage.py
.venv/bin/python -m unittest discover -s tests -p test_body_motion.py -v
```

## Ongoing backbone comparison

`detector_candidates.py` and `detector_sequences.py` compare nano, small, and
medium YOLO11 pose models on identical local frames and nano-derived crop grids.
The application default has not been changed. Candidate weights are official
[Ultralytics release artifacts](https://github.com/ultralytics/assets/releases/tag/v8.4.0),
with release SHA-256 digests verified and recorded in `model_candidates.json`.
The [official inference documentation](https://github.com/ultralytics/inference)
describes the supported ONNX models; generic model capability is not evidence of
rowing-specific accuracy. All source-frame inference stays local.

The initial still-frame overlays show mixed results, including some improved
wrist localization. Full sequence measurements and a clearer localization audit
are needed before adopting a larger backbone. The existing model, source footage,
and prior outputs are preserved.

The full backbone experiment has completed (see `backbone_sequence_results.json`).
Across the two 20-second windows, nano/small/medium retained 4,451 / 4,487 / 4,566
seat observations respectively. CPU extraction took about 96 / 197 / 500 seconds.
A six-crop approximate visible-arm audit gives mean joint errors of 4.30 / 5.77 /
4.48 source pixels; its subjective six-pixel review tolerance and anatomical-side
ambiguity prevent treating those differences as a reliable model ranking. The
small coverage increase does not justify claiming better body-motion accuracy
or replacing the default with a model roughly five times slower.

`joint_audit.py` replays that explicitly qualified diagnostic. `source_clock.py`
checks decoded timestamps: the current clips deviate from their nominal frame
clock by at most 1.53 ms. Source-clock redesign is therefore lower priority for
these clips than joint localization and stroke-event selection.

## Neighboring-frame optical-flow experiment

`temporal_flow.py` runs nano pose inference on four adjacent original frames,
warps their keypoints into the target with bidirectional Lucas–Kanade flow, and
takes a median when at least three estimates survive. It uses the same fixed
scene tiles, a hip proximity identity gate, pose confidence >= .35, flow error
< 20, and round-trip error < 1 source pixel. It remains an offline experiment.

On the same six approximate assistant arm annotations (18 joints), mean error
is 4.2992 px for the baseline versus 4.2998 px for temporal flow. Wrist mean error
increases from 4.5444 to 5.1294 px; in case 3 it increases from 4.6772 to 8.7039 px
despite all five estimates passing the flow gate. Differences across most cases
remain below annotation uncertainty, so these are diagnostic numbers, not an
accuracy ranking. The visual comparison provides no consistent reason to adopt
this added inference cost. Production remains unchanged by this experiment.

Private input/output evidence is in `results/body-motion-evaluation/temporal-flow/`:
per-case vote arrays and validity masks, source-pixel comparison, and results JSON.
Repeated neighboring predictions can share a localization bias; a consistent flow
round trip is not proof of anatomical correctness. Next localization work should
focus on distinguishing anatomical-side/limb ambiguity and improving direct pose
estimates, rather than assuming temporal agreement implies accuracy.

## Horizontal-reflection consistency experiment

`mirror_consistency.py` runs the same nano model and reflected tiles on a mirrored
frame, maps x coordinates back, swaps the COCO left/right joint indices, and
compares the reflected prediction and an equal-weight average with the original.
The target identity is matched by hip proximity, not by ground-truth joint labels.
On the six approximate assistant arm cases, mean errors are baseline 4.299 px,
mirrored 5.594 px, average 4.729 px. Wrist errors increase in aggregate. These
uncertain labels do not certify a ranking, but provide no reason to adopt the
added cost. Production is unchanged. Private arrays/images/results are under
`results/body-motion-evaluation/mirror-consistency/`.

## Undefined angle geometry

A numerical correction in `kinematics` now treats zero-length or nonfinite
segments as unavailable angles. The old epsilon denominator returned a fabricated
90-degree interior angle for coincident endpoints, while atan2(0,0) returned a
fabricated upright torso/thigh. Separate unit-vector normalization also removes
an arbitrary dependence on coordinate scale. A collapsed torso cannot count as
visible motion supporting a stroke. No new limb-length or ideal-form assumption
is introduced; finite nonzero segments retain their projected angles.

Four `test_angle_geometry.py` regressions cover analytic angles across coordinate
scales, coincident and nonfinite endpoints, and high-confidence collapsed torsos.
A scan of the five cached tracking segments found zero exact coincident smoothed
torso/upper-arm/forearm/thigh segments. This is a mathematical validity safeguard,
not a claimed measured accuracy gain on those clips.

## Torso fluctuation traced to crop-boundary competition

`torso_candidates.py` and `torso_replay.py` inspect IMG_9674 source frames
416–426 (analysis frames 208–213), the torso fluctuation seen in the phase audit.
The source video and model SHA-256 hashes match the historical detection cache.
Both left/right hips jump in that cache, so averaging torso sides is not a remedy.

The 20-second and 21-second auto-tile grids differ (395 px vs 418 px CPU tiles).
Replaying identical source pixels with these grids changes which pose wins.
With the 21-second grid, the first tile ends at source x=418 and cuts through the
rower's body. The next tile contains the body fully. At analysis frame 212:

- Partial crop: person score .715, torso confidence .719, trunk -15.4°, local
  bounding box right edge exactly 418 (the crop boundary).
- Complete crop: person score .705, torso confidence .989, trunk -35.6°.

At frame 213, partial/complete person scores .753/.704 similarly select the
partial crop; trunk estimates are -15.8°/-32.7°. The torso appears in a sustained
finish posture in the source images. This provides a concrete mechanism for
large pose changes: person-score ordering can favor a cropped-off body over a
more complete pose of the same person. Several anchors within each tile repeat
these predictions; they are not independent votes.

CPU and configured-provider replays agree on this behavior; minor numerical
changes can change the winner when scores are close. A crop-edge-aware duplicate
preference is a justified next candidate, but must preserve partial-only detections
and distinguish genuinely overlapping rowers. No new suppression rule is adopted
yet. Private raw candidates, crop bounds, arrays, source comparisons and replay
results are under `results/body-motion-evaluation/torso-candidates/`.

## Crop-boundary preference adopted

The detector now records whether a proposal touches an internal crop boundary
(within max(2 px, 1% of the smaller crop dimension)). Actual source-image edges
are excluded. Duplicate suppression may replace a truncated winner only when:

- Shared torso landmarks establish the existing anatomical duplicate match.
- The alternative does not touch an internal crop boundary.
- Its person score is at least 80% of the winner's score.
- Its mean shoulder/hip confidence is at least 0.10 higher.

The whole alternative pose and its original score are kept; joints are not fused.
Partial-only detections remain. Missing crop metadata preserves score ordering.
These are conservative engineering gates, not calibrated probabilities.
`torso-landmarks-v4-crop-edges` invalidates old base/refined pose caches through
the shared detector-postprocessing version.

`crop_edge_compare.py` freezes the raw proposals and grids, then applies frozen
v3 and candidate v4 suppression to exactly the same input. Across six audited
torso frames plus the six existing arm cases, detection counts remain identical.
Frames 212 and 213 switch from -15.4°/-15.8° truncated torso estimates to the
complete-pose -35.6°/-32.7° estimates; the source overlay shows hip and knee
locations restored to the visible body rather than collapsed at the crop edge.
The other four torso selections and all six arm-case selections are unchanged.
This is a targeted failure correction, not an independent aggregate accuracy
benchmark. Raw proposals, masks, output poses and source overlays are private
under `results/body-motion-evaluation/crop-edge-comparison/`.

Eight new tests cover replacement, weak alternatives, distinct overlapping
people, partial-only retention, source-image boundaries, detector propagation,
metadata validation and legacy ordering. Six existing pose-merge tests and the
updated cache-identity test pass. Full suite: 808 tests with the same ten known
application failures and no new failures. Four standalone legacy rowing tests
also pass.
