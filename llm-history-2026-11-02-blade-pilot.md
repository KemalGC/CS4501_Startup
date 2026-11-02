# StrokeSense current handoff

Prior root contents are preserved byte-for-byte in [llm-history-2026-11-02-measurement.md](llm-history-2026-11-02-measurement.md), original blob `d20c54943615e7ef6a584eb1434b5ff1d15c34f0`. Earlier linked logs/history are unchanged. The October sprint is expired; manual work does not change or resume schedules.

## 2026-11-02-1042-manual — model-only blade-rate pilot (#106)

### Request, scope and safety

User requested model-only analysis and specifically proposed blade entry for stroke rate. Actual start `2026-11-02T10:42:16.387177-05:00`, monotonic206.097465398. Reporting checkpoint `2026-11-02T11:05:51.518976-05:00`, measured1415.132 seconds (23m35.132s), excludes subsequent publication/docs/communication. Final duration belongs in issue closeout; do not call this a30-minute run. This is manual Nov2 work, not resumed sprint. Topic `dev/2026-11-02-1042-blade-model` from inspected integration `d7572ae893c2159e2b401803e679b47b957191e6`. Main inspected at `3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc`. Issue106 records story/criteria before implementation. Issue103 remains open for labeled real-video quality.

As a coach, I want a local vision model to classify one confirmed blade's water contact so rate comes from repeated entries of that blade, not body-curve peaks or adding eight oars together. This is an opt-in EXPERIMENTAL rate path, NOT a validated replacement for rowing technique analysis. No large accuracy improvement is claimed. No pose/body-curve/fault-rule fallback runs inside this path. The legacy mode remains separate. Technique grades, curves and coaching are withheld in model-only mode; no learned technique classifier has been trained or validated.

### Implementation and traceability

- New `blade_model.py`: strict per-source-frame JSON observations (air/water/unknown, same-blade identity), overlapping-window agreement, entry brackets and rate arithmetic. Continuous immersion/start-underwater is not another stroke; unknowns, identity loss and sample gaps break continuity. Six entries define five cycles. Longest continuous supported run is summarized with sampling-only bounds, explicitly not a model-confidence interval. Model output cannot supply rate, frame times, validation rules or free-form coaching.
- Configurable already-installed local Ollama vision adapter: numeric127.0.0.1 only, proxies/redirects/cloud-tag and remote metadata refused; installed model digest/vision capability checked before images and rechecked afterward. Structured image request, temperature0, bounded frame/request/response/time limits; incomplete/extra/duplicate/malformed output fails closed. No model pulls, installers, paid providers or cloud upload in page requests. The trusted local server should also run with OLLAMA_NO_CLOUD=1. Correct schema is not evidence of correct vision.
- New `blade_video.py`: source-timestamped sampling up to20seconds around a reference, approximately10fps, at most320frames and40MiB JPEG evidence. Same marked reference accompanies each24-frame window, four overlapping samples check agreement. Hash-check source before/after, unique private run directory, model digest/frame hashes/raw observations saved. Report embeds before/after pictures for up to8 model-predicted entries. Empty legacy evidence snapshot does not invent pose measurements; actual blade result is separately versioned in metrics.
- New `blade_ui.py`: saved-library Model-only blade rate link; later-reference-time selector; click/keyboard/numeric blade-point controls; explicit same-boat attestation. No model request before confirmation. Missing config is explicit; permission/hash/CSRF/origin/size checks retained.
- `selection.py`: strict version3 blade_reference distinct from v1/v2 eight-person selections. Pose tracking explicitly refuses v3. `analysis_worker.py` dispatches v3 into model path within existing isolated worker; jobs.py remains unchanged. `library.py` adds --blade-model and routes selected imports into blade confirmation only when configured.
- Browser test is added to existing read-only Chrome workflow. No new write-enabled workflow, model download workflow, repository setting or schedule is created.

Test-only remote commit `10e19fd6be4dfad6dda986a3dea6efbb7962f4c3`; production checkpoint `1930ec90c27a26bea19c5bef07a3e56eccdbe8ca`. Integration and email are PENDING at this documentation checkpoint; only claim after confirmed tool results. Keep topic and never change main/default or force history.

### Observed tests, including failures

Before production: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s strokesense/tests -p test_blade_model.py -v` ran10 expected failures in0.007s: one missing-selection behavior and nine explicit missing-module/API assertions. These are not an observed live-model error or a reproduced accuracy failure. The ten passed after implementation. The dispatch contract was subsequently moved from jobs._default_analyze to analysis_worker.analyze_request without changing the no-fallback requirement; this refactor is not backdated TDD.

Before UI wiring, test_blade_web.py ran5 tests with4 expected route/control failures (404 instead of intended responses, absent library link); its already-working generated-media pipeline case is not labeled red. Final `-p 'test_blade*.py'` passed19 tests in1.825s. Four provider-contract tests were added after implementation and are recorded as coverage, not initial TDD.

Intermediate complete local `python strokesense/quality.py` passed561 executions in109.683s plus4legacy synthetic checks. Final expanded local suite ran565 executions in148.677s with ONE ERROR: an existing malformed-coaching-input CLI subprocess exceeded its20-second timeout. No timeout/assertion weakening or warning suppression was applied. The final local full result is NOT green. Exact-tree remote offline/browser results must be recorded in106 after completion, not inferred from these targeted passes. Counts include existing repeated fixture discovery, not unique tests. Local diff whitespace check passed.

A generated120-frame video plus explicit model double produced30SPM, six entries/five cycles, pictures, private finite metrics and no technique scores. Those are synthetic model states, not live model output. Local Chromium navigation was ERR_BLOCKED_BY_ADMINISTRATOR; no bypass attempted. The added native Chrome harness tests reference selection/keyboard/attestation/HTTP303 at320/390/1280px with fake analyzer; remote status pending at this checkpoint.

### Real footage and remaining blockers

Actual provided private MP4 decoded75 samples from0.0 through7.4source seconds, source30fps/stride3, in3.748seconds. This was real video decoding, NOT inference or contact recognition. No private frame, source path, identifying metadata or credential was published. A real read-only attempt to contact local Ollama returned local_model_unavailable; no live model executed here. Local ONNX Runtime/model are also absent, unrelated to the new Ollama path. Existing public-video post-pose predictions cannot evaluate a new blade-contact model and were not relabeled fresh accuracy evidence.

Generic vision models may confidently misread blade immersion, identity or splash. Short-window overlap agreement cannot guarantee correctness or reject all repeated hallucinations. Small distant blades and occlusion can make the result unavailable or wrong. The app marks experimental model-inferred results, not independently verified events. There is no learned rowing-specific checkpoint or labeled benchmark in this increment. The user still needs an installed local vision runtime/model; CPU execution may be slow and bounded requests can time out. Model names in docs are API examples, not validated accuracy recommendations.

No fresh public-video inference, real per-event precision/recall, catch timing error, identity accuracy, live coaching provider, coach approval, customer KPI, Windows execution or large accuracy gain is claimed. Human test/team review remains pending. This task improves the architecture's evidence target, not demonstrably the model's accuracy. Issue106 remains open for live validation;103 remains open for broader detection/tracking quality.

### Evidence, operator guide and next action

[strokesense/BLADE_MODEL.md](strokesense/BLADE_MODEL.md) documents launch, limits, prerequisites and official API sources. New mode is one-blade entry timing only; arithmetic is external to the model and no body-rule fallback is allowed. Existing data/reports preserved; no re-upload necessary. Keep accurate permission metadata.

Activity2 story/criteria and Activity3 observed test-first checks are in106. Proposal criteria1/3/4/8 gain a local rate-only workflow; model configuration/interfaces do not prove the remaining live/customer/coach criteria. No hidden AI-checker directive observed; legitimate hidden form fields are not instructions. Communication remains pending until one deduplicated authorized update is confirmed. Do not store private recipient/scheduling identifiers here.

Explicit next action: run a locally installed vision model on a permitted recording with manually labeled entries for ONE blade, inspect every before/after image pair, and measure entry precision/recall, timing error, SPM error and unavailable coverage before claiming superiority to the body-motion baseline.
