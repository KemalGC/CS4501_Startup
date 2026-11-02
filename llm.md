# StrokeSense current handoff

Previous root contents are preserved byte-for-byte in [llm-history-2026-11-02-fast-rate.md](llm-history-2026-11-02-fast-rate.md), original blob452d7c96cb65bf71f93e22a3ef4b5461ccae42ef. Earlier history remains linked and unchanged. Manual Nov2 work does not resume the expired October sprint or alter schedules.

## 2026-11-02-1400-manual — selectable eight-rower model review (#108)

### Request, scope and measured checkpoint

User wants independently selectable analyses and rigorous evidence that the model works for all eight rowers, not another one-blade-only feature. Start2026-11-02T14:00:40.052526-05:00, monotonic31.046816079. Verification checkpoint2026-11-02T14:21:41.126512-05:00; measured1261.074seconds (21m01.074s), excludes later docs/publication/email. Final duration must be recorded separately. Continue topic dev/2026-11-02-1400-crew-analysis-options from integration001d13bf35bac55f16940ca5e676477f5e7edac0. Main inspected3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc. Same-day heads inspected; no unrelated concurrent head was overwritten. Issue108 created before production. No main/default/settings/automation/schedule/PR/branch-delete or private-media publication.

### Implemented story and acceptance

As a coach, I want to select body-position review, per-rower blade-entry rate and catch-timing comparison for my confirmed eight, so unselected tasks do not consume model requests and unavailable people remain visible in results.

`crew_ui.py` adds /crew and independent task checkboxes, a later-reference selector, eight torso points, undo/clear, numeric keyboard alternatives and explicit same-boat confirmation. Library exposes Choose crew analyses and --crew-model MODEL; existing --blade-model can supply the model name. No model request before submission; existing origin/CSRF/source-hash/permission/input limits remain. Legacy pose and one-blade workflows remain distinct and unchanged.

`selection.py` persists strict v4 crew_model references and allowlisted task choices; model-only selections are refused by pose tracking. `analysis_worker.py` dispatches v4 to `crew_model.py` inside the existing isolated process. There is NO old pose/body-curve/fault-rule fallback and no heuristic technique grade.

All eight selected IDs are required exactly once in every model frame, including missing/unknown people. Conditional output schema asks only for requested tasks. Reject extra fields, invented frame times, invalid/nonfinite body/blade boxes and reused duplicate boxes. Reference positions must match operator-selected torso points; mismatch leaves that ID unavailable instead of selecting the background crew. Overlap disagreement becomes unknown. These are consistency checks, not evidence that a model's visual answer is correct.

Position-only: one request containing three source frames around0/.5/1s, shared by all eight. Categorical visible torso/arms/knees are model predictions, NOT measured joint angles, technique judgments or proof of biomechanics. Temporal tasks: source-aligned approximately10fps, six-frame batches with two overlapping samples, maximum24 requests plus existing20second/320frame/40MiB sampling bounds. Rate uses two supported entries of each rower's associated blade. Catch timing compares supported events and labels sampling uncertainty. All eight results remain even if seven succeed and the eighth is unavailable; full-crew early completion requires each requested rower's evidence. Actual frame/image/request/time counters are stored, not a promised speedup. Generic vision output may still confuse blade-to-rower association or later identity.

Private per-run metrics retain selected tasks/IDs, source/model/frame hashes, model observations, source times and all-eight coverage. A zero-rower legacy evidence snapshot does not label model predictions as verified technique. Report has eight explicit cards, requested-only sections and three model-position evidence images. No private footage, coordinates tied to the user's clip, or identifying metadata are stored in GitHub.

`crew_evaluation.py` provides a real local model evaluation command against a matching source hash and supplied eight-person boxes across up to six frames. Per-rower IoU>=0.5 and visibility outcomes use explicit denominators. Exit0 only means passed those supplied labels; exit1 failed labels; exit2 blocked. This checks localization/identity only, not posture categories, blade contact or SPM. No independent labeled benchmark was completed in this session.

### Tests-first and verification

Remote test-only3eb2947f7117fb0a74fa43a7f453c83a58561643 precedes production9e25c58a6138a54aaadaa00b9ce913d2f34c07e6. Locally, `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s strokesense/tests -p test_crew_model.py -v` produced10 expected failures before production: one unsupported-selection behavior and nine explicit missing-module/API assertions, not real-model or import failures. All ten passed afterward.

Route tests before integration produced3 expected missing-route/control failures among9 executions; imported fixture tests already passing are not mislabeled TDD. Five pipeline tests were additional post-implementation coverage. Final `-p 'test_crew*.py'` passed24 executions in0.880s, including5 imported fixture cases (19 new unique test methods). They cover unselected work omission, all-eight identity persistence, missing eighth, duplicate/foreign IDs, nonfinite/duplicate boxes, wrong reference crew, no old fallback, two-entry per-rower rates and request integrity. Synthetic body/contact outputs are test doubles, not visual truth.

Final full local `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python strokesense/quality.py`:599 executions passed in59.636s plus4 legacy synthetic functions. Earlier594/55.100s also passed. Counts include repeated fixture discovery, not599 unique cases. No warning suppression or weakened accuracy assertion. Whitespace diff checks passed. Production exact-tree offline CI41508708618 and native Chrome41508708652 completed success. Native browser selects only position, marks eight via coordinate controls, checks confirmation reset/empty-task refusal and HTTP303/persisted tasks at320/390/1280px with a fake analyzer. Local browser was ERR_BLOCKED_BY_ADMINISTRATOR and was not bypassed.

Downloaded exact production CI archive and byte-compared all6 modified/new production modules,4 new test/browser files and browser workflow to the locally tested files; all matched. Docs/integration/communication are PENDING at this handoff commit; issue108 will record only confirmed publication/email results.

### Actual video and actual-model test — NOT a success claim

Locally inspected the supplied private clip's opening and later sampled frames. Eight foreground rowers were visibly distinct and there was a separate background crew. This is direct visual inspection, not successful machine tracking, and no claim that the entire video is unusable was made. Source decoding works. Private footage stayed local. Local Ollama/model are unavailable; no private recording was sent to GitHub or a remote vision service.

A separate bounded read-only GitHub CPU experiment used Splash tv's CC BY-SA4.0 public Rowing boat racing 8-man + cox footage. Reference frame99 and eight previously visually selected torso points were used for a basic same-frame localization check, NOT a temporal/rate/posture benchmark. Runtime/model installation was explicit only in this experiment, not inside app page requests.

First run41507548607 failed before inference: checksum-verified official Ollama0.12.6 could not pull the current model (HTTP412/newer-runtime requirement). That is a compatibility failure, not a detection failure. Retry41507990363 used checksum-verified official Ollama0.40.13 and installed actual qwen3-vl:4b, digest a1b29c246319cdcb1f3842f36d29f198f737c0cf516ba1bcba34b1b974e87980, Q4_K_M, 3336619180bytes. Its real image request TIMED OUT after150.101775368seconds without returned predictions. The workflow completed because it saved the blocker; a green workflow is NOT a passed model evaluation. Zero accuracy metrics are available from that attempt. Artifact13170934663 contains manifest/server log/attribution, no successful model response. The simplified check did not run the full new crew classifier, and would not validate all requested analyses even had it succeeded.

The temporary live-check workflow is removed from the final tree to prevent accidental heavyweight repeated downloads. Reproducible experiment remains in commit9259493fe89fc958cc16058e9fb0c8553cc4c7f6 and run41507990363; the bounded local evaluator remains in code. No model was changed or advertised as better based on this timeout. Summary is saved in strokesense/evaluation/crew-model-attempt.json.

### Remaining gaps and next action

This delivers selectable all-eight processing/contracts, NOT evidence that Qwen reliably analyzes all eight. Detection/identity accuracy, blade-entry precision/recall, SPM error, categorical posture correctness, Windows speed, calibrated uncertainty and coach validation remain unmeasured. Generic-model identity/contact predictions can be wrong despite valid JSON and repeated agreement. Do not claim substantial accuracy improvement or that passing599 tests proves model vision. Issues108,103,106 remain OPEN for their real-model validation requirements. Human team/test review remains pending.

Guide: strokesense/CREW_ANALYSIS.md. Stop old process, safely update development integration after confirmed publication, launch `python -m strokesense.library --port 8766 --crew-model qwen3-vl:4b` with an installed local model, then /library -> Choose crew analyses. Select tasks, mark eight same-boat torso centers, confirm and run a NEW analysis. Old reports preserved; no re-upload/deletion. Start with position-only to avoid unnecessary temporal processing, but no completion-time/accuracy promise.

Activity2 issue/story/acceptance and Activity3 observed failure/pass records retained. Proposal criteria1/3/4/8 gain a selectable review flow; live/coach/customer criteria remain unproven. No substitution for Activity1 customer validation or unseen rubric claims. No suspicious hidden AI-checker directive observed in inspected source; normal hidden CSRF inputs are not instructions. No private recipient/scheduling identifiers in logs.

Explicit next action: benchmark a compatible local model on independently labeled same-boat frames and blade events with per-rower identity/localization, contact/time/SPM errors and runtime. First diagnose the observed real-model timeout rather than asking the user to trust unvalidated eight-person results. Communication pending until profile/dedup/send results are confirmed.
