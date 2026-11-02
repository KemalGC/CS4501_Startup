# StrokeSense current handoff

## Preserved history

The preceding current log is preserved byte-for-byte at [llm-history-2026-11-01-dynamic-crew.md](llm-history-2026-11-01-dynamic-crew.md), original Git blob `6def473b2958eeea876408d19239527fe990d9e6`. It links the complete October history and earlier manual companions; those files are unchanged. No history or scheduling metadata was discarded. The October 27–29 sprint has ended; no old schedule is resumed by manual work.

## 2026-11-01-1631-manual — resilient results and qualified crew cadence (#101)

### Session and safeguards

Actual start `2026-11-01T16:31:52.748966-05:00`, America/New_York; monotonic start61.323721198. Verification checkpoint `2026-11-01T16:48:05.885985-05:00`: elapsed973.137 seconds (16m13.137s), excluding later publication/email/closeout. This was the user's manual follow-up to a connection-refused screenshot, VP80/WebM warning and a45spm result from one detected cycle among33–35spm multi-cycle results. The warning alone does not prove what terminated Windows Python; its exit code/traceback was unavailable.

Topic `dev/2026-11-01-1631-resilient-results` starts at inspected integration `168174807ac3167fc95955f77dc8d3f9b8f9de09`. Main inspected at `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`. Existing issues/remote heads and applicable source/tests/proposal were read. No main/default/settings/PR/branch deletion/automation changes; private footage stays local. Integration and communication are PENDING at this commit, to be confirmed in #101 after publication. Human review remains pending.

### Story, implementation and tradeoffs

#101 contains two coupled results-reliability stories: keep the local website available when native analysis fails, and show evidence-qualified crew cadence rather than treating one noisy cycle as a confident different rate.

`analysis_worker.py` isolates production inference/rendering in a bounded child using the same Python executable, unbuffered output and faulthandler. JSON request on stdin and a private <=16KiB receipt carry only report/media pointers back. No shell/pickle/new service/dependency. Queue validation, source hashes, permission rechecks, artifact containment/limits and withheld coaching remain. A nonzero child exit/timeout becomes the existing retryable public `analysis_failed`; original invalid-media/selection codes stay intact. Local exit diagnostics print the code. Injected test analyzers retain their old behavior. Default job upper limit3600s; external encoding upper limit120s. This is process isolation, not a security sandbox or protection from system-wide OOM, closed PowerShell, preview-process faults, or every possible native failure. A hard child crash fails the job, not salvaged partial outputs.

`render.py` removes the unchecked OpenCV VP8/WebM fallback. It checks the mp4v writer, releases it on failure, encodes H.264 via an existing local FFmpeg executable (PATH or already installed imageio_ffmpeg), validates nonempty decodable output, then atomically publishes it. Failed encoding keeps pre-existing output/intermediate; there is no false media link. Missing encoder or catchable rendering failure becomes `RenderingUnavailable`; CLI continues report/metrics/snapshots with an explicit annotated-video-unavailable notice. No automatic encoder installer added. Video HUD uses qualified crew cadence, not an arbitrary seat's instantaneous rate.

`cadence.py` retains all original strokes/summaries. Per-rower median rates with >=2 finite in-range cycles and bounded within-rower dispersion can support a shared estimate; boats of >=3 need at least3 agreeing eligible rowers and a strict majority of eligible observations. Agreement tolerance is max(2spm,10% centre). Output includes supporting rower/cycle denominators and low-sample/unstable/outlier/no-cycle labels. A one-cycle45spm estimate is retained as raw and marked unconfirmed, not overwritten to34. Consensus is a heuristic, not a common-timebase measurement, proof of synchronization, corrected segmentation, or empirical accuracy improvement. Different observation windows/rate changes remain a limitation. Existing heuristic technique scores were not newly validated or replaced.

CLI/report show this distinction and preserve no-cycle/coverage states. No production web.py, registry schema, tracking, source permissions or generator validators were changed. Existing reports are not rewritten; new analysis is needed. Guide: [strokesense/RESULT_RELIABILITY.md](strokesense/RESULT_RELIABILITY.md).

### Observed tests and failures

Test-only commit `994f85ee2e1ccf723095c70e10a768e664fed235`: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s strokesense/tests -p test_resilient_results.py -v` ran10 tests with10 expected missing-feature/API assertions in0.003s, not import/environment failures. The tests explicitly asserted absent isolation/cadence/error surfaces before exercising behavior; this was not a reproduced OpenCV native crash. After implementation all10 passed in1.054s.

Production commits: child22ace0c7; cadence7387441c; queue8b8f7018; rendering45429908; CLIea30f44c; reportd12ba3a2. Test refinement203d0938 preserves the established `analysis_failed` public code and adds Retry analysis verification instead of introducing a new unrecognized code. Five later integration-era regressions at97222112 are not mislabeled initial TDD; all five passed locally in1.060s. Source blob hashes match the published six production files. `git diff --check` passes.

An initial local prototype error in a custom web error-message branch was caught by the abrupt-exit HTTP test; the entire web change was removed, preserving the established web.py byte-for-byte. A temporary render-HUD indentation mistake caused an early full-run failure/timeout and was corrected before publication. These are implementation errors, not reported as expected TDD failures.

One clean intermediate full local run passed504 test executions in47.355s plus four legacy synthetic checks. After adding the five integration tests, two complete Python3.13.5 runs executed509 tests but each had ONE failure: an older evaluation CLI test's stderr assertion captured a delayed ResourceWarning about an unclosed SQLite connection from preceding fixtures. The final rerun took46.314s. This local full result is NOT claimed green. The isolated unchanged evaluation suite passed7 tests in0.016s; no warnings filter, relaxed assertion or hidden suppression was added. Existing fixture connection cleanup is a remaining Python3.13 test-harness limitation.

The exact published code/test head `972221123d7989ea1df6f875c8d312704e21a27a` passed complete offline GitHub CI https://github.com/KemalGC/CS4501_Startup/actions/runs/41353555729 and existing native Chrome CI https://github.com/KemalGC/CS4501_Startup/actions/runs/41353555797. CI uses Python3.11, distinct from the local3.13 warning behavior. Test-execution counts include existing repeated fixture discovery and are not unique-case counts. No claim of Windows/Python3.14 certification.

Specific new evidence: a REAL child deliberately exits via os._exit(17); queue marks analysis_failed, HTTP GET of its job page remains200 and Retry analysis is present. A real sleep child is bounded by a0.1s test timeout. Synthetic child success receipt is validated and private working files cleaned. Encoder-unavailable tests retain HTML/JSON/evidence without media, failed FFmpeg output is rejected, and raw outlier rates remain unchanged with qualification. Detector inputs for report tests are synthetic, not live model output.

### Real video and unavailable validation

The supplied private MP4 was actually decoded, resized and encoded using the updated renderer with NO rower overlays/inference:113 frames at15fps,1280x720, verified H.264 output,3,285,856 bytes, measured3.63 seconds in this Linux environment. This tests the source video's decoding/encoding path, NOT real pose detection, rower identity, stroke accuracy or the exact Windows crash. Private media/output paths and identifying hashes were not published.

Read-only `python strokesense/quality.py --doctor` found Python3.13.5, NumPy/SciPy/OpenCV/Matplotlib and /usr/bin/ffmpeg, but ONNX Runtime missing and pose model uncached. It is incomplete locally, not an inference test. No model downloads, live LLM calls, customer validation, coach approval, precision/recall or empirical SPM error claims. Local native browser access remains blocked by environment policy from prior work; existing Chrome tests run on the GitHub Linux runner, not Windows. No suspicious hidden AI-checker directive found in inspected material; ordinary hidden CSRF controls are expected application data.

### Traceability and next action

#101 -> test-only994f85ee red -> isolated child/queue + encoding fallback + cadence/report ->203d0938 compatibility assertion +97222112 integration regressions -> full exact-tree CI -> this log and operator guide. Activity2 story/acceptance and Activity3 observed test-first assertions are recorded; human test review pending. Proposal criteria1/3/4/8 gain reliable local result delivery and qualified evidence; criterion2 still needs actual customer feedback; criteria5/6/7 get no new live LLM/release/correction validation here. Activity1 empirical KPIs remain unmeasured.

Next action: guarded fast-forward after current-head checks, confirm post-integration checks and send one deduplicated factual update. Then user restarts the library launcher and retries analysis; inspect whether reports remain available with video unavailable on Windows, and collect any child exit code before asserting the original native-crash cause. Do not delete recordings or force equal SPM values.
