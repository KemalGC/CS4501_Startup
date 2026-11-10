# StrokeSense accuracy work handoff

Continue improving the core tracking model and rowing analysis for standard, unobscured rowing. Preserve the app's existing offering and UI. Prioritize correct body motion and phase timing over smoother curves, higher detection counts, or more accepted strokes.

The previous run is paused at the user's request. This handoff is for a new agent; do not resume an unattended background goal without a new instruction to work. The next concrete task is to broaden validation of the newly implemented crop-boundary duplicate selection rule.

## Repository and starting state

- Application repository: `/Users/nategiraudeau/Documents/ChatGPT/stroke-sense/app`.
- Python package and test working directory: `app/strokesense`.
- Working branch: `codex/strokesense-video-testing`.
- Published implementation commit: `9bde16f7dd78cfe479ddb39e469365a6d07017d9`. This handoff is a subsequent documentation change.
- Remote: `https://github.com/KemalGC/CS4501_Startup.git`.
- The parent `stroke-sense` folder is a separate repository. Use the application repo for commits, not its parent.
- Python: `.venv/bin/python` from `app/strokesense`. The system Python does not have all required dependencies.
- No `AGENTS.md` was found during the prior run; check again for new instructions.

The implementation, regression tests, evaluation scripts/results, and PDF report are committed. No neural weights were retrained. The default remains `models/yolo11n-pose.onnx`.

Start by reading this file, [the report](reports/StrokeSense_Overnight_Improvement_Report.pdf), and the final sections of [the work log](ACCURACY_WORK_LOG.md). Read the longer experimental history only when relevant.

## Preserve the unrelated workspace changes

The working tree was intentionally not cleaned. These changes predated the overnight accuracy work and were not included in its commit:

- Modified: `.gitignore`, `README.md`, `strokesense/README.md`, `strokesense/strokesense/jobs.py`, `strokesense/strokesense/web.py`, `strokesense/tests/test_jobs.py`.
- Untracked: `run-local.sh`, `strokesense/strokesense/boat_scenes.py`, `boats.py`, `crew_bundle.py`, and tests `test_automatic_upload.py`, `test_boat_scenes.py`, `test_boat_windows.py` under `strokesense/tests/`.

Recheck `git status` before editing. Do not reset, discard, bulk-stage, or claim ownership of these files. Some related extraction/cache changes were included with the tracking implementation because they support the evaluated core behavior. The remaining dirty application/UI work is separate.

HTTPS Git push had no usable local credentials. Publication succeeded through the connected GitHub tools, then the local branch was synchronized to the identical published file tree. The local and remote branch heads matched at handoff. Prefer normal Git if credentials become available; otherwise use the connected GitHub service, inspect the remote head, and preserve concurrent changes. Do not force-push. No PR was created.

## Implemented changes to retain

| Area | Current behavior | Main files |
|---|---|---|
| Seat identity | Bidirectional ordered seat matching from a complete anchor; hip-based positions, common translation/zoom, local spacing, explicit missing observations | `strokesense/rowing_tracker.py`, `pose.py` |
| Duplicate detections | Anatomical torso matching preserves genuinely overlapping people; crop-truncated winners can be replaced by a stronger complete pose | `pose_merge.py`, `PoseDetector.__call__` in `pose.py` |
| Body motion | Fixed anatomical side excluding ankles from side choice; confidence-weighted hip-relative filtering; conservative isolated-jump rejection; interpolation remains estimated evidence | `body_motion.py`, `kinematics.py` |
| Angle validity | Coincident/nonfinite segments produce unavailable angles; collapsed torsos cannot support strokes | `kinematics.py` |
| Event clock | Rate, drive and recovery use fractional catch/finish/end times consistently; segmented tracks offset all event times | `strokes.py`, `dynamic_crew.py` |
| Finish selection | Locally supported hand reversal determines finish; unsupported hand evidence retains the mixed motion cue | `strokes.py` |
| Rhythm | Missing samples retain their original time positions; no concatenating observed runs into a shorter clock | `strokes.py`, `crew.py` |
| Crew timing | Strict majority of distinct identities, each catch used once, all valid cycle endpoints retained, stale offsets cleared | `synchrony.py`, `crew.py` |
| Provenance | Existing JSON includes conditioning/timing versions and rejection counts | `report.py`, `cli.py` |

Current versions: detector postprocessing `torso-landmarks-v4-crop-edges`; body conditioning `camera-relative-joint-quality-v1`; stroke timing `supported-hand-finish-v1`; synchrony `one-use-crew-events-v1`; pose-cache version `3`.

### The most recent fix and its evidence

IMG_9674 analysis frames 212 and 213 (source frames 424 and 426, first boat, leftmost slot 0) exposed a crop-boundary error. A crop ending at x=418 cut through the rower yet slightly outranked a complete crop by person score. It collapsed hip/knee positions and shifted projected trunk angle by roughly 17-20 degrees.

The implemented preference requires an existing anatomical duplicate match, an untruncated alternative, person score at least 80% of the truncated winner, and mean shoulder/hip confidence at least 0.10 higher. Internal crop edges use a margin of max(2 pixels, 1% of the smaller crop dimension). Actual source-image boundaries are excluded. The whole alternative pose is retained with its original score. Partial-only detections remain usable.

Identical-proposal replay corrected the two failure frames, left the other four inspected torso selections and six existing arm-audit selections unchanged, and preserved detection counts across all twelve frames. A fresh configured-provider run also produced a stable torso sequence there. This is targeted development evidence, not broad held-out validation.

## Ordered next steps

### 1 Validate crop-boundary selection on more footage

This is the first task. Do not start by changing its thresholds.

1. Read [the crop analysis](body_motion/README.md), `body_motion/crop_edge_compare.py`, `torso_candidates.py`, and `torso_replay.py`.
2. Extend paired suppression replay to additional times in all three videos, including frames not used to identify the problem. Include ordinary clear rowing, overlapping rowers, partial-only detections, and people at real image edges.
3. Run inference once per frame/crop and apply frozen v3 and current v4 suppression to the same raw proposals. Freeze crop bounds and provider settings. Record which whole pose was replaced, confidence values, identity match, and changed joint locations.
4. Inspect source pixels for changed selections. Do not judge improvement solely by temporal smoothness or confidence. Keep per-case before/after overlays and a source-frame ledger.
5. Add regression tests only for newly demonstrated failure mechanisms. Consider non-transitive duplicate matches and replacement order when reviewing the suppression logic.

Acceptance: demonstrate correct same-person replacements beyond the original example, preserve separate neighboring people and partial-only detections, quantify observed regressions, and run appropriate tracking/merge tests. If evidence reveals a regression, fix or narrow the rule before claiming general improvement. Do not promote selected-frame success to an aggregate accuracy rate.

### 2 Build a stronger joint and event benchmark

The existing six approximate arm annotations and selected event reviews are too small and uncertain for reliable model ranking.

- Create a reproducible manifest with source hashes, decoded frame numbers, analysis-to-source mapping, person/seat identity, anatomical side, visibility and annotation uncertainty.
- Include shoulder, hip, elbow, wrist and knee positions, plus catch and finish intervals. For indistinct reversals, label a plausible interval rather than an unjustified exact frame.
- Separate development cases from held-out cases before tuning. Keep ordinary unobscured rowing central to the benchmark.
- Obtain independent human/coach review where possible. Assistant annotations may guide debugging but must remain explicitly distinguished from independent ground truth.
- Report joint errors in pixels and torso-normalized units, angle errors where reference geometry supports them, event-time errors, missing evidence and wrong-identity rates separately.

Acceptance: a future model/filter change can be evaluated against fixed labels, not just against another model's predictions. If independent labels are unavailable, continue concrete source-based debugging but keep claims limited.

### 3 Improve remaining localization errors from identified causes

Prioritize persistent wrist/hip errors over another general smoothing pass. The crop-boundary discovery showed that high joint confidence can coexist with a wrong pose and that the failure may originate before kinematic filtering.

- Inspect raw crop proposals and selected poses before changing downstream timing.
- Keep one anatomical chain for arm measurements; do not splice left/right joints frame by frame.
- Preserve genuine body motion and camera invariance. Do not force ideal stroke shapes, fixed limb lengths, or crew synchronization into each rower's motion.
- Evaluate any proposed pose refinement on the held-out benchmark. Fine-tuning is a later option once suitable labels and a baseline exist; no fine-tuning infrastructure or trained checkpoint was produced overnight.

Acceptance: better labeled localization or demonstrated source-supported failure correction, with quantified coverage/latency tradeoffs and no invented observations.

### 4 Refine phase timing with localization under control

Read [event reviews](events/README.md) and [synchrony rationale](synchrony/README.md). Current hand-based finishes fix gross knee-driven late minima, but some hand trajectories remain flat, blurred or biased by hip estimates.

- Review the remaining largest phase disagreements on fresh v4 detections. Older cached poses may contain the crop-selection failure already fixed.
- Compare hand reach, shoulder-relative hand movement, elbow motion and source imagery without assuming any one cue is ground truth.
- Preserve real rate changes and individual timing offsets. Do not force events onto a regular cycle or reuse catches.
- Keep discrete frame references for snapshots distinct from fractional measurement times. Current evidence snapshots retain discrete finish/end references even though stroke durations use fractional fields.

Acceptance: improved source-labeled event timing or better-supported abstention, a consistent event clock, and preserved clean-motion/fault behavior. More accepted cycles, smaller crew offsets, and smoother curves do not establish accuracy.

## Existing evidence and its limits

- Tracking coverage on five cached segments: 9,653/10,704 to 10,272/10,704 observed seat-frames, or 90.2% to 96.0%. The difficult first 0185 boat improved 62.4% to 96.4%. The second 9674 boat decreased 99.9% to 98.2%.
- Assistant visual identity audit: correct 141/160 to 153/160; wrong-seat assignments 3 to 0; missing 16 to 7. Selected development frames, not independent labels. Tracking results predate the final v4 detector change.
- Controlled confidence-dependent noise: trunk RMSE 3.29 to 2.14 degrees; elbow 8.72 to 5.75 degrees. Synthetic assumptions, not measured real-video accuracy.
- Ideal sinusoidal timing: quantization-only rate RMSE 0.425 to 0.00171 spm. This does not measure real catch/contact accuracy.
- Latest full dirty-workspace suite: 808 tests, ten known failures. Isolated committed application snapshot: 794 tests, the same ten failures. Four standalone legacy rowing/fault checks passed. Different counts reflect excluded pre-existing unrelated tests.
- Fresh final v4 run: IMG_9674, 21 seconds, eight rowers, 54 accepted cycles, nine supported crew events. Saved timing/provenance checks passed. Counts and estimated cadence are diagnostics, not accuracy labels.

Do not combine metrics from these different baselines into a single claimed final-model accuracy percentage.

## Experiments already tried

| Experiment | Finding and decision |
|---|---|
| YOLO11 nano, small and medium | Small coverage changes; no convincing joint-localization gain in the approximate audit. Medium cost about 5x CPU inference time in the paired sequence test. Nano retained. |
| Tighter person crops | Mixed results and no consistent gain. Not adopted. |
| Neighbor-frame optical flow consensus | No overall arm-audit gain; one wrist worsened despite good flow round trips. Not adopted. |
| Mirrored inference and averaging | No convincing gain; wrist errors increased in the small audit. Not adopted. |
| Full source rate versus half rate | Identical detections on all 296 shared frames, but changed timing/counts did not establish accuracy. 72-second versus 32-second CLI runs on one 20-second window. Default sampling retained. |
| Wider time-matched smoothing | Helped white noise, blurred clean motion, barely helped correlated noise. Not adopted. |
| Bilateral torso averaging | Both hip estimates shifted in the audited crop failure; averaging would not solve it. Not adopted. |
| Source timestamp rewrite | Decoded versus nominal clock discrepancy under 1.6 ms on supplied videos. Not prioritized. |

Do not rerun these unchanged on the same six arm labels. Revisit only with a concrete new mechanism, different candidate, or stronger benchmark.

## Local data and reproducibility

From `app/strokesense`, original videos are `../../test-footage/IMG_0185.MP4`, `IMG_9673.MP4`, and `IMG_9674.MP4`. Videos, ONNX weights and `results/` artifacts are local and ignored. They are not available merely by cloning the repository.

Useful artifact locations under `app/strokesense`:

- `results/model-tracking-evaluation/`: frozen before/after track arrays, comparison media and cache-ledger metadata.
- `results/body-motion-evaluation/detector-candidates/`: fixed-grid inference samples and sequence caches.
- `results/body-motion-evaluation/torso-candidates/`: raw alternatives, crop bounds and duration/provider replay.
- `results/body-motion-evaluation/crop-edge-comparison/`: paired v3/v4 proposals, selected poses, source overlay and full-test log.
- `results/event-evaluation/` and `additional/`: source-only event contact sheets and measurement traces.
- `results/crop-edge-pipeline/IMG_9674--3fe85c5c931fa8d19c9c/`: fresh final v4 cache, metrics, snapshots and report.
- `results/final-pipeline-evaluation/` and `results/full-rate-evaluation/`: earlier half/full-rate experiments.

Many evaluation scripts depend on these private artifacts and use fixed development cases. Read their inputs before running them in a new checkout. Historical JSON results remain valid records of the named version; rerunning a script against current production modules may produce different values. Preserve historical results and write a new comparison rather than overwriting evidence silently.

Record source/model hashes, actual frame rate and stride, start offset, crop bounds, postprocessing version and execution provider. Automatic crop selection depends on analysis duration: a 20-second versus 21-second request changed the grid in the demonstrated failure. CPU-only benchmarks and configured CoreML runs are not interchangeable speed comparisons.

## Commands for the next working session

Run these from `app/strokesense` after inspecting the current tree:

```sh
git status --short --branch
git log -1 --oneline
.venv/bin/python -m unittest discover -s tests -p test_crop_edges.py -v
.venv/bin/python -m unittest discover -s tests -p test_pose_merge.py -v
.venv/bin/python -m unittest discover -s tests -p test_rowing_tracker.py -v
.venv/bin/python -m unittest discover -s tests -p test_body_motion.py -v
.venv/bin/python -m unittest discover -s tests -p test_finish_phase.py -v
.venv/bin/python -m unittest discover -s tests -p test_synchrony.py -v
.venv/bin/python tests/test_analysis.py
```

With the required local artifacts present, reproduce the focused crop comparison:

```sh
.venv/bin/python evaluation/body_motion/crop_edge_compare.py
```

For a fresh final-path smoke test, use a new output directory:

```sh
.venv/bin/python -m strokesense.cli ../../test-footage/IMG_9674.MP4 \
  --out results/next-agent-smoke --duration 21 --crew-size 8 --threads 4 --fresh
```

Pass that run's actual `metrics.json` path to `evaluation/pipeline/verify.py`. It checks numerical/provenance invariants, not accuracy. Run the full suite after a substantive change:

```sh
.venv/bin/python -m unittest discover -s tests > /tmp/strokesense-next-agent-tests.log 2>&1
```

The ten baseline failures are in `test_jobs` (five), `test_revocation` (two), `test_upload` (two), and `test_web` (one). They include macOS `/var` versus `/private/var` path behavior and existing job-publication expectations. A cold-model preview timeout also occurred intermittently earlier; it did not recur in the latest runs. Compare exact failure names with `results/body-motion-evaluation/crop-edge-comparison/full-tests.log` before calling a failure pre-existing. Do not alter unrelated product code to hide them.

## Deliverable for the next agent

Produce one evidence-backed accuracy improvement or a completed broader validation of the current crop fix. Save a concise results note with baseline/candidate versions, exact inputs, measured improvements and regressions, reviewed source frames, and test outcomes. Update the work log and this handoff's remaining tasks. Preserve the user's UI/offering constraint and all unrelated workspace changes.
