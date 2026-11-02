# Two-entry quick rate (default model-only mode)

Two clear water entries of the SAME blade define one complete interval: `SPM = 60 / (second entry time - first entry time)`. That is enough for a **provisional** rate. It does not require five cycles, and it does not mean that two still images alone establish contact or identity. Short sequences around both entries are still inspected.

## Use it

Stop the previous StrokeSense process, update `dev/strokesense-2026-10-26` without discarding local changes, and launch from the outer `strokesense` directory with your already installed local vision model:

```powershell
$env:STROKESENSE_BLADE_TARGET_CYCLES = "1"
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766 --blade-model qwen3-vl:4b
```

The model name above is an existing API example, not a newly validated rowing-model recommendation. Ollama must already be running locally with that model installed. Keep its cloud features disabled as described in BLADE_MODEL.md. No model is automatically downloaded or substituted.

Open a fresh `http://127.0.0.1:8766/library` and use **Model-only blade rate (experimental)** on your saved permitted clip. This speed change does not apply to **Choose rowers**, the separate legacy pose mode. Pick a clear reference frame before the entries you want and click the blade itself. Confirm its boat and analyze. No deletion/re-upload needed. Existing reports do not change; start a new analysis. The startup banner is unchanged; new reports include **Quick rate processing** and **Model-predicted blade position**.

## What stops early

Sampling starts at the selected reference rather than five seconds before it. Source frames are decoded lazily at approximately10fps with their original timestamps; the prior1280px maximum input width is retained. It processes24-frame windows with4overlapping samples, then stops when a full interval is supported outside the still-unresolved tail. It does not intentionally scan the rest of20seconds after obtaining a rate. Uncertainty can still require more windows or yield no estimate.

To explicitly request more averaging, set `STROKESENSE_BLADE_TARGET_CYCLES` to an integer from1 through5 before launching. This means complete intervals, requiring one more entry than intervals. More samples may reduce timing variability but cannot guarantee that a model recognized the correct blade.

Requests remain sequential to avoid multiple large vision-model executions competing for memory. Ollama is asked to retain the model for10minutes between calls. The report/metrics record actual request counts, sampled frames and measured durations. Backend load/prompt/generation durations are saved when returned. No claim of GPU acceleration or real-model wall-clock speedup is made by this update.

## Position and contact checks

Visible classifications must carry a finite normalized box around the blade face, not the handle, rower, splash or whole scene. The first predicted position must agree with the clicked reference point, allowing1% image tolerance. A mismatch yields **reference_unconfirmed** and no rate; choose a clearer reference rather than accepting a different oar.

Disagreement in overlapping frames' contact/identity, or box centers differing by more than5% of image dimensions, produces unknown observations. Single-sample contact runs also become unknown instead of creating extra catches. Long gaps, uncertain identities and missing blades are not bridged. These thresholds are conservative engineering safeguards requiring real-video calibration, not labeled accuracy evidence.

Before/after entry pictures show model-predicted boxes. The boxes themselves remain unverified predictions. **This is blade localization, not improved body positioning, body angles, or technique grading.** The model-only path does not run the old body-curve peak finder or heuristic fault rules. Those requested posture improvements remain separate work.

## Verification and limits

A controlled20second generated-video/model-double comparison used10 requests/246 images/200 source samples in the old fixed window and2 requests/50 images/44 samples in quick mode. Both produced the constructed30SPM, but quick mode used one interval instead of nine. This establishes reduced work in that test, not empirical Qwen speed or accuracy. The new localization output adds tokens per request. Hardware/model choice, contact uncertainty and a CPU-only runtime may still be slow.

Tests cover initial mismatch, required boxes, finite values, overlap disagreements, transient contact flicker, source timestamps, early stopping, longer optional targets and no heuristic fallback. Real source-video decoding and a real isolated-worker/HTTP report path were tested with an explicitly fake model server. A live vision model was unavailable in the implementation environment. Do not describe these fixtures as measured rowing accuracy. Human/Windows review and real model/event/position benchmarking remain pending under issues103/106.

Run from repository root:

```text
python -m unittest discover -s strokesense/tests -p test_blade_quick.py -v
python -m unittest discover -s strokesense/tests -p "test_blade*.py" -v
python strokesense/quality.py
```

Official API contract references:
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/capabilities/structured-outputs

API structure and data validation do not prove visual correctness. Review the entry pictures and manually count a reference interval before trusting an estimate.
