# StrokeSense current handoff

The preceding root log is preserved byte-for-byte in [llm-history-2026-11-02-blade-pilot.md](llm-history-2026-11-02-blade-pilot.md), original Git blob `6c9690aef3cbd6712505ead321ad303b4a93b9c0`. All earlier linked history remains. Expired October sprint schedules were not resumed or modified.

## 2026-11-02-1323-manual — two-entry quick rate and blade position evidence (#107)

### Scope and current status

Manual follow-up to the user's request for improved accuracy, positioning, and speed, explicitly accepting two blade entries for rate. Start `2026-11-02T13:23:43.339082-05:00`, monotonic108.288373907. Verification checkpoint `2026-11-02T13:39:07.245946-05:00`: measured923.907seconds (15m23.907s), excludes subsequent documentation/publication/email. Final closeout duration belongs in issue107. This is not a resumed October sprint and not a claim of30minutes worked.

Topic `dev/2026-11-02-1323-fast-blade-rate` from inspected integration `a006246c7e1b646f61ae3d672a61b8db0fa312f7`; inspected main `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`. Read the full root handoff, selected proposal, relevant source/tests and inspected remote heads; no applicable AGENTS/CLAUDE instruction file was present in the exact tracked source. Issue107 was created before implementation. Issues103/106 remain open for real tracking/contact-model accuracy. The supplied Windows localhost report was NOT accessed; plugin discovery found no connected Windows desktop controller. No inference about its unseen contents is made.

### Implemented bounded behavior

New `blade_quick.py` is the default version3 model-only worker path. Two entries of ONE blade define one interval; one supported interval is enough for a provisional estimate. Sampling starts at the chosen reference and proceeds lazily, retaining source timestamps and the prior approximately10fps/full-scene1280px sampling resolution. Work stops after the target interval is supported outside the unresolved four-frame overlap tail, rather than predecoding and modeling an entire20second window. Maximum320frames/40MiB/private evidence budget remains. Optional `STROKESENSE_BLADE_TARGET_CYCLES=1..5` requests a longer estimate; default1. It never fills missing catches or adds other blades.

The model must now return finite normalized blade-position boxes for visible air/water classifications. Whole-frame boxes, malformed IDs/coordinates and missing visible positions are refused. The first sampled reference location must contain the operator's point (1% frame tolerance); otherwise the report is unavailable with reference_unconfirmed after one request, not a fabricated rate. Same-source overlapping-window position disagreement over5% of image dimension becomes unknown. Isolated one-sample state runs become unknown rather than extra catches. Unknown/time/identity gaps still break intervals. These are conservative engineering checks, NOT calibrated guarantees of identity or contact correctness.

Entry pictures show model-predicted blade boxes; private metrics preserve positions, frame hashes, source times, model digest, sampled/advanced frames, request/image counts, stop reason and measured processing/request durations. Optional Ollama timing fields are retained when valid. The adapter uses keep_alive10m between requests; no model replacement, installation, download, paid API or cloud provider was added. Existing local-only restrictions, source/permission checks and isolated worker remain. One model request at a time avoids simultaneous large-VLM memory pressure. No speed gain from changing hardware or lowering resolution is claimed.

Positioning here means BLADE LOCALIZATION. Body posture/angles, eight-rower identity accuracy and learned technique assessment were NOT improved or newly validated. No old body-curve/fault-rule fallback runs. The old callable blade_video full scan remains for compatibility; production v3 jobs dispatch to blade_quick. The legacy pose mode is unaffected. UI text states two entries; startup banner is unchanged.

### TDD, verification and exact artifacts

Test-only remote commit `101bb39dda3522291b630d22416bc539e0611438` precedes production `7afc337ac6db83b7c866f948fa587f629254aea4`. Initial `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s strokesense/tests -p test_blade_quick.py -v`: nine explicit missing-API assertions in0.183s, not import failures and not measured real-world inaccuracies. After implementation the nine passed. A further test was added before reference-anchor validation: a synthetic wrong-blade location incorrectly produced30SPM; that observed assertion failed (30.0 is not None), and passes after the reference check. The existing dispatch mock was updated to the new worker module without weakening its no-heuristic-fallback requirement. An initial all-unknown test expectation was updated to reference_unconfirmed after the new early reference rejection; it still asserts no rate, no fallback and one request.

Final targeted `-p 'test_blade*.py'`:29 tests passed in0.903s. Full `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python strokesense/quality.py`:575 executions passed in52.975s plus four existing legacy synthetic functions. Earlier complete run574/55.222s also passed. One initial invocation was interrupted by the tool's1second timeout before rerunning to completion; it is not counted as a complete test result. Existing Python3.13 SQLite ResourceWarnings remain visible but caused no failure in these runs; no suppression/assertion weakening was introduced. Counts include existing repeated fixture discovery, not unique tests. Diff whitespace checks passed.

Actual local full-path test used a generated200-frame AVI and a clearly labeled fake Ollama HTTP server: real library POST303 -> real isolated Python child -> actual new model request/receipt/report pipeline -> succeeded job and report GET200. Two24-frame requests produced the controlled30SPM result and localized evidence. The fake service was stopped afterward. This validates runtime integration, NOT real model vision.

Exact production topic remote offline run41502179695 and existing Chrome run41502179702 completed success. Native Chrome includes existing single-blade controls/confirmation but uses a fake analyzer; it is not a live-inference/real-user accuracy test. Local Chrome navigation returned ERR_BLOCKED_BY_ADMINISTRATOR; no bypass attempted. Final documentation-commit CI/integration are PENDING at this root checkpoint and must be confirmed before claiming completion. Communication also PENDING.

The largest changed source and test blobs were reread and matched local verified bytes: blade_quick `c9aa187d6b28074e400d64c625a9d7a10dd9a22d`; blade_ui `758b8ae4d184c790d61273bcc52b225ca69ae626`; test_blade_quick `d35dd2e263392b8bd158afd796223050e68225a9`. Remaining expected one-line dispatch/mock changes are in the scoped diff. Main/default/settings/schedules/PRs were not changed; no branch deletion or history rewrite.

### Measured workload comparison and real-media limitations

Same synthetic20second recording, deterministic model double representing30SPM:
- Old fixed scan:10 requests,246 submitted images including repeated references/overlaps,200 sampled frames,9 cycles,30SPM.
- Quick default:2 requests,50 submitted images,44 sampled frames,1 cycle,30SPM.
This is80% fewer model requests and about80% fewer submitted images on this controlled case, NOT a measured real-Qwen runtime speedup. Different model output/occlusion can use the entire budget or withhold. Localization output itself adds work per request. Test-double wall times are not promoted as production speed measurements.

Actual private source MP4:12 samples at0.0,0.1,...1.1seconds decoded from30fps input (stride3), advancing34 source frames, in0.479s. This confirms real decoding/source times/lazy closure, NOT detection/contact/SPM accuracy. No private video, source path, frame hash or identifying metadata was published. A read-only call to configured local Ollama returned local_model_unavailable; no live vision model ran here. Doctor: scientific libraries/FFmpeg present, ONNX Runtime missing/model uncached (separate legacy path). No fresh internet-video inference or new labeled accuracy metric is claimed. Windows and human review remain pending.

### Documentation and next action

See [strokesense/BLADE_QUICK.md](strokesense/BLADE_QUICK.md) for default quick-mode behavior and reproducible commands. The prior [BLADE_MODEL.md](strokesense/BLADE_MODEL.md) remains the local runtime setup reference; its historical full-window/five-cycle discussion is superseded by BLADE_QUICK for production v3 jobs. New analyses are required; old reports/data are preserved, no deletion/reupload needed. Model-only blade mode must be selected explicitly; this increment does not make the legacy pose analyzer faster.

Primary API documentation consulted: official Ollama api/chat and structured-output docs (keep_alive, image input, timing fields). These establish the API contract, not model accuracy. No suspicious hidden AI-checker directive observed; legitimate hidden CSRF/reference form fields are not instructions.

Activity2 story/acceptance and Activity3 observed red-to-green are in107. Proposal criteria1/3/4/8 gain a bounded local rate/evidence workflow; remaining live model/coach/customer criteria are unclaimed. No substitution for Activity1 customer validation. The requested body-position quality improvement and empirical accuracy gains remain open, not bundled into a completed rate optimization claim.

Next action: annotate a permitted SAME-BLADE video with real entry timestamps and visible position boxes, run the installed model, and compare event precision/recall, SPM error, localization error, unknown coverage and wall time against those labels. Keep103/106 open for those measured results.
