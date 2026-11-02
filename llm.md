# StrokeSense current handoff

## Preserved history

The preceding root log is preserved byte-for-byte in [llm-history-2026-11-01-resilient-results.md](llm-history-2026-11-01-resilient-results.md), original Git blob `2ac911f826f9a87bee5364c80b4c3d71f18cf65c`. Its links preserve the dynamic-crew log, complete October history and manual companions. No historical entries or private scheduling metadata were discarded. The October 27–29 sprint remains ended; no automation was resumed, deleted or rescheduled.

## 2026-11-01-1947-manual — five-stroke assessment and real-video quality checks (#102, #103, #104)

### Session and branch safeguards

This is an explicit user-authorized manual continuation, not an out-of-window sprint. Actual start `2026-11-01T19:47:55.010186-05:00` (America/New_York), initial monotonic22.819814906. Reporting checkpoint `2026-11-01T20:11:05.707122-05:00`, elapsed1390.697seconds (23m10.697s). This excludes subsequent documentation/publication/email and earlier interrupted work; no invented30-minute claim.

Continued existing topic `dev/2026-11-01-1927-report-gaps`, recovered at958da3ada39c4d11af367aac646ebebaa58252f4, originally based on integration5ba092efd3f2a03051a213b98da0f520d66510b0. Existing #102/#103 work was inspected and preserved; narrowly scoped #104 was added for the new five-stroke/parallel request. Integration was reread at5ba092ef and main at3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc. Neither main/default nor settings/schedules were written. No PR, force-push, branch deletion or private-footage publication. All code is on the dated topic. Integration/email are pending at this checkpoint and must only be confirmed after tool results.

### Current result and important open limitation

Implemented a five-usable-stroke short-assessment policy, bounded parallel per-cycle measurement, explicit stroke windows, short-gap qualification and the pending NaN report repair. Actual model tests on two licensed public videos completed. A short sample gained selected-rower observation coverage, but the longer12-second real-video test STILL produced only one usable stroke and no rower reached five. Detection/tracking quality is therefore NOT solved. Keep #103 open for visibility-labeled identity/dropout evaluation; do not equate passing executable CI with sufficient real-world results.

### Changes and traceability

#102: existing repaired `kinematics.smooth` handles contiguous finite spans independently, keeping missing samples unavailable and clean-input numerics compatible. The reproduced report-stage path was CLI -> render.fault_snapshot_requests -> kinematics.smooth -> SciPy Savitzky-Golay edge fit, raising ValueError on NaN tracking gaps. This is consistent with the supplied generic child-failure log, not a diagnosis of the unavailable Windows traceback. Existing end-to-end regressions generate actual fault snapshots, charts, HTML/JSON/evidence with synthetic partial tracks and unavailable optional video encoding. Worker diagnostics print a bounded exception category rather than private exception text. Earlier tests-first checkpoints are retained; interrupted-worker observations are not invented here.

#103: existing `pose_merge.py` uses shared confident torso landmarks to distinguish duplicate crop detections from overlapping adjacent people, rather than bounding-box overlap alone. The refined merge/cache setting is torso-landmarks-v1. Ordinary manual same-boat confirmation, closed-set identity association and abstention remain. Added bounded real-inference scripts record source/model hashes, times, counts and annotated frames; raw private recordings are never uploaded. No model retraining, guaranteed identity recognition or empirical technique-accuracy claim.

#104: user story and acceptance are in the issue. `strokes.analyse` segments first, then measures independent catch-to-catch windows with ordered ThreadPoolExecutor work, strict1–4worker bounds. Selected analysis defaults to4measurement workers; pose inference, video decoding, identity tracking and rendering are NOT duplicated or parallelized. Parallel numeric ordering matches serial. This is logical stroke-window processing, not export of separate MP4 files, and no overall speedup is claimed.

`dynamic_crew.rowers_from_selected` accepts only internal gaps up to0.2seconds with at least90% observed frames per accepted cycle; catch, finish, next catch and their immediate neighbors must be observed. Long/leading/trailing gaps still split analysis. No missing keypoint is promoted into the observation history; displayed missing coordinates remain NaN. Per-stroke observed/gap counts and policy short-internal-gaps-v1 are saved. Five usable cycles PER ROWER yields short_assessment_ready; fewer are preliminary, not discarded or padded. Five is an engineering sample policy, not coach approval/statistical proof. A single cycle no longer receives100/100consistency.

Reports expose source-time catch/finish/next-catch windows and quality counts in HTML details and a version1 JSON stroke_windows manifest. Legacy strokes without measured counts use null, not invented zeros. Raw cadence remains qualified, scores are explicitly provisional heuristics, and coaching release stays independently withheld. A minor over-compression cue wording changed during file publication; it remains unreviewed and no thresholds/approval were validated by that edit. New reports require re-analysis; old outputs are not rewritten. Guide: [strokesense/FIVE_STROKES.md](strokesense/FIVE_STROKES.md).

### Observed test-first and regression results

Test-only commit5e19b58b4389969230d4f85ba4693e08a3ff544a added five tests in test_short_strokes.py. Before production changes, `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s strokesense/tests -p test_short_strokes.py -v` produced THREE expected missing-behavior assertions (one-frame gaps destroyed cycles, workers parameter missing, five-stroke assessment missing); two long-gap/landmark cases already passed. This was not an import failure. After changes all five passed; exact published-source run took0.207s.

Test-only89eb36a5d77765ccda79b7d7abbf5884f07d3d28 added test_stroke_windows.py; before its production changes the same discovery command with that filename had two expected missing-report/manifest failures. Both passed after implementation. Synthetic eight-cycle fixture with one missing sample per cycle improved fromZERO toSEVEN usable cycles, while actual observed count remained487/495 and each accepted cycle reported its gap. This is synthetic algorithmic evidence, not a real-video accuracy metric.

First expanded full suite found one legacy-fixture compatibility error because a historical stroke fixture exposed only to_dict(), not direct attributes. Manifest compatibility was corrected without weakening the old test; unknown counts are null. Final local `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python strokesense/quality.py` passed531test executions in53.676s plus four legacy synthetic checks. Counts include existing repeated fixture discovery, not531unique cases. Diff whitespace checks passed. The local source matches published production files, with only an inconsequential comment difference in strokes.py. Actual old report-gap/merge/cache regressions remain included.

Production checkpoint2566c42f4d320eb2d093eddc85d7d40d3ce0b9b0 passed complete offline CI https://github.com/KemalGC/CS4501_Startup/actions/runs/41370299524 and existing native Chrome flows https://github.com/KemalGC/CS4501_Startup/actions/runs/41370299582. Chrome covers import, selection, later-frame review, library, results/evidence/comparison; it is not a new independent visual/accessibility audit of every stroke-table cell. Local Python3.13.5 lacks ONNX Runtime and cached weights; read-only doctor is incomplete, not a claimed inference success. No Windows run occurred here.

### Actual public-video/model evidence, including negative results

Real CPU inference was executed in GitHub's Linux runner, not merely a test double: https://github.com/KemalGC/CS4501_Startup/actions/runs/41370299563. Pinned evaluation stack: torch2.5.1CPU, ultralytics8.3.0, onnx1.17.0, onnxruntime1.23.2, numpy1.26.4, scipy1.14.1, OpenCV4.11.0.86. Official Ultralytics v8.3.0 YOLO11n-pose weights exported to ONNX; exported model SHA2569e5a8714a43c206251d5c9a1d1ec2771225c02487bd5512499b645c8fa06a91c. Exact before/after comparisons use the same raw predictions within the run. Export bytes can differ across runs; do not assume an earlier export hash is identical.

Public sources verified on their Commons license pages:
- Splash tv, Rowing boat racing 8-man + cox.webm, CC BY-SA4.0: https://commons.wikimedia.org/wiki/File:Rowing_boat_racing_8-man_%2B_cox.webm . Source SHA256971dbbea9b924565428849377c408eeb568f7fd99d89c4ad71319be0b9d283ac.
- Jan Ainali, Rowing in Amsterdam.webm, CC BY-SA4.0: https://commons.wikimedia.org/wiki/File:Rowing_in_Amsterdam.webm . Source SHA256ec7242de11a21140848c39ccce2e0178de335a0c6da20f9e2be36d9a36d3bb15.

Artifact real-video-comparison contains sources.json, attribution, actual raw proposals, metrics and annotated derivative frames under CC BY-SA4.0; raw private videos/model weights are not committed. The public videos are DEVELOPMENT samples, not held-out validation. The eight-rower reference was assistant-visually selected, not human ground truth. Images were inspected for plausible selected crew/coxswain exclusion, not named-person identification.

Short8-person sample,25frames/200possible rower-frame observations: ordinary duplicate merge retained171/200(85.5%); revised torso-aware merge183/200(91.5%), a6percentage-point coverage increase. Slots before[18,19,20,21,24,25,24,20], after[22,23,23,20,25,24,25,21]; some individual slots worsened. Total detected boxes260->235 as duplicates decreased. An independent local replay of saved real predictions reproduced171->183. This is OBSERVATION COVERAGE, not identity accuracy/recall or proof all assignments are correct.

Crowded Amsterdam sample:30frames;197->204detected boxes. No crew was confirmed, so selected-crew tracking was deliberately not run; higher count alone is neither an accuracy gain nor evidence of correct boat grouping.

Longer8-person source window1–13seconds:150sampled frames, real model elapsed136.757s. Observed slot counts[18,38,32,91,84,59,31,17]. Strict-gap usable stroke counts[0,0,0,0,1,0,0,0]; new short-gap countsIDENTICAL. None reached five. No accepted cycle contained a gap. Serial/parallel outputs matched; timings0.021774s/0.021768s are effectively equal and only one cycle survived, so this does not demonstrate real multicyle parallel speedup. Synthetic multiple-cycle tests did exercise the worker pool. Without visibility/identity labels, the long-run missing observations cannot be conclusively divided into actual exits versus tracking failures. This result is a blocker to claiming overall detection/following quality solved, not a failed executable test to hide.

The user's private Video18.mp4 was not available in this continuation's mounted runtime and was not rerun or sent to CI. No new customer labels, fault precision/recall, catch timing accuracy, coach approval, live LLM output or coaching effectiveness was measured. Human team inspection of AI-generated tests remains pending. No suspicious hidden AI-checker directive was observed; legitimate hidden form fields are not such directives.

### Scope mapping and next action

Activity2 stories/acceptance: #102report robustness, #103real-video detection evaluation, #104five-stroke/gap/parallel assessment. Activity3 has the observed seven new tests and five expected initial failures above, plus retained earlier test history; do not relabel implementation-era compatibility corrections as initial TDD. Proposal criteria1/3/4/8 gain usable reports/windows and reproducible real-footage inspection; empirical target-customer validation and coaching/LLM claims for remaining criteria are still unproven. Activity1 real customer KPIs are not replaced by tests.

Next action: create visibility/identity annotations for the longer public segment, separate real exits from association loss, then reproduce and fix a bounded tracking failure before claiming reliable five-stroke analysis on real crews. Keep #103 open. Finish guarded integration and one deduplicated authorized progress email; do not resume old automation.
