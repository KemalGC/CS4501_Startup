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

- 2026-10-27 15:00 continued: local job preflight also requires finite,
  positive reported frame count and rejects nominal clips longer than
  120 seconds before decoding/inference. Frame count/FPS metadata can lie
  or be absent; this is not a hard execution timeout.


- 2026-10-27 15:00 continued: default local worker now opens and decodes one
  initial frame before running pose; nondecodable or invalid-size/FPS source
  returns a sanitized `invalid_media` result without starting inference.
  A tiny generated MJPG AVI smoke test passed actual OpenCV decoding in CI.

- 2026-10-27 15:00 continued: local browser uploads now reject clearly
  mislabelled/truncated ISO BMFF, RIFF/AVI and EBML container signatures
  before private storage or SQLite registration; this is NOT decoding,
  malware scanning, consent verification, or empirical model evaluation.


- 2026-10-27 15:00: successful local jobs now require source-byte stability
  across analysis, with an explicit failed status if footage changes mid-run.

- 2026-10-27 15:00 continued: CLI now rejects invalid/nonfinite start,
  duration and FPS settings before any analysis; 128 unittests + 4 synthetic
  checks passed with the added regression coverage.\n
- 2026-10-27 15:00 continued: cache identity now includes streamed SHA-256
  for source footage and model; same-size/same-mtime replacement forces
  inference rather than stale pose reuse. Full video decode still untested.

- 2026-10-27 15:00: evidence navigation now rejects checksum-valid but structurally
  inconsistent v1 metrics and false review states; generated coaching remains withheld.

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

The Alpha's existing offline-regressed capabilities now include collision-safe
video outputs, SHA-256 private clip index with grouped splits, a three-attempt
LLM correction/withholding gate with independent validator, an opt-in
configurable HTTPS provider adapter, bounded local jobs, and a loopback-only
browser upload/job/report/evidence flow. A standalone **synthetic-only** demo
is available with `python -m strokesense.demo`. An observed 16:00 API
increment returns sanitized Problem Details JSON for `/api/` errors.

The current 16:00 sprint also adds a local operator permission-withdrawal
operation. Already queued/running workers recheck the grant and suppress
results on withdrawal. This is a local claim, not verified consent. Past
published outputs remain available and are not deleted or instantly recalled.
The independent LLM adapter has *not* run with live provider credentials;
actual rowing pose accuracy and customer validation are unmeasured.

**Next focused engineering action:** implement a versioned, non-destructive
local permission-withdrawal audit (schema migration and first-revocation
timestamp) with test-first cases. #31 HTTP Problem Details/error coverage now
includes real 409/413/503 routes, 403/404, and a test-only serializer probe
for other codes. Do not delete existing files or imply independent consent.
Preserve loopback-only, CSRF, Host and Origin gates.

Remaining research/validation blockers: genuinely permitted rowing media,
downloaded ONNX pose model for empirical inference, coach-reviewed cue
catalogue, live provider credentials plus explicit data-transfer
authorization, independent customer validation and real labeled evaluation.
The local server is not authenticated for public deployment and must stay
bound to loopback. Full-content SHA-256 pose cache identity now prevents
same-size/same-mtime stale reuse, but each rerun incurs O(input size) reads
and deliberate concurrent file mutation remains a race to analyze.

### Alpha issue-to-test traceability (sprint)

| Story and acceptance | Issue | Test-first/verification evidence | State |
| --- | --- | --- | --- |
| Same-stem input result/caches isolated; legacy outputs preserved | #12 | `test_output_paths.py`; red `079bb78a` / green `f7c22564` | Integrated; team review pending |
| Private clip registry and grouped split integrity | #13 | `test_registry.py`; red `b5a733e9` / green `1d4e6d99` | Integrated; review pending |
| Versioned evidence + independent validation + three-attempt correction | #14–#16 | `test_evidence.py`, `test_validation.py`, `test_correction.py`; red/green CI in session history | Offline tests green, no live approved cues |
| Configurable provider adapter, local jobs, browser and evidence | #17–#28 | Issue-based test/CI history below | Offline tests, no live inference |
| One-step upload, synthetic browser demo and machine-readable API errors | #29–#31 | `test_upload_analyze.py`, `test_demo.py`, `test_api_errors.py`; red Actions 40583792311 and 40584165377; green Actions 40584304598; route coverage Actions 40585010706 | #31 acceptance tested; team inspection pending, no real footage |
| Withdraw local claim, deny queued/running result publication | #32 | `test_revocation.py` (5 synthetic cases): red Actions 40579650482; green Actions 40580034840 | Integrated; team inspection pending |
| Withhold revoked prior results and recent history in browser/API | #33 | `test_revoked_web.py` (3 synthetic HTTP cases): red Actions 40580738910; green Actions 40580961440 | Integrated at `842f4663`, team inspection pending |
| CSRF/Host/Origin-protected withdrawal form in loopback UI | #34 | `test_web_revoke.py` (3 HTTP fixture cases): red Actions 40581464304; green Actions 40581629204 | Green topic, integration pending; human review pending |

These tests are **synthetic or mocked**. The eight selected-proposal
criteria map to Alpha implementation goals, not a verified official grade.
Activity 2 issue/story/criteria records are present for chosen stories;
Activity 3 test-first evidence is in CI and commits, while actual human
review remains pending. Activity 1 requires real customer validation,
not offline unit tests.

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

### 2026-10-27 13:00 sprint (continued) — bounded local analysis jobs

- Issue #18: queue only an explicitly registry-permitted clip, recheck SHA-256
  before analysis, persist queued/running/succeeded/failed jobs without
  exposing private paths, isolate every job's report under a random run ID,
  and sanitize errors. Explicit permission is a *claim*, not independently
  verified consent. Topic branch `dev/2026-10-27-1300-analysis-jobs`,
  based on CI-green integration `6ab7df8716d92bc0a42ff987de34d8452e7fe168`.
- **Test first:** `strokesense/tests/test_jobs.py` (8 synthetic/mock cases)
  at `25c8b6458d8ade0271d23d8ceceb087df678c026`. GitHub Actions
  #40552765707 confirmed 8 expected missing-module errors; 75 existing
  unittests and four legacy synthetic checks still passed.
- **Green:** implementation commit `8303ae23d18c9212a15efcf53433ddd729087481`
  added `strokesense/strokesense/jobs.py`, using bounded local executor,
  SQLite durable public status, registry permission/provenance claim,
  source hash check, per-job output isolation, safe report-relative paths
  and sanitized errors. Actions #40552986633 passed 4 legacy synthetic
  checks plus 83 unittests (8 new job tests).
- **Quality review:** a new filesystem failure test-first commit
  `c4c5547a3c3bbc0634684f92c6d591dfbe5021e9` produced the
  expected unsanitized `OSError` in Actions #40553198705 before the fix.
  Commit `001a596fe25dab8c85c899d258ea2c0de6f48408` catches
  unwritable output directories, marks the job `output_unavailable`,
  and closes the initialization SQLite connection. GitHub Actions
  #40553340755 passed **4 synthetic functions and 84 unittests**,
  including all nine job lifecycle and failure tests; read-only
  `--doctor` succeeded. The ONNX model was not cached in CI.
- Documentation added to `strokesense/README.md`. No real media, model
  inference, LLM calls, coach review, customer validation or empirical
  accuracy data. Team test inspection remains pending. Job permissions
  rely on an operator claim; the media can mutate between hash check
  and decoding. Local worker is not a production distributed queue.
- Overall scheduled 13:00 occurrence already had issue #14–#17 work
  logged above. This continuation was instrumented at **13:27:07 EDT**;
  the **13:44:44 EDT** checkpoint was **17m37s measured** from that
  start. Additional docs, publication and email steps follow. Neither
  this continuation nor the earlier work should be recorded as a full
  30-minute session without the corresponding elapsed evidence.
- Next: issue-based TDD for a loopback-only, bounded upload/results UI
  with safe artifact navigation and independent coaching withholding.
- Communication: report completion only after integration and email.


### 2026-10-27 14:00 sprint — local clip-to-report browser and durable history

- Session key `2026-10-27-1400-sprint`; scheduled 14:00 EDT, tools
  instrumented at 13:51:26 EDT; engineering checkpoint 14:05:06 EDT,
  **13m40s elapsed** to that checkpoint. This is not 30 minutes.
- Base: verified integration `f60989fa66ea9cf4dfdebe2a7663ac31dd091559`
  after the earlier CI-green local jobs service. Original main remains
  `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`.
- Issue #19: as a coach select permission-claimed registered clips, queue
  a job, inspect status and safely reopen reports in a local browser.
  Topic `dev/2026-10-27-1400-local-web`. Test-only
  `28434e2dea9ea1e63108e40e8bf9a4478f1172d4` preceded implementation
  and GitHub Actions #40555229072 **failed as expected**: ten offline
  UI tests reported missing `strokesense.web`, while 84 existing unittest
  cases and four synthetic checks passed. Code commit
  `0bdb9155ef01e162ebbd59af17325c3eeaf6046b`: standard-library
  127.0.0.1-only browser pages, CSRF/Host/Origin enforcement,
  bounded form input, public job JSON, scoped/sandboxed report serving,
  no raw private paths. Green Actions #40555569413: 94 unittests
  plus four synthetic analysis checks passed. Docs commit
  `82db151e1bd4b83d6003f9b87e89af9ec1ff7233` passed Actions
  #40555754839. Integration fast-forwarded; main untouched.
- Issue #20: as a coach browse newest finished/pending/failed jobs
  without memorizing IDs and reopen reports after restart.
  Topic `dev/2026-10-27-1400-job-library`, from integration
  `82db151e1bd4b83d6003f9b87e89af9ec1ff7233`.
  Test-only `b7b5f1f3472f723662f57f436c67f8c0dd9a2a0a` was
  observed red in Actions #40556141769 (seven new tests, missing
  `list_recent` and `/api/jobs`, 94 existing unittests passed).
  Added bounded parameterized newest-first SQLite public job history,
  homepage links, safe JSON endpoint and restart reopen tests in
  `strokesense/strokesense/jobs.py`,
  `strokesense/strokesense/web.py`,
  `strokesense/tests/test_job_history.py`. Implementation commit
  `fbc1d573c9538560ccf7e58d7556dfef6e9bea0f` passed
  GitHub Actions #40556359759: **all 101 unittests and four legacy
  synthetic functions passed**; read-only doctor found runtime
  modules available but no downloaded ONNX model. README revised.
- No empirical accuracy, actual video decoding/inference, verified
  consent, human-coach review, live LLM call, externally verified
  usability/customer data or public hosting occurred. These are
  synthetic/mock offline tests. The browser is **not authenticated**,
  for local loopback use only; source cache still has path/stat identity.
  Student-team inspection of AI-assisted tests remains pending.
- Next: scoped issue-based test-driven **private browser upload** with
  limited bytes/types and explicit permission/provenance claim; do not
  auto-release unreviewed LLM coaching. Preserve all older history.
- Communication: final session email after completed integration and
  duplicate check; pending until confirmed.

### 2026-10-27 14:00 sprint (continued) — bounded private browser ingest

- Issue #21: as a coach, upload a single local video from the browser
  with explicit permission/provenance and no exposure of original
  path; safely hash/index the clip for later analysis. Branch
  `dev/2026-10-27-1400-private-upload` from verified integration
  `28c51a66ae2603b330faae8029f8bdc8361c4d0e`. Student team
  inspection of AI-authored tests remains pending.
- **Test first** at `11af6ac9efda06b4c27f93db3b8c177b97f9f18d`:
  GitHub Actions #40557056540 confirmed nine new offline upload tests
  errored on missing `upload_dir` support in `create_server`, while
  101 previous tests and four synthetic legacy checks remained passing.
- Initial implementation `209d8a14169592c128a0a0ca363fb110cc2d488d`
  was not integrated: Actions #40557303846 failed nine new cases
  because the multipart MIME prefix escaped CRLF incorrectly. Fixed
  in `e8f533a73668e7214624aa3cebef4eb87112f42a`.
  Actions #40557392874 then passed **4 legacy synthetic functions plus
  110/110 unittests** including all nine new upload cases.
- Implementation uses a 25-MiB maximum request body, strict
  multipart/field limits, random private filenames and 0600
  permissions, explicit CSRF and Host/Origin checks, SHA-256
  registration/deduplication, deletion on duplicate/error, and
  sanitization of HTTP responses. No arbitrary upload downloads.
  README documents local-only controls and missing virus scan,
  codec/content validation and abandoned-file garbage collection.
  Documentation commit `42231b48cbf1a50a713593070a8f1bb04735782c`
  passed GitHub Actions #40557616163.
- Changed: `strokesense/strokesense/web.py`,
  `strokesense/tests/test_upload.py`, `strokesense/README.md`,
  this durable history. Diff reviewed against previous integrated head.
  No source footage, sensitive local paths or secrets committed.
- Measured scheduled-session checkpoint 14:11:26 EDT from tool-recorded
  start 13:51:26 EDT: **20 minutes elapsed**. Further log/CI,
  integration and report steps may extend the observed duration.
  This is not a 30-minute work claim.
- Limitations: Only synthetic bytes and mocked worker tests were
  exercised, no real video decoder/ONNX inference, empirical accuracy,
  verified permission, human coach cue review, live LLM output or
  customer validation. Actual consent must be checked externally;
  local UI is unauthenticated and must not be network-exposed.
- Next: issue-based negative tests for evidence navigation and explicit
  withheld/verified coaching UI; no release without independent gate.
- Communication: scheduled-session email after final CI/integration;
  pending confirmation.


### 2026-10-27 15:00 sprint — evidence viewer schema hardening

- Issue #22 (existing evidence viewer, continuing the last unfinished increment).
  First integrated the 14:00 topic branch after confirming a clean two-commit
  fast-forward, red Actions #40558145506 and green Actions #40558386951.
  The viewer returns job-scoped, checksum-checked and allowlisted records and
  explicitly withholds unreviewed AI advice; no third-party provider calls.
- The 15:00 safety review found that the viewer verified a checksum but
  did **not** verify typed measurements, evidence referential integrity,
  counted denominators or false approval claims when a malicious record
  recomputed its own SHA-256. This is a concrete correctness gap, not an
  empirical performance metric.
- Story: as a coach, I want invalid saved evidence rejected before display
  so that malformed measurements or fabricated review states cannot appear
  as usable feedback. Acceptance: finite FPS/times, ordered frames, unique
  seats/strokes/findings, accurate counted observed fractions, known fault
  links, unreviewed-only version-1 states and fail-closed HTTP 409.
- Topic `dev/2026-10-27-1500-evidence-hardening`; integration base
  `538e36675fd50a325f54df6bb72af5cca72babab`.
  Tests were committed first at
  `26191353c90e9f4730e5ef4488cadf941726b0f2`;
  `python strokesense/quality.py` on Actions #40566398725
  showed **12 expected assertion failures** within three new regression
  test functions (HTTP 200 instead of 409), while older tests passed.
- Code commit `4cb39aeec485ec08759d11b23784c4dc6875ead1`
  added `validate_public_evidence_snapshot` in
  `strokesense/strokesense/evidence.py`, enforced it in `web.py`,
  and corrected the synthetic fixture to include the declared three
  strokes. Green Actions #40566710311 passed **119 unittests and 4
  legacy synthetic checks**, and the read-only doctor completed with
  runtime libraries available but no cached ONNX model.
- Additional green-only guard regressions verify rejecting oversized
  `metrics.json`, unsupported schema versions and HTML-injection seat
  names without echoing private paths. These test pre-existing expected
  defenses, not the original observed missing-behavior failures.
- No real video decoder/model inference, real-world coach agreement,
  reviewed cue catalogue, external LLM generation or customer KPI
  measurement was exercised. Consent claims are not independently
  verified; a local SHA-256 check cannot provide adversarial integrity.
  Human team inspection of AI-assisted tests remains pending.
- Next: issue-based TDD for source-content hash freshness in the pose
  cache when a video is replaced in place without changing its size or
  modification time, with benchmarked digest overhead. Keep `main`
  unchanged and preserve result-directory identity.


### 2026-10-27 15:00 sprint (continued) — source video digest and cache isolation

- Issue #23: As a coach, ensure a replaced file cannot silently reuse stale
  pose detections if size and nanosecond mtime are restored. Dedicated topic
  `dev/2026-10-27-1500-source-cache-fingerprint` from tested integration
  `9cd5c5f07c9b35a4e1dd100e24a73c587d8ff5bd`.
- **Red first:** three synthetic mocked regressions committed at
  `a229ddd77f1ede318a41e3e57792ca1e5299bbc3`.
  `python strokesense/quality.py` failed with three expected assertions
  on GitHub Actions #40567402995: same-stat replacement reused the cache,
  same-stat mid-inference mutation published an obsolete cache, and
  stat-only legacy identity was accepted.
- Code commit `f4254e4cd689d3c5050ce3526ac238ac4f67d5b3` streams
  full input SHA-256 and model SHA-256 using 1 MiB chunks with stat checks
  before/after hashing, never reading entire video into memory. Canonical
  source path, file stats, request settings and model data are still
  part of the versioned JSON cache key. Existing layouts and CLI flags
  are preserved. Old stat-only caches safely fail identity comparison.
- GitHub Actions green #40567687099 ran
  `python strokesense/quality.py`: **4/4 synthetic analysis checks plus
  125/125 unittests passed** including all three new regressions;
  `python strokesense/quality.py --doctor` confirmed runtime deps present
  but the ONNX model still absent. No model inference or actual video decode.
- Synthetic local disk benchmark (not CI, not rowing video): hashing a
  32 MiB repeated-byte file in 32 x 1 MiB chunks took 0.034775 s in
  this container (approximately 920 MiB/s, warm local filesystem).
  This one observation is not a cross-platform performance guarantee.
  Every cache check now incurs O(file size) read I/O, including cached
  reruns, and first-time runs may hash multiple times. No real-video
  latency/accuracy comparison was measured.
- Files: `strokesense/strokesense/cli.py`, `strokesense/tests/test_cache.py`,
  README and log. Human team review of AI-assisted tests remains pending.
  SHA-256 content fingerprint is not a cryptographic signature or a
  mechanism to prevent adversarial in-place mutation during decoding.
- Next: input argument validation for finite positive clip processing
  settings, then an end-to-end local demo on genuinely permitted media
  when available. Record real-asset blockers honestly.


### 2026-10-27 15:00 sprint (continued) — finite CLI numeric inputs

- Issue #24: As a coach, receive actionable argument errors rather than
  undefined or costly inference for negative/nonfinite time/rate parameters.
  Topic `dev/2026-10-27-1500-cli-numeric-validation`, based on
  `8dc17eaa522cd5562c89a5a9a1ad58862667ddb0`.
- **Tests committed before code:** `f119e2a461efb066e9186bbc67939ca0e548b409`
  added three tests with 12 invalid argument subcases and valid fractional
  forwarding. GitHub did not schedule the original test-only branch's
  push, so a separate unmodified-parser test checkpoint was pushed at
  `bfec0c2976b3d56696fa383a2ae70c697cb68f05` on
  `dev/2026-10-27-1500-cli-numeric-red` and Actions #40568709051
  **failed with 10 expected behavior assertions**. Note chronology
  accurately: the tests preceded implementation, but this red CI
  observation occurred *after* the code commit on the separate green
  branch. Do not claim it ran before code was written.
- Code commit `f9c1f388d75f57d702b8d6cbc4db9dbe21b46e06`:
  `strokesense/strokesense/cli.py` uses strict finite
  nonnegative/positive argparse conversion for start/duration/FPS,
  exits 2 for invalid input before analysis, preserves valid decimals
  and omitted whole-clip duration. No external model/footage accessed.
- Green GitHub Actions #40568413093 ran
  `python strokesense/quality.py`: **128 unittests and four legacy
  synthetic analysis checks passed**; `--doctor` detected runtime
  dependencies but no cached model.
- Files: CLI implementation, `strokesense/tests/test_cli.py`,
  technical README, and this handoff. Existing CLI commands remain
  unchanged for valid arguments. No real inference, new accuracy estimate,
  live LLM, human coach review, or customer evidence was performed.
  Team inspection of AI-assisted tests remains pending.
- Next: fail-closed local job completion if source changes during
  analysis, followed by permitted real-video end-to-end verification.


### 2026-10-27 15:00 sprint (continued) — reject jobs after source mutation

- Issue #25: As a coach, do not see a succeeded/reopenable report when
  registered source footage changed or disappeared during analysis.
  Topic `dev/2026-10-27-1500-job-source-recheck`, based on verified
  integration `3bf54bee4daa5c1c53a81c0210e9534022d0861a`.
- Two synthetic worker lifecycle regressions were **committed before code**
  at `b9d728af00c88791624597a34d53d2ac200b4c8a`.
  The isolated baseline branch `dev/2026-10-27-1500-job-recheck-red`
  at `3850e7d8e5099d1617658198d54305f56cc2e179`
  produced **two expected failures** in Actions #40569271748
  (old publisher returned `succeeded` after a same-stat source
  replacement and after source deletion). For accuracy of TDD chronology,
  the red CI execution happened after the test-first and fix commits,
  not before code publication; it is a valid replay against the
  test-only/unfixed baseline.
- Code commit `842cb12aab83078e06d2cf680cdc5721bc82040d`:
  `JobQueue._run` streams registered SHA-256 before and again after
  the analysis callback, before storing any success/report pointer.
  Source changes and missing/unreadable files fail with public
  `error_code=source_changed` and `report_path=None`; private
  paths/errors stay unexposed. Helper centralizes both checks.
- Green Actions #40569193401: `python strokesense/quality.py`
  passed **4 synthetic analysis checks plus 130 unittests**, including
  two new worker post-run regression cases; `--doctor` confirmed
  runtime modules present but no cached ONNX model.
- No actual rowing video, real-video pose inference, empirical accuracy,
  verified consent, live LLM, reviewed cue library or customer KPI
  was tested. This is not atomic/immutable storage: the local file
  could change after the second hash or be deliberately restored.
  All AI-assisted test inspection by the student team is pending.
- Session combined issues #22–#25 in distinct dated topic branches,
  retained separate intentional-red test checkpoints, and integrated
  only verified green commits; neither `main` nor repo settings changed.
  Concrete next task: evaluate the end-to-end local UI on genuinely
  permitted, decodable rowing footage when made available, otherwise
  add a safe media-format/decoder preflight with synthetic tests.

### 2026-10-27 15:00 sprint (continued) — fail-closed upload container preflight

- Story and issue #26: as a local coach, do not accept text or truncated
  binary files renamed as videos for registration. A bounded standard-library
  `strokesense/strokesense/media.py` helper checks plausible initial container
  header families, and `web.py` rejects bad ones with HTTP 415 before any
  private upload or registry writes. Existing CSRF, size, storage and
  deduplication controls are preserved. Tests use **synthetic plausible
  headers**, not playable or consented real media.
- New topic `dev/2026-10-27-1500-upload-signature`; verified base
  `41ba51d7594db4da3951afe5be40f2912332c0b4`.
  Red tests-first commit `263f83622ca8fbfd7ab9724e695231b3931ddd3f`
  updated synthetic fixtures and added nine invalid-container subcases.
  GitHub Actions #40570634002 ran `python strokesense/quality.py`:
  **nine expected assertion failures** (old upload returned 303 instead of
  415); all preexisting cases passed. This is a genuine pre-code red run.
- Implementation `087a8d17ad092904397e77d878f4e261d0161048`
  added header-size and family checks for MP4/MOV `ftyp`, RIFF/AVI
  and EBML MKV/WebM, adjusted synthetic fixture declared lengths,
  and documented behavior. GitHub Actions #40570969886 succeeded:
  `python strokesense/quality.py` passed **four legacy synthetic
  functions plus 132 unittests**, including supported-container and
  rejection tests; `python strokesense/quality.py --doctor` reported
  installed runtime modules but no cached ONNX model. Diff scoped to
  `media.py`, `web.py`, `test_upload.py`, README and this log.
- This check is deliberately **not** a decoder or trust boundary against
  malicious containers. It does not establish that a file contains video,
  that OpenCV can decode frames, or that footage was authorized. Some
  legacy QuickTime files without initial `ftyp` may be rejected. No
  actual footage, model inference, live LLM call, coach review or customer
  validation was carried out. Human inspection of AI-generated tests
  remains pending; no hidden AI checker or covert checker directive
  was found in the inspected text files.
- Measured first checkpoint: America/New_York 15:32:37 to
  15:40:36 (7 minutes 59 seconds elapsed); execution continues
  within the remaining allotted budget. Do not claim a full 30 minutes.
  This is a continuation of the already logged 15:00 occurrence,
  not a second scheduled run or email.
- Next engineering step: validate basic media decoding in the local
  worker before expensive pose inference; do so without converting
  synthetic unit-test fixtures into fake real videos. Preserve tested
  integration and never change main.
- Communication: one consolidated factual 15:00 report after remaining
  verification and branch integration; pending confirmation.


### 2026-10-27 15:00 sprint (continued) — early video decode preflight

- Issue #27: as a local coach, see a safe actionable failed analysis
  for registered nondecodable media before pose estimation starts. Topic
  `dev/2026-10-27-1500-job-decode-preflight`, based on verified integration
  `fb2d0eb5740a7c6d8cb60ad547bdfe5050b6e718`.
- TDD test-only commit
  `8c3bc697a21a754e8d3649d1f4dc32016b702573`
  preceded implementation; Actions #40571847478 ran
  `python strokesense/quality.py` with **five expected behavior
  failures** across worker rejection, valid capture invocation, and bad
  metadata / missing-frame cases. Earlier cases passed.
- Implementation `9bfbd8c26be14c308d7c79f2c408e332d514b456`
  adds `media.probe_decodable_video`: background-only lazy OpenCV
  VideoCapture, finite FPS/dimension checks, at least one decoded frame,
  release of capture on all paths, and a 4K/240fps ceiling for this
  local Alpha. `jobs._default_analyze` raises a typed media failure
  before model loading; `JobQueue` maps it to public
  `failed/invalid_media` with no report URL. Existing injected fake
  analyzers remain independent of real footage. README updated.
- Green Actions #40572120062 ran
  `python strokesense/quality.py`: **135 unittests and four synthetic
  technique functions passed**; doctor found runtime modules but no
  ONNX model asset. Follow-up post-code smoke test committed at
  `45691790aeddf551af0839c49c59ab1d53441c41`
  generated a three-frame toy MJPG AVI and verified real OpenCV opening,
  frame decoding and mock analyzer forwarding. Actions #40572392258
  passed **136 unittests and four synthetic technique functions**;
  the smoke test executed and passed (not skipped).
- Scope: synthetic generated video and mocked frame tests only; no
  actual permitted rowing footage, real model inference, customer
  validation, human coach review, approved cue catalogue or live
  external LLM. The header and first-frame checks cannot guarantee
  later-frame decoding, codec safety or malware resistance, and
  intentionally exclude certain unusual files. Student-team review
  of AI-assisted tests is pending.
- Main never touched. To continue within the remaining budget:
  next consider a bounded-duration safeguard for full-clip local jobs
  to avoid unbounded inference on heavily compressed long videos.
  Document behavior, do not imply security sandboxing.
- Measured running checkpoint: 15:32:37 to 15:49:35 EDT
  (16 minutes 58 seconds elapsed); this includes two separately
  tested increments and is not a 30-minute work claim.
- Communication: consolidated issue/branch/CI progress report after
  final safe integration and duplicate Sent check; pending.


### 2026-10-27 15:00 sprint (continued) — bounded local video duration

- Issue #28: as a local coach, prevent a compressed multi-hour or
  unmeasurable clip from monopolizing pose processing. Topic
  `dev/2026-10-27-1500-video-duration` from verified integration
  `1a02a6c6d1b92353789c331f8e4624944c109135`.
- Test-first `c70571bf01f005f355302079df6f7f56d52b5d8d`
  updated the mocked known-frame-count setup and added four negative
  duration subcases (zero, NaN, negative, 121 s at 30 fps).
  GitHub Actions #40572872909 executed `python strokesense/quality.py`
  and recorded **four expected assertion failures** against unbounded
  production behavior, all prior cases green.
- Implementation `d81fd2c50d4bed0ad588b50971b308230dc13eda`
  enforces finite, positive reported frame count and `count/fps <= 120`
  before reading the first frame. It reuses the existing typed
  `UndecodableMediaError` and sanitized `invalid_media` job status.
  README describes conservative limits and false rejections for
  unindexed/variable-frame-rate files.
- GitHub Actions #40573038496 completed **successfully**:
  `python strokesense/quality.py` passed **137 unittests plus
  four synthetic legacy analysis functions**, including the new
  duration test. `python strokesense/quality.py --doctor` found
  analysis modules installed but no downloaded ONNX pose model.
  No real rowing footage, coach comparison, reviewed cues, live provider
  inference, end-to-end pose runtime or customer KPIs were measured.
- Native OpenCV has actually decoded the separate generated toy AVI
  in the previous issue, but there was no real user clip and the
  duration bound trusts potentially inaccurate container metadata.
  It is not a hard CPU timeout, malware scan, consent verification,
  security sandbox or guarantee of fully decodable video.
  Human team inspection of AI-assisted tests remains pending.
- Measured checkpoint 15:53:50 EDT from 15:32:37 EDT
  (21 minutes 13 seconds). This three-increment continuation does
  **not** claim the full 30-minute work budget.
- Next: a reproducible local end-to-end browser happy/error-path demo
  with explicitly synthetic fixtures and a fake analysis adapter,
  showing upload, job status, report reopen and withheld advice; use
  genuinely permitted video/model only if available and label gaps.
  Prioritize code quality over decorative UI. Do not touch main.
- Communication: send one consolidated factual progress email after
  integration and duplicate-Sent check; pending.

### 2026-10-27 16:00 sprint — API errors and permission withdrawal

- Scheduled occurrence: `2026-10-27-1600-sprint`, America/New_York.
  This worker's independently measured start was **16:31:56 EDT**
  (monotonic 535.8759); first verification checkpoint **16:41:01 EDT**
  (about **9 minutes 5 seconds** elapsed). Earlier 16:00 topic work
  preceded this delayed worker; do not claim its time as measured here.
- Reconciled existing completed 16:00 issue work without duplicating it:
  #29 opt-in upload-to-analysis was green on existing topic
  `dev/2026-10-27-1600-upload-analyze`; #30 reproducible offline
  synthetic browser demo was integrated at `586b6051`.
  #31 machine-readable, fail-closed `application/problem+json` API
  errors had tests-first red Actions #40577206601 (**four expected
  assertions failed in 151 unit tests**) and green Actions
  #40577572081 (**151 tests plus four legacy synthetic functions**).
  Verified the three-file diff, response contract, and CI; safely
  fast-forwarded integration from `586b6051` to topic `39469a4`
  with an expected-head guard. #31 remains open pending wider error-code
  route coverage; the implemented common routes are tested.
- New issue **#32**: as a coach, withdraw an operator permission claim
  so no new/in-flight analysis of that clip can be published.
  Topic `dev/2026-10-27-1600-consent-withdrawal`, base `39469a4`.
  Test-only commits `b74733e` and `1a09bb7` preceded production.
  `python strokesense/quality.py` on Actions #40579650482 showed
  **2 expected behavioral assertion failures and 3 expected missing
  revocation API/CLI errors** among 156 tests; legacy synthetic checks
  ran. This was missing functionality, not an import/environment failure.
- Implementation `4dd30b964435d04259461b4fd984bb81d24deeb6`
  adds transactional/idempotent `registry revoke`, preserves private
  clip metadata, rechecks permission before and after the worker's
  analyzer, and withholds revoked queued/in-flight jobs with safe
  `permission_revoked`. Changed `registry.py`, `jobs.py`, README,
  and added five test cases in `tests/test_revocation.py`.
- Green GitHub Actions **#40580034840** executed
  `python strokesense/quality.py`: **156/156 unittests and four
  synthetic analysis functions passed**. Read-only
  `python strokesense/quality.py --doctor` found runtime modules
  installed, ONNX pose model not cached, no actual inference.
  Test suite includes offline fake media and mocked report creation;
  no permission, coach label, footage or live provider empiricism.
- Privacy limitations: revocation neither deletes historic files nor
  revokes an already downloaded report. A running analyzer may continue
  computing; its result is withheld by a pre-publication check, which
  is not an atomic guarantee against races. Human team inspection of
  AI-assisted tests remains pending.
- Next: enforce revocation when reopening historical reports and evidence
  via the browser, with new issue and independent test-first evidence.
  `main` remains excluded; communication pending Sent confirmation.

### 2026-10-27 16:00 sprint (continued) — withhold browser access to revoked clips

- Issue **#33**, topic `dev/2026-10-27-1600-revoked-web-access`
  based on verified integration `fdfef67b`. As a coach, when a clip's
  local operator permission is withdrawn, prior job reports/evidence and
  status links must no longer be served by the loopback UI/API. Other
  permitted clips must remain accessible.
- Tests-first commit `ed5751c3dfe6d2e3564ffc41726f1dffc398ffc3`
  added 3 synthetic HTTP cases. GitHub Actions **#40580738910** ran
  `python strokesense/quality.py` against the unfixed baseline and
  observed **six expected behavior assertion failures** within
  159 unittests: five direct revoked job/status/report/evidence routes
  returned 200 instead of 403, and the homepage history retained a
  revoked job. Other tests, including allowed-clip behavior, passed.
- Code commit `7ed13608212028ddb995f308053b9ed021e66076`
  adds current registry permission checks before serving historical
  job status, report and evidence, plus filters homepage/API recent
  history. `/api/` errors continue using sanitized Problem Details;
  browser errors remain HTML, with no-store and existing security
  headers. Only `web.py`, README and the new test file changed.
- GitHub Actions **#40580961440** completed green:
  `python strokesense/quality.py` passed **159/159 unittests**
  and four legacy synthetic technique functions; the read-only
  `--doctor` reported installed runtime modules but no cached
  ONNX pose model. No real footage, model inference or actual
  consent evidence was tested. Revocation blocks current read routes
  but does not delete historical files or recall previously downloaded
  copies; a read/revoke race remains possible. Team review pending.
- Measured worker checkpoint: **16:46:34 EDT**, ~14 minutes 38 seconds
  after 16:31:56 EDT actual start, not a claimed 30-minute session.
- Next action: browser permission-withdrawal form guarded by
  CSRF and Host/Origin checks, with test-first negative cases.
  Communication pending consolidated email after safe publication.

### 2026-10-27 16:00 sprint (continued) — private browser withdrawal

- Issue **#34**: as a local coach, withdraw the current local
  operator permission claim from the same loopback-only Alpha browser.
  Topic `dev/2026-10-27-1600-web-revoke-form`, base `842f4663`.
- **Tests committed first:** `031e23dc4d4d33e4f9b86bb2bb6c7a155c176f68`
  added three synthetic HTTP integration test functions with forged
  CSRF/Origin/Host, unknown/malformed/duplicate request inputs, previous
  report blocking and permitted-clip selection. Actions
  **#40581464304** ran `python strokesense/quality.py` and observed
  **six expected behavior assertion failures** (unimplemented
  `/revoke` route and missing form); unrelated cases passed.
- Code commit `7063d4a3c14827db6ff8b58b3de3cf5f4d9e8416`
  adds an explicit separate browser withdrawal form and a bounded
  POST `/revoke` that reuses existing Content-Type, CSRF, Host/Origin,
  field cardinality and clip ID validation; it invokes the previously
  tested atomic `registry.revoke_clip` and redirects to home. The
  already-verified #33 read-time gate blocks previous reports; no
  historical video/report files are deleted. README updated.
- Actions **#40581629204** completed green:
  `python strokesense/quality.py` passed **162/162 unittests and
  all four legacy synthetic stroke checks**;
  `python strokesense/quality.py --doctor` detected runtime modules
  but no cached pose model, and did not infer video. Verified changed
  files are `web.py`, README, `test_web_revoke.py` (and this log).
- Session actual start **16:31:56 EDT**; checkpoint
  **16:51:57 EDT** (`time.monotonic` 535.8759 to 1736.3486,
  ~20 minutes measured). This continues the 16:00 occurrence,
  not a claim of 30 minutes of work.
- No genuine footage, real-video precision/recall/timing, external LLM
  execution, approved coaching cues, verified consent or customer
  KPI was measured; all tests are synthetic/mocked. Server remains
  local loopback, not a public authenticated service.
  Human inspection of AI-assisted tests remains pending.
- Next: harden and complete #31 API error-code coverage; then
  assess explicit retention/audit strategy in a narrow issue.
  Communication pending confirmed Sent check after integration.

### 2026-10-27 17:00 sprint — fail-closed HTTP methods

- Session key `2026-10-27-1700-sprint`; America/New_York actual
  start **17:01:44 EDT** (`time.monotonic_ns` 101463822631);
  verification checkpoint **17:10:05 EDT** (`time.monotonic_ns`
  601745630167), **8m 21s measured to that checkpoint**, with
  integration/communication potentially following. No 30-minute claim.
- Reused open **issue #31**, local API Problem Details/error-contract
  user story. Topic `dev/2026-10-27-1700-http-methods` from
  verified integration base `d49546c2c52794d20453f510291eea5da25838b6`.
  Acceptance: unsupported methods get sanitized 405, appropriate
  `Allow`, no-store/privacy headers and no HEAD response body;
  Host/Origin validation also applies. Unknown routes remain 404.
- Test-first commit `f0e0b9db4ffbb3bc16f2bc7ee9af16fac026304c`
  added three HTTP regression tests for common unsupported methods,
  forged origins and HTML browser compatibility. GitHub Actions
  **#40583792311** ran `python strokesense/quality.py`; among
  **165** offline unittests, **24 expected behavioral assertion failures**
  (old 501/404 instead of 405 or 403), not an environment/import error.
- Production commit `02f6a71092869fd151dc391e2fa0f023b8d5cb07`
  implements safe `_error(405)`, route-specific `Allow`, HEAD
  empty body, and explicit common-method rejection. Actions
  **#40584005101** was green (165 tests, four synthetic functions).
- Before the next production change, additional test-only commit
  `acf44f2b6025fbd3ffc384234d858cd4b3a9079a` covered
  extension verbs BREW and PROPFIND. Actions **#40584165377**
  observed **three expected failures** (501 instead of 405/403)
  in **166** unittests. Code commit
  `f63a53c4fa29a759390850504f131193c4943ace`
  adds safe fallback dispatch for unknown method names; Actions
  **#40584304598** ran `python strokesense/quality.py` and
  **passed 166/166 unittests plus four synthetic analysis functions**.
  Its read-only `python strokesense/quality.py --doctor` found runtime
  dependencies installed but **no cached ONNX model**. Targeted HTTP
  regressions were included in full unittest discovery.
- Files: `strokesense/strokesense/web.py`,
  `strokesense/tests/test_api_errors.py`, and this handoff.
  Diff review: 53+ production insertions and 7 deletions, tests
  cover common and extension method dispatch. No PR, settings, or
  default branch change.
- This is offline synthetic loopback HTTP behavior, **not real-video
  inference, empirical rowing precision/recall, live LLM output or
  customer validation**. Team inspection of AI-generated tests pending;
  #31 remains open for wider status-path exercise. Existing revocation
  does not delete past private footage/reports or recall downloads.
- Next: verify API 409/413/503 and browser compatibility through real
  local routes, then consider a versioned privacy/data-retention audit
  mechanism that does not erase data without authorization.
- Communication: pending confirmed Sent search after integration.

### 2026-10-27 17:00 sprint (continued) — complete #31 API error paths

- Reused issue #31 after integrating the preceding tests-first code
  fix. New dated topic `dev/2026-10-27-1700-api-status-coverage`,
  base `ee48e6b77b14c605ee2d16b0bc78d8d537505f46`.
- Added four **regression tests for existing behavior**, not incorrectly
  described as new TDD implementation: fake successful local job with
  invalid metrics => actual API 409 and browser HTML 409; oversized
  metrics => API 413 without loading content; jobs database failures =>
  API 503 without internal exception text. A clearly labeled test-only
  handler injection checks the shared Problem Details serializer for
  400/403/404/405/409/413/415/422/503. This does not create public API
  routes for every status. Tests use only synthetic bytes/fake analysis.
- Test/commit `f53221a79dd45255cca8561e2971c9b09fb28d28`;
  GitHub Actions **#40585010706** ran
  `python strokesense/quality.py` with **170/170 unittests and all four
  synthetic stroke checks passing**, and read-only
  `python strokesense/quality.py --doctor` found dependencies installed,
  cached ONNX model absent. No production change was necessary for these
  existing API response paths; no import or environmental failures.
- The issue's method behavior was separately demonstrated RED before
  GREEN in the first 17:00 topic. This continuation is additional green
  route-level coverage, not an invented red checkpoint. Team inspection
  of AI-assisted tests remains pending.
- Actual session start **17:01:44 EDT**, measured checkpoint
  **17:14:44 EDT**, about **13 minutes**; any later work will be
  separately measured. No full 30-minute claim. No live LLM, permitted
  real footage, athlete-consent verification, coach labels or empirical
  video accuracy was measured.
- Next: a non-destructive, privacy-safe schema migration for a first
  permission-withdrawal timestamp; create a new issue and red tests
  before production. Keep files intact and do not touch `main`.
- Communication: one consolidated factual email after final safe
  integration; pending.

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
