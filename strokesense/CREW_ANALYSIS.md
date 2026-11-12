# Selectable model review for eight rowers

## Launch and choose tasks

Update `dev/strokesense-2026-10-26` after confirmed publication. Stop the old server. With Ollama running locally and a vision model already installed, run from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766 --crew-model qwen3-vl:4b
```

The model name is an integration example, not a validated rowing recommendation. Use a trustworthy local-only Ollama server; set `OLLAMA_NO_CLOUD=1` on that server before starting it. StrokeSense does not automatically install/pull models, use cloud models or paid APIs. CPU model calls can be slow or time out.

Open a fresh `http://127.0.0.1:8766/library` and click **Choose crew analyses** on a permission-granted saved recording. This is separate from old **Choose rowers** and **Model-only blade rate** routes. Select a clear reference timestamp, mark the centers of eight rowers' torsos from ONE boat, exclude the coxswain/background crew, confirm and submit. Coordinates provide a keyboard alternative; Undo/Clear allow corrections. R1..R8 mean selection order, not official bow/stroke-seat numbers.

Choose any nonempty combination:

- **Body positions**: model-described torso, arms and knees at three source times near the reference. One shared request for all eight. These are visible-configuration categories, not validated joint angles or good/bad technique grades.
- **Stroke rate**: each rower's associated blade must have two supported entries (one provisional interval). Rate is calculated from source time; eight oars are not added together. Missing or confused blade associations stay unavailable.
- **Crew catch timing**: model-inferred entry differences from the group median where overlapping supported events exist. Sampling uncertainty can exceed apparent timing differences; this is not coach-validated synchronization.

Unselected tasks are absent from requests and report sections. Every selected ID remains in the report, including unavailable rowers. Position-only avoids scanning for blade events. Rate/timing use additional shared frame batches and bounded early stopping. No heuristic pose/technique fallback runs in this mode. Existing reports remain unchanged until a new analysis; no deletion/re-upload required.

## What is tested

Software tests cover strict task/identity schemas, all-eight retention, background-reference mismatch, unknown members, duplicate boxes, invalid times/coordinates, wrong IDs, no old fallback, synthetic two-entry rate, only-position work, actual local form requests and native browser controls. The final local suite passed599 executions plus4legacy synthetic checks. These establish program behavior, NOT real visual accuracy.

The real Qwen3-VL test on licensed public footage did NOT establish eight-person success. Official Ollama0.40.13 with qwen3-vl:4b loaded, but a simple marked-reference localization image request timed out after150.10seconds without predictions on the GitHub CPU runner. Source/model provenance and blocker are saved in `evaluation/crew-model-attempt.json`. The earlier Ollama0.12.6 attempt failed compatibility before inference. A successful workflow only meant the blocker was saved. No claim of real eight-rower rate, posture or tracking accuracy is supported by this experiment.

Your private uploaded clip was visually inspected and decoded locally, not uploaded for remote model inference. Its opening view contains eight distinct foreground rowers plus another crew; no whole-video quality excuse is being asserted. The supplied Windows localhost reports remain inaccessible from this environment. Windows/live-model/private-recording accuracy and runtime remain unverified.

## Reproducible local localization check

`python -m strokesense.crew_evaluation --video PATH --labels LABELS.json --model MODEL --output RESULT.json --permission-confirmed`

Labels contain `source_sha256`, `label_provenance`, the version4 `selection` with `analyses:["position"]`, and one to six `frames`. Each frame has source `seconds` and exactly eight normalized full-body `boxes` (null when not visible), ordered by selected ID. Mark boxes independently of model predictions. Keep private labels/media out of public GitHub. Source hash must match.

The command runs the actual model and reports per-rower visibility/localization IoU against those supplied labels. Exit0 means every specified box passed IoU>=0.5 or correct absence, not general model accuracy; exit1 means a label failed; exit2 means blocked. It does not validate posture labels, contact events or SPM. Those require separate human-reviewed event/pose labels and recording/session-separated test sets. Do not use model predictions as their own ground truth.

## Limits and next work

Generic vision models can confuse identities and blade associations. Initial point matching, duplicate suppression and overlap checks are not appearance re-identification. Fixed-reference windows may still switch identities. Categorical posture output can be wrong even with correct boxes. Never interpret coverage as precision/recall, or a schema-compliant response as proven perception. Use the embedded position frames to inspect predictions, not to declare automatic approval.

Issues108/103/106 stay open for real quality validation. Next: resolve model latency and run a compatible model on independently labeled same-boat frames and catches, measuring each rower's error/coverage, not just successful HTML generation.
