# StrokeSense development log and handoff

This file is the durable handoff for development of `KemalGC/CS4501_Startup`.
Read it at the start of each session, verify the current remote state, and update
it with actual results before finishing. Completed work and future plans must
remain clearly separated.

## Program and branch rules

- Program: October 27 through November 16, 2026, inclusive; 42 scheduled sessions.
- Start times: 09:00 and 21:00 **America/New_York** each day. Keep these local
  times through the daylight-saving transition.
- Work budget: 30 minutes per session (21 hours total planned). Record actual
  elapsed time when measured; runtime limits may shorten a session. Do not idle
  to fill the budget or claim an unmeasured duration.
- Integration branch: `dev/strokesense-2026-10-26`.
- Session branches: `dev/YYYY-MM-DD-am-short-topic` and
  `dev/YYYY-MM-DD-pm-short-topic`, created from the latest verified integration
  head. Retain each branch as a reviewable checkpoint.
- Initial setup branch: `dev/2026-10-26-setup-cache-accuracy`.
- **Never write, merge, force-push, delete, or change settings on `main` or the
  default branch.** Explicitly specify the destination branch in every write.
- After relevant checks pass, fast-forward only the integration branch to the
  tested session commit, using the previously read head as the expected SHA.
  Re-read and reconcile concurrent human changes; never overwrite them.
- Incomplete/failing changes stay on the topic branch. Record their branch and
  next action in a separate safe handoff commit if needed; do not carry broken
  code into the integration branch.
- Use the session key `YYYY-MM-DD-am` or `YYYY-MM-DD-pm` to avoid duplicate work
  on a retried scheduled run. Check both the log and remote branch heads.
- Send the authorized progress email after each session using the private
  scheduler instructions. Keep addresses, credentials, and task identifiers out
  of this public repository. Never email other people on the project's behalf.

## Product goal

Help rowers and coaches find recurring technique and crew-timing issues in
short, suitable side-on recordings, inspect the supporting evidence, and receive
grounded coaching explanations. Preserve the existing CLI while building a
small usable video registry and local upload/results interface.

The intended LLM workflow is:

1. Analysis produces versioned, immutable measurements and evidence references.
2. A configurable real LLM proposes structured coaching from those measurements
   and an explicitly reviewed cue library.
3. A separate deterministic validator checks references, quantitative claims,
   allowed cue/fault mappings, and evidence sufficiency.
4. Precise validation errors support a bounded correction loop of at most three
   attempts. Persistent failures remain withheld from published coaching.
5. The UI exposes the supported finding and its video evidence, with clear
   unavailable/withheld states.

The validator can establish only the properties it checks. Matching IDs and
numbers alone does not prove that every free-text statement is correct or that
the advice improves performance.

## Current state

Base inspected: `main` at `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.

### Implemented before this program

- Python CLI; YOLO11-pose through ONNX Runtime; person/seat tracking and
  camera-motion compensation; body kinematics and stroke segmentation.
- Ten heuristic fault rules with fixed coaching cues, per-seat catch timing,
  annotated video, HTML reports, JSON metrics, and cached detections.
- Synthetic tests for clean rowing, mirrored rowing with hidden ankles, and
  several injected technique faults.

### Not established at baseline

- No implemented LLM adapter, coaching release validator, or correction loop.
- No video database, annotation/import workflow, held-out real-video evaluation,
  upload application, or hosted deployment in the inspected tree.
- No measured real-video accuracy, coach-approved cue library, or customer
  validation evidence. The example report values are synthetic illustrations.
- The 0-100 technique score is a hand-designed heuristic, not a validated
  performance score.

### Setup-session progress

- Created the dated integration and setup branches from the inspected main head.
- Configured 42 recurring development sessions with progress emails.
- Reproduced the existing synthetic baseline: all four test functions pass.
- Added versioned cache identity for source path/stat metadata, clip settings,
  and the model's path/stat/SHA-256 digest. Legacy, mismatched, and malformed
  caches now recompute. Cache writes use atomic replacement.
- Added 13 passing cache regression tests. The four existing synthetic analysis
  test functions also pass after the change.

## Verification and assets

Run from the repository root unless stated otherwise:

```sh
python strokesense/tests/test_analysis.py
MPLCONFIGDIR=/tmp/strokesense-test-mpl python -m unittest discover -s strokesense/tests -p 'test_cache.py' -v
```

The baseline command exercises synthetic kinematics/fault analysis. It does not
exercise real video decoding, the downloaded pose model, tracking accuracy, or
coach agreement. The cache tests exercise real NPZ serialization and CLI cache
decisions with inference/model entry points mocked. When OpenCV is absent, they
use a documented import-only placeholder. Add new test commands here when
implemented and actually run.

The setup environment has NumPy, SciPy, and Matplotlib. OpenCV (`cv2`) and
ONNX Runtime are not installed there, so full-video inference is not verified.
The repository's declared dependencies remain in `strokesense/requirements.txt`.
Do not claim an end-to-end video run until dependencies, model availability,
input media, and outputs have actually been exercised.

No video binaries, verified real-video labels, or approved cue-review records
are committed in the inspected baseline. Do not invent those assets. Live LLM
credentials/provider configuration have not been verified. Offline fixtures
support tests but do not establish live model behavior.

## Quality gates

### Every change

- Choose one bounded useful increment. Continue an unfinished core dependency
  before optional polish; the calendar below is a backlog, not a completion claim.
- Read the affected implementation and relevant tests. Reproduce a concrete
  failure before claiming to fix it when feasible.
- Run meaningful targeted regression checks and the relevant existing tests.
  Record exact commands, results, and anything not exercised.
- Review the changed diff. Preserve CLI compatibility and human work.
- Update this file with current behavior, remaining limitations, and one
  precise next action. Preserve earlier entries.
- Do not copy a commit's own hash into itself; provide the resulting commit link
  in the email and record it in a subsequent entry when needed.

### Accuracy and data

- Version input identity, model, analysis settings, thresholds, and annotations.
- Use per-fault precision/recall, catch/finish timing error, and evidence coverage
  with explicit denominators. Distinguish no observed fault from insufficient
  reliable evidence.
- Keep synthetic regression results separate from empirical footage results.
- Group evaluation splits by recording session and athlete/crew as available;
  duplicate clips and adjacent frames must not leak across splits.
- Tune on development data. Preserve a held-out set for a meaningful final check.
- Keep a registry of stable clip IDs, hashes, source, permission/provenance
  status, private storage references, camera/FPS metadata, usable intervals,
  label version, recording group, and split.
- Public availability of footage does not establish permission to republish it.
  Keep private athlete footage and identifying metadata outside public Git.
  Unverified sources may be catalogued as unverified; never invent consent.
- Mark existing heuristic coaching cues as unreviewed until actual coach review
  is documented. Do not fabricate labels, customer interviews, or improvements.

### LLM and user interface

- Test malformed output, fabricated seat/stroke IDs, wrong quantities and
  denominators, incompatible/unreviewed cues, and weak evidence.
- Demonstrate both a rejected candidate that is corrected and a persistent
  failure that stays withheld. No failed candidate may leak into reports.
- Keep measurements and validation rules outside the generator's control.
- Clearly label offline fixtures and live-provider validation status.
- Show useful progress, failure, evidence, and insufficient-data states. Check
  that displayed values and timestamps agree with saved analysis records.

## Course criteria and evidence

These are the eight criteria described in
`README-startups/readme-startupSelected.md`. The official CS 4501 assignment
rubric has not been provided or independently verified. Track evidence against
the proposal and reconcile any official rubric when it becomes available.

| Proposal criterion | Required evidence / current gap |
| --- | --- |
| One specific problem | A suitable rowing clip yields inspectable technique/timing findings. |
| Accessible customers | Actual rower/coach feedback or a documented pilot protocol; no invented validation. |
| Familiar infrastructure | Reproducible setup and clear analysis/coaching/UI boundaries. |
| Reimagined workflow | Findings linked to measurements, strokes, footage, and useful correction cues. |
| Core generative model | A real configured LLM produces tailored grounded explanations; currently absent. |
| Independent validation | A separate release gate with negative tests; currently absent. |
| Automatic self-correction | Bounded retry success and persistent-failure demonstrations; currently absent. |
| Deployable MVP | One working local upload/process/results flow and documented deployment status; currently CLI only. |

## Priority-ordered 42-session backlog

Adapt these increments to observed failures and completed work. A 30-minute slot
may only complete part of an increment. Record that honestly and continue it.
Real-data and live-provider tasks depend on available permitted assets and
configuration; build and verify the unblocked parts when those are unavailable.

| Date (2026) | 09:00 session | 21:00 session |
| --- | --- | --- |
| Oct 27 | Verify integrated setup, dependency/model availability, and establish a repeatable quality command. | Close one concrete CLI/configuration mismatch and verify cache behavior with available video tooling. |
| Oct 28 | Define the video registry schema and permission/provenance fields. | Implement import/list operations and duplicate detection. |
| Oct 29 | Define seat/event/fault annotations and label provenance. | Implement annotation import and grouped evaluation splits. |
| Oct 30 | Build coverage, timing-error, and per-fault evaluation. | Record available baselines and explicit real-data gaps. |
| Oct 31 | Handle unreliable joints and excessive interpolation gaps. | Test abstention and occlusion regressions. |
| Nov 1 | Investigate one observed segmentation failure. | Correct it and compare against unchanged development inputs. |
| Nov 2 | Investigate one observed tracking/seat-assignment failure. | Apply a targeted correction and retain uncertainty where needed. |
| Nov 3 | Add versioned threshold configuration saved with results. | Evaluate changes on development labels, preserving held-out data. |
| Nov 4 | Define immutable evidence IDs, timestamps, values, and eligible denominators. | Add cue IDs, fault mappings, and explicit review status. |
| Nov 5 | Validate structure, references, values, and denominators. | Validate cue/evidence eligibility and test deliberate failures. |
| Nov 6 | Add the configurable real LLM adapter and offline adapter tests. | Implement bounded validation/retry and withheld output. |
| Nov 7 | Test corrected success and persistent rejection end to end. | Exercise the live provider if configured, or record the precise blocker. |
| Nov 8 | Add a small local analysis-job API. | Add bounded job execution and useful lifecycle/error states. |
| Nov 9 | Build video upload and analysis controls. | Add progress and navigation to results/failures. |
| Nov 10 | Add video-library browsing and reopen saved analyses. | Integrate evidence coverage and validated coaching into reports. |
| Nov 11 | Link findings to video timestamps and seat/stroke IDs. | Verify chart/report navigation and numerical consistency. |
| Nov 12 | Add constrained comparison with settings and coverage visible. | Address keyboard/mobile usability and confusing states. |
| Nov 13 | Add a lightweight annotation/review workflow. | Import newly permitted assets or improve evaluation coverage tooling. |
| Nov 14 | Profile and fix one measured performance bottleneck. | Exercise bad media, no-rower, model/provider, and interrupted-job failures. |
| Nov 15 | Package reproducible setup and an end-to-end demo. | Run final held-out evaluation where possible and assemble criteria evidence. |
| Nov 16 | Resolve the highest-priority remaining defect and verify the main workflow. | Finalize evidence, limitations, remaining backlog, and handoff. |

## Next action

Establish a repeatable test entry point and verify dependency/model availability without
claiming real-video accuracy from synthetic fixtures. Inspect the technical
README's tile options against the current CLI when selecting the next concrete
reproducibility issue. The cache fix is complete; do not repeat it without a
new observed failure.

Known follow-ups: the output directory still uses only the input video's stem,
so different same-named inputs can overwrite reports even though cache reuse
is now prevented. Video identity uses path, size, and modification time; changed
content with all three preserved is not detected. The planned video registry
can add content hashes. `--fresh` forces recomputation in the meantime.

## Session history

### 2026-10-26 setup — branch and accuracy foundation

- Session key: `2026-10-26-setup` (additional setup; not one of the 42 scheduled runs).
- Branch: `dev/2026-10-26-setup-cache-accuracy`.
- Base: `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc` from `main`.
- Initial verification: `python strokesense/tests/test_analysis.py` passes
  `test_clean_rower`, `test_facing_left_and_hidden_ankles`,
  `test_fault_detection`, and `test_angle_faults`.
- Finding: `analyse_video()` reused `results/<video.stem>/detections.npz`
  without checking changed input identity, clip range, sampling rate, tiles,
  or model. This can produce stale analysis and invalidate comparisons.
- Changed files: `strokesense/strokesense/cli.py`,
  `strokesense/strokesense/pose.py`, `strokesense/tests/test_cache.py`, and this
  `llm.md` handoff.
- Implemented source/request/model identity, first-download fingerprint refresh,
  legacy/mismatch/corruption recovery, archive validation, and atomic cache writes.
  A source/model change during extraction prevents publishing that cache.
- Independent review identified an uncaught `zlib.error` from a damaged compressed
  archive member. The handler and a real damaged-DEFLATE regression were added
  before publication.
- Final verification: the two commands in Verification and assets above pass
  all four existing analysis test functions and all 13 new cache tests. The new
  cases cover matching reuse, changed settings/source/model, same-stem inputs,
  legacy/version mismatch, fresh requests, malformed and damaged compressed
  archives, first download, source mutation, empty data, and interrupted writes.
- Review: no remaining blocking defect identified in the bounded cache change;
  source-stat identity and shared same-stem output directories remain explicit
  follow-ups. Full OpenCV/ONNX execution was not exercised.
- Empirical accuracy change: not measured; no labeled real-video evaluation.
- Communication: recurring development plus post-session email configured;
  the setup email will be sent after the commit is verified.

### Future session entry template

Copy this structure for each completed or blocked session; do not count the
template as a run.

- Session key and local start/end time; measured elapsed time or not measured.
- Topic branch; base commit; integrated or held for follow-up.
- Problem, implementation, and changed files.
- Exact test/evaluation commands and observed results.
- Real/synthetic evidence; before/after metrics only when actually measured.
- Blockers, unavailable assets/configuration, and remaining risks.
- Next concrete action and its acceptance criteria.
- Communication status (without personal addresses or private identifiers).
