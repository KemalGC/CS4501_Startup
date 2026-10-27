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

### 2026-10-27 AM quality and reproducibility

- Added `strokesense/quality.py`, a cross-platform single offline test command
  and a read-only `--doctor` preflight for Python/modules, cached ONNX model
  presence, and optional FFmpeg availability; no network/model inference.
- Added 5 new regression tests for the quality harness, including exit codes,
  missing prerequisites, and ensuring both suites execute after a failure.
- Added `.github/workflows/strokesense-quality.yml` on dev branches, using
  Python 3.11 and dependencies from `requirements.txt`.
- Corrected technical README cache name (`detections.npz`) and supported
  `--tiles auto|none` flags, and documented test/doctor commands.
- GitHub Actions first run on commit `d16f78c8` **passed** on 2026-10-27:
  4 legacy synthetic functions and 18 discovered unittest cases.
  Follow-up CLI argument validation on `50ab85f2` also **passed CI**:
  4 synthetic checks and 21 cases (13 cache, 5 quality, 3 CLI).
- No real-video inference or empirical measurement was performed. The
  checked execution container lacks ONNX Runtime and a cached model;
  the CI job installed runtime dependencies but did not download/infer a model.
- Added a strict `--tiles auto|none` argparse choice gate with tests;
  unrecognized options no longer silently disable native-resolution tiling.

### 2026-10-27 sprint 12:00 — collision-safe per-video results

- The October 27–29 coding sprint temporarily prioritizes the new course
  Activity 2 and Activity 3 workflow over the old 42-session calendar.
  This is an implementation sprint, not evidence that planned three-hour
  daily coding budgets were fully consumed. Keep the earlier schedule and
  session history for continuity; do not automatically resume the old plan.
- Issue-based TDD: GitHub issue #12 records the alpha user story and acceptance
  criteria. Its tests were committed first; synthetic placeholder clips and
  mocked inference isolate path/cache behavior. The team's review of
  AI-assisted tests remains pending.
- Production: `_result_directory()` chooses a stable path-scoped output
  directory using a 20-character SHA-256 prefix of the canonical source path,
  together with the video stem. Separate same-stem inputs now receive
  independent cache, reports, snapshots and annotated media directories.
  The same canonical source path retains its folder across reruns.
- Compatibility: legacy `results/<stem>/` directories are intentionally
  not overwritten, read or automatically migrated; users can still open their
  old reports. Existing CLI flags remain unchanged.
- Offline red-to-green: GitHub Actions red checkpoint
  `079bb78a7d68e99ae73c30b1d193a09eb4e9ced1` produced 4 passing
  legacy synthetic checks, 21 previously passing unittests, plus 1 passing
  and 5 intentionally failing new tests (1 assertion failure, 4 missing
  helper errors). After implementation
  `f7c225646a31ec655f4292f8bc6f68a250734a87`, the command
  `python strokesense/quality.py` passed 4 legacy synthetic checks
  and all 27 discovered unittests, including 6/6 new output path cases.
  The read-only `python strokesense/quality.py --doctor` also exited
  successfully in CI. The green run is GitHub Actions #40537739246.
- Changed implementation/check files: `strokesense/strokesense/cli.py`,
  `strokesense/tests/test_output_paths.py`,
  `strokesense/tests/test_cache.py`, `strokesense/README.md`,
  and this log. No private videos, athlete records, credentials or models
  were added.
- Scope/evidence: mocked no-rower analysis exercises real NPZ cache writes
  and path isolation but not complete real-video analysis. There are no
  verified permissioned clips, coach labels, approved cue library or live
  LLM provider in this checkpoint. Empirical rowing accuracy improvement:
  not measured.

### 2026-10-27 sprint 12:16 — private content-addressed clip registry

- Issue #13: user story for a local clip library with stable SHA-256 identity,
  conservative permission/provenance, recording-group split isolation,
  and private-by-default source references.
- Added `strokesense/strokesense/registry.py`: standard-library SQLite,
  streamed content hashing, `import` and `list` commands, metadata for
  camera/FPS/split/consent status, original local source reference, and
  duplicate detection with conflicting metadata rejection. Default SQLite
  path: `strokesense/results/video_registry.sqlite3` (Git ignored).
  Import does not copy, upload, decode or analyze footage.
- Added ten synthetic offline regression tests in
  `strokesense/tests/test_registry.py`; first commit
  `b5a733e963f89620d31ac12ec2e748d90222a039` intentionally failed
  CI with 10 missing-module errors, while 27 existing unittests and four
  legacy synthetic checks passed. This is observed red-before-code evidence,
  not an environment or model import failure.
- Implementation commit `1d4e6d99c17526c7410d64b18822d540f19a514e`
  passed GitHub Actions #40540751599:
  `python strokesense/quality.py` ran 4/4 legacy synthetic checks and
  **37/37** unit tests (10 new registry tests). Read-only
  `python strokesense/quality.py --doctor` exited successfully with
  dependencies available; pose model remained uncached. No actual ONNX
  inference, real-video evaluation or model-accuracy estimate.
- `strokesense/.gitignore` now excludes SQLite and journal files; README
  explains CLI usage and migration. The database stores a private local
  source path and operator-entered permission/provenance, which do not
  establish legal authorization. Human review of AI-assisted tests, coach
  labels, live LLM adapter and end-to-end UI remain pending.

## Verification and assets

Primary command (all offline tests, independent of the working directory):

```sh
python strokesense/quality.py
python strokesense/quality.py --doctor
```

The first command executes both legacy synthetic tests and all discovered
unittests. The second reports local runtime/module/model availability without
downloading assets or running inference; it returns nonzero if a required
runtime module is missing. The dev-only GitHub Actions workflow repeats these
checks. On its initial commit, the workflow passed 4 legacy functions and 18
unittest cases (13 cache, 5 quality), without a real-video validation run.

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

The code-level Alpha now includes collision-safe outputs, a private
content-addressed clip registry, versioned evidence, fail-closed independent
coaching validation, a bounded three-attempt correction loop, and an explicit
HTTPS LLM chat adapter with sanitized, minimal evidence projection.
The new adapter passes mocked offline CI, **not** live provider verification.
No approved real cue catalogue or independently eligible real-video evidence
exists yet, so the adapter appropriately refuses live generation without
those prerequisites.

Next highest-priority issue: implement a minimal **local** analysis job and
results interface with bounded uploads, clear queued/running/failed states,
and safely escaped navigation to saved metrics/evidence. Prefer established
maintainable components, robust path isolation and security controls. Write
acceptance tests before implementation. Preserve existing CLI and release
validator. Do not expose unapproved coaching or private video footage.

Follow-ups: registry import is a private *index*, not a permission enforcement
gate for the analysis CLI. It neither validates video format nor prevents all
athlete/crew/adjacent-frame split leakage. The existing cache/output folder is
path-stable, so replacing media at the same path may overwrite earlier reports.
Content-identical video files in different directories have one registry ID;
the separate analysis output folders are still path-based.

Remaining caveats: a clip replaced at the *same canonical path* shares its
output directory, so re-analysis may replace prior reports there. Pose cache
identity still uses source path/size/mtime, not source-content SHA-256; a
same-size, same-mtime replacement is not detected. The video registry should
add strong content identity. The deterministic folder suffix is a path hash,
not proof of consent or a complete confidentiality boundary.

### Alpha issue-to-test traceability (sprint)

| Story/acceptance | Issue | Tests and commits | Status |
| --- | --- | --- | --- |
| Separate results for independent same-named clips, preserve legacy files, reuse valid same-source pose cache | #12 | `test_output_paths.py` (6 synthetic/mock tests), existing `test_cache.py`; red `079bb78a`, green `f7c22564` | CI green; student team inspection pending |
| Privacy-first local registry with content SHA-256, duplicate consent conflict handling and session-group split guard | #13 | `test_registry.py` (10 synthetic cases), red `b5a733e9`, green `1d4e6d99` | 4 synthetic + 37 unittests green in Actions; human test review pending |
| v1 stroke/fault references, observed denominators, and abstention | #14 | `test_evidence.py` (11 synthetic cases); red `33cee429`, green `7adcfe3b` | Offline CI green; coaching withheld pending eligibility/review; human test inspection pending |
| Independent fail-closed candidate validation, strict IDs/counts and cue checks | #15 | `test_validation.py` (9 synthetic cases); red `26154fe9`, green `0cbf6d5d` | 57 unittests and 4 synthetic checks green; no live cue approval |
| Bounded independent correction/retry and fail-closed withholding | #16 | `test_correction.py` (7 synthetic tests), red `5c15e9b6`, green `8bf3d9e3` | 64 unittests and 4 synthetic checks green; no live provider |
| Live provider adapter and results UI | Issues/tests required before each increment | No live provider or empirical validation claimed | Unfinished; create narrow issues first |

The eight selected-proposal criteria remain the project goals; this increment
strengthens reproducible infrastructure and Alpha readiness, not the core LLM
or live deployment criteria. The actual customer-validation Activity 1 remains
unverified and requires human outreach/evidence.

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

### 2026-10-27 AM — offline quality and runtime preflight

- Session key: `2026-10-27-am`; America/New_York start 09:03:53, verified
  checkpoint 09:14:32 (10 minutes 39 seconds measured to that checkpoint);
  no claim of a full 30-minute runtime. Further integration/email steps follow.
- Topic branch: `dev/2026-10-27-am-quality-preflight`, branched from
  integration commit `02bf9b9d944d71e0cb87ab0ccc0964307cafbe85`.
- Files: `strokesense/quality.py`, `strokesense/tests/test_quality.py`,
  `.github/workflows/strokesense-quality.yml`, `strokesense/README.md`,
  and this log. Code commit: `d16f78c8184722dcc155fdd07dcc1f7e7779f1dc`.
- Implemented a one-command offline quality suite and optional read-only
  environment diagnostics, plus dev-branch CI and accurate CLI/cache docs.
- Local verification: `python -m unittest discover -s
  /mnt/data/strokesense_dev_am/strokesense/tests -p test_quality.py -v`
  passed 5/5 harness tests; `python -m py_compile` and `ast.parse` passed
  for new Python modules; a controlled fixture test of
  `python <fixture>/quality.py` passed when both suites succeeded and
  returned exit 1 when a discovered unittest intentionally failed.
- GitHub Actions run on code commit:
  `python strokesense/quality.py` passed the 4 legacy synthetic checks
  and 18 unittests (13 existing cache + 5 new quality cases). The
  diagnostic reported Python 3.11.17, runtime modules installed and model
  file not cached; run conclusion `success`.
- Current execution environment's `--doctor` found ONNX Runtime missing,
  cached model missing, optional FFmpeg present, and other analysis modules
  available. This does not contradict the clean CI environment.
- Follow-up fix in the same AM session: the CLI silently accepted unknown
  `--tiles` strings and treated them as `none`, which could reduce distant
  rower detection accuracy without warning. Added `choices=('auto', 'none')`
  in `strokesense/strokesense/cli.py` plus 3 parameter/typo regressions in
  `strokesense/tests/test_cli.py`; commit `50ab85f2e715f67ce49d5aba42242c157897c6db`.
- GitHub Actions CI rerun on this CLI commit passed 4 legacy synthetic
  test functions plus **21 unittest cases** (13 cache, 5 quality, 3 CLI);
  Python 3.11 runtime dependencies were available, model remained uncached.
- Final engineering checkpoint: America/New_York 09:18:31, measured
  14 minutes 38 seconds from start (integration/email occurred afterward);
  no idle time or unsupported 30-minute duration claim.
- Empirical performance improvement: **not measured**. The quality changes
  catch regressions; they do not claim to improve rowing recognition accuracy.
- Blocked/untested: no consented real rowing clip, coach-labeled benchmark,
  actual ONNX model inference or live LLM provider configured in this run.
- Next acceptance: distinct same-stem inputs must not overwrite each
  other's reports/caches, and a repeated identical input should reuse the
  intended result location; relevant offline regression tests must pass.
- Communication: post-session email to be verified and sent after
  integration; no private recipient information stored here.

### 2026-10-27 12:00 sprint — isolated output directories

- Session key: `2026-10-27-1200-sprint`; scheduled 12:00 America/New_York.
  Local instrumented start 11:58:21 EDT and engineering checkpoint
  12:08:24 EDT, **10 minutes 3 seconds measured** to that checkpoint;
  integration and communication followed. The 30-minute budget was not
  fully used or claimed.
- Topic branch `dev/2026-10-27-1200-output-isolation`, based on verified
  integration head `572194dc03b4e98add73e2ddb2e3cea99990c678`.
  Main head before changes: `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.
  Integration is allowed only after the final logged commit is green.
- User story: as a coach analyzing several practice recordings, keep
  each clip's evidence and reports independent even if clip names match.
  Issue #12; acceptance includes stable canonical-source identity,
  legacy preservation, no private path leakage, and existing cache behavior.
- Test-first: added `strokesense/tests/test_output_paths.py` (6 cases)
  in the test-only red commit `079bb78a7d68e99ae73c30b1d193a09eb4e9ced1`.
  Workflow #40537150854 confirmed the expected missing behavior:
  4 errors from absent `_result_directory`, one overwritten old cache
  assertion, and one passing same-source reuse check; 21 previous
  unittest cases and 4 legacy synthetic checks remained green.
- Implemented helper in `strokesense/strokesense/cli.py`,
  switched output creation to deterministic per-source paths, aligned
  the existing cache test fixture, and documented behavior/migration
  in `strokesense/README.md`. Code commit:
  `f7c225646a31ec655f4292f8bc6f68a250734a87`.
- Green verification on code commit (GitHub Actions #40537739246):
  `python strokesense/quality.py` => 4/4 synthetic checks plus
  27/27 unittests, including all six new output-path cases;
  `python strokesense/quality.py --doctor` => success, Python 3.11.17
  and modules installed, ONNX model file not cached. No video decoding,
  actual model inference, annotated video/report production from real
  inputs, or real accuracy benchmark was performed.
- Diff reviewed: only CLI implementation, cache fixture, technical
  README, new tests, and this session log changed. No main changes,
  PRs, private source clips or hosted services. Team validation of
  the AI-assisted tests is **pending**.
- Next acceptance: a clip registry issue with failing tests for SHA-256,
  permission/provenance, session grouping and duplicate protection;
  implement a small safe registry and retain green offline regression.
- Communication: send one progress email after final CI/integration,
  avoiding duplicate subjects; no recipient metadata in repository logs.

### 2026-10-27 12:16 sprint — local private clip library

- Session key: `2026-10-27-1216-sprint`; immediate on-demand scheduled
  occurrence at 12:16:24 EDT. Monotonic start recorded at **12:16:53 EDT**.
  Engineering checkpoint **12:27:25 EDT**, measured **10 minutes 32 seconds**
  to that checkpoint; verification/integration/email follow. Do not claim a
  full 30-minute session or use scheduling budget as elapsed work.
- Branch: `dev/2026-10-27-1216-video-registry`, based on verified integration
  head `0f4ee92e6b2d2b6a8cdfb9199b4ba39c69fce068`. The prior noon
  increment was already complete and was not repeated; `main` before
  changes: `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.
- Story and acceptance criteria: GitHub issue #13; local private clip
  import/list, streamed SHA-256 identity, immutable duplicate metadata,
  unverified-by-default permission and explicit consent provenance for
  `granted`, grouped development/heldout split collision checks,
  path-private results and rejection of bad files/settings.
- **Red first:** `strokesense/tests/test_registry.py` (10 unit tests) committed
  as `b5a733e963f89620d31ac12ec2e748d90222a039` *before* production
  registry code. `python strokesense/quality.py` in Actions #40539995106:
  four synthetic checks passed; 27 old unittests passed; ten new tests errored
  because the registry module was absent (expected missing behavior, not a
  third-party dependency or flaky runtime failure).
- **Green after implementation:** code commit
  `1d4e6d99c17526c7410d64b18822d540f19a514e`;
  `python strokesense/quality.py` in Actions #40540751599 exited
  successfully: four synthetic checks + all 37 unittests, including ten new
  registry cases. `python strokesense/quality.py --doctor` exited zero:
  Python 3.11.17 and required modules present; ONNX model file not cached,
  no video inference or real-world validation.
- Files: new `strokesense/strokesense/registry.py` and
  `strokesense/tests/test_registry.py`; updated
  `strokesense/.gitignore`, `strokesense/README.md`, this `llm.md`.
  Reviewed diff against integration base: these four product/test files plus
  this log only. No real video, identifying metadata, secret or credential
  added to GitHub.
- Limitations: operator-entered permissions are not verified and not enforced
  by existing analysis CLI; local SQLite references source paths and is not
  encrypted; source changes after registration or moves require reinspection.
  Grouping is not a complete athlete-level split isolation mechanism.
  No coach-reviewed cues, permitted footage, LLM credentials or real labels
  verified. Student-team inspection of AI-derived tests is **pending**.
- Next action: create a narrow issue and failing tests for immutable evidence
  IDs and explicit evidence sufficiency/abstention; then implement and run
  full offline suite. Preserve earlier logs and do not touch `main`.
- Communication: one sprint email after final CI/integration and duplicate
  check; until confirmed, status is pending.

### 2026-10-27 13:00 sprint — deterministic evidence snapshots

- Session key: `2026-10-27-1300-sprint`. Scheduled 13:00 ET.
  Instrumented local start **12:59:31 EDT**, checkpoint **13:09:46 EDT**;
  **10m15s** measured to checkpoint; integration/email followed. Not a
  claim of 30 minutes.
- Branch `dev/2026-10-27-1300-evidence-records`; integration base
  `8d79bd29723a73fde8568d98cc1773d74acd71e7`. Main started at
  `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.
- Issue #14 user story: versioned, analysis-scoped seat/stroke/fault
  IDs; valid source timeline; exact observed numerator and total analyzed
  denominator; insufficient-sample status and unknown eligible denominator;
  all coaching withheld until evidence/coach review. Digest is not signed.
- Test-first record: test-only `05ac7f65` had an unmatched parenthesis,
  causing a syntax error in Actions #40546983871 (not a valid red behavior
  test). Corrected test-only `33cee429492ff2c9cdb1276f4e3bf4ee44644853`
  failed for *missing evidence module* as expected in Actions
  #40547207380: existing 4 synthetic and 37 unittests passed, 11 new
  test functions raised missing-module errors (21 reports with subtests).
- Implemented `strokesense/strokesense/evidence.py`, 11 synthetic tests
  in `strokesense/tests/test_evidence.py`, backward-compatible optional
  evidence field in `strokesense/strokesense/report.py`, automatic
  `strokesense/strokesense/cli.py` integration, and README contract.
- Green GitHub Actions #40547758797: `python strokesense/quality.py`
  passed **4/4 legacy synthetic checks and 48/48 unittests**. The
  read-only `--doctor` check succeeded, runtime modules installed;
  pose ONNX file absent, no real inference or accuracy benchmark.
- Diff reviewed: evidence, tests, CLI, report, README and this log.
  No private clips, secrets, provider spending or main writes.
  Student review of AI-derived tests remains pending.
- Limitations: snapshot SHA-256 detects unintentional alterations but
  not a malicious editor recomputing the digest; per-fault eligibility and
  real-video reliability unknown, all cues unreviewed, no LLM output released.
  Source cache identity still path/stat-based.
- Next: issue-based negative tests for independent coaching release
  validation, then fail-closed implementation. Communication pending.

### 2026-10-27 13:00 sprint (continued) — independent release validator

- Issue #15: as a coach, prevent unsupported LLM coaching from being
  released. Branch `dev/2026-10-27-1300-coaching-validator` based
  on verified integration head `6b3736820ef12309f9c46e9991dc1c99afc247c4`
  from the same 13:00 session (issue #14 was CI-green and integrated).
- Test-only commit `26154fe959cb94757ee14df5ac3b97e370dc0908`
  introduced nine offline fixture/negative cases. GitHub Actions
  #40548518387 ran against that unchanged preimplementation commit and
  produced the expected missing-module ImportErrors (9 errors) while
  the previous 48 unittests and four synthetic functions passed.
  The workflow was queued for several minutes and **reported the red
  failure after implementation was already committed**; therefore
  strict observe-red-*before*-implementation chronology was not met
  for this second increment, although tests were committed first.
- Code commit `0cbf6d5dfdf4e4b80e6394097524a5ba31433bee`:
  added `strokesense/strokesense/validation.py` with strict schema,
  independent measured ID/count/denominator checks, verified snapshot
  digest, approved cue/fault mapping, reviewed eligibility and fail-closed
  withholding. Rejected candidates never appear in response payload;
  passing candidates warn `free_text_unverified`.
- Green GitHub Actions #40549113205:
  `python strokesense/quality.py` passed **4/4 synthetic analysis checks
  and 57/57 unittests** including all nine validator cases. `--doctor`
  succeeded but no ONNX model file or live inference was available.
  README updated to distinguish entirely fictional test approvals from
  actual coach review. No real approved cues exist in the repository.
- Measured checkpoint for the overall session **13:18:24 EDT**,
  **18m53s elapsed** since 12:59:31 EDT start. Final integration/email
  follow. This does not imply 30 minutes of work.
- Human review of AI-assisted tests remains pending; no actual real-video
  validation, live model access, deployment, or user validation.
- Next: bounded three-attempt correction loop, negative retry tests and
  separately configurable provider. Communication pending.

### 2026-10-27 13:00 sprint (continued) — bounded correction

- Issue #16: generator-agnostic self-correction loop with three total
  attempts maximum, independent validator on every candidate, fail-closed
  withholding, and no candidate text leakage from failures. Branch
  `dev/2026-10-27-1300-bounded-correction` from prior verified
  integration head `4be48fcea77588d72e81e6749d0f814ee8a53887`.
- **Test-first observed red**: test-only commit
  `5c15e9b63c49a981354dcb224a2de1aa91cc653c`;
  GitHub Actions #40549738484 passed 4 legacy synthetic functions and
  57 existing unittests; seven new tests errored because the correction
  module was missing. This was confirmed before implementation.
- Implemented `strokesense/strokesense/correction.py` and synthetic
  `strokesense/tests/test_correction.py` cases for rejected-then-corrected
  success, exact attempt caps, persistent rejection, provider error
  withholding and snapshot/catalogue mutation isolation. README records
  limits. Code commit `8bf3d9e327a926068bc08ddf8a6fc438315740f0`.
- Green Actions #40549888862: `python strokesense/quality.py` passed
  **4/4 legacy synthetic checks and all 64 unittests**, including seven
  new correction cases. `--doctor` succeeded but the ONNX file was not
  cached. No real LLM, coach-reviewed cues, or real footage was used.
- Trusted inputs are copied, a generator receives only structured error
  codes from prior rejected attempts, invalid output is never returned,
  and provider exceptions are withheld without emitting error text.
  This does not ensure free-text truth or provider reliability.
- Next concrete task: a separately configured, network-safe provider
  adapter with mock-based tests for API errors and structured responses,
  then local results/UI integration. Student review pending; main
  remains excluded from all write operations.
- Communication: final progress email after CI/integration.


### 2026-10-27 13:00 sprint (continued) — configured HTTPS LLM adapter

- Session key: `2026-10-27-1300-sprint` (continuation following issues
  #14–#16). This coding checkpoint began at **13:27:07 EDT**, after inspecting
  the already-green integrations. Monotonic timer used; **8m51s measured**
  to the **13:35:58 EDT** documentation checkpoint. Remaining verification,
  integration and email steps occur afterward; this is not a 30m claim.
- Issue #17: as a coach, request generated structured explanations using
  preverified evidence and reviewed cue identifiers without bypassing the
  independent release gate. Topic branch:
  `dev/2026-10-27-1300-provider-adapter`, from integration SHA
  `edd43d7db51658d236dd5b5bc21761bc51daf723`. Original `main` head
  `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.
- Test-first commit `965e01eaf2b8397515719f6bea7f5025a13e8e6c`
  specifies network-safe initialization, secure URL/config behavior,
  allowlisted privacy-safe request projection, response shape/size,
  sanitization, correction-loop use, persistent withholding. Human review
  tightened the test fixture checksum before implementation in test commit
  `b3207b8bfd56268b625c3311b98aca8611efe88b`.
  GitHub Actions red run #40551302223 failed with the expected missing
  `strokesense.provider` module, while four prior synthetic checks passed;
  there was no live network traffic.
- Implementation commit `d4b44669b37a6f1f022ecc93553e984940c21403`
  added `strokesense/strokesense/provider.py`: explicit HTTPS Chat
  Completions adapter, env-configured model/key/endpoint, minimal whitelisted
  eligible evidence/approved cue payload, JSON parsing, timeout/size limit,
  sanitized provider failures, and direct compatibility with independent
  correction/validation. Initial green Actions #40551592658 passed four
  synthetic functions + 74 unittests, including ten provider cases.
- Security review added a **separate failing redirect test** first:
  `652a6932703952b4e6e1a850928681c797319d00`,
  GitHub Actions #40551829700 confirmed missing redirect-rejection handler
  before code changes. Fix commit `02364e53ef74ef690e880960e10f4d0705bd9c3d`
  uses a dedicated no-redirect HTTPS opener, avoiding global mutation and
  preventing forwarding credentials to redirected destinations.
- Final green Actions #40551950563: `python strokesense/quality.py`
  passed **4/4 existing synthetic analysis checks plus all 75 unittests**,
  including 11 provider tests; `python strokesense/quality.py --doctor`
  succeeded with installed runtime deps but no cached ONNX model. All
  provider responses and approvals were fictional test doubles; no real
  provider was contacted and no empirical accuracy was measured.
- Files: new provider module + tests; updated README and durable log.
  Team inspection of AI-assisted tests is still pending. Limitations:
  no verified cue approvals, no consented external-provider transmission,
  no live inference, no real labeled accuracy data, and no full UI.
  Privacy decision still required before sending even allowlisted
  biomechanics data to third parties. Old source path/stat cache limitation
  remains. Avoid any actual spending without consent.
- Next: issue-based TDD for local job/result upload interface and strict
  release-only coaching display. Progress email after verification/integration.

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
