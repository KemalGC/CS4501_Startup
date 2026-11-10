# Fresh integrated pipeline verification

Ran the existing CLI with current tracking/body/phase/synchrony changes:

```
.venv/bin/python -m strokesense.cli ../../test-footage/IMG_9673.MP4 \
  --out results/final-pipeline-evaluation --duration 20 --crew-size 8 \
  --threads 4 --fresh
.venv/bin/python evaluation/pipeline/verify.py \
  results/final-pipeline-evaluation/IMG_9673--ebc59e58c20a888dfc7c/metrics.json
```

The run completed in 32 seconds on this machine's configured ONNX providers.
This is not directly comparable to the controlled CPU-only backbone experiment.
It generated fresh detections, tracks, annotated video, snapshots, HTML, and JSON.
All outputs remain private local artifacts under `results/`.

Saved metrics contain eight rowers, 36 accepted cycles, six majority-supported
crew events and a 22.465 spm boat estimate. These are diagnostics, not independently
verified counts/rates. `results.json` retains a digest of the inspected metrics.

The verifier checks fractional frame bounds and ordering, rate/duration identity,
observed plus missing cycle frames, mutually exclusive observation counts,
independent majority support, one-use crew events, and the evidence graph/digest.
Snapshot/window indices remain discrete source-frame references; fractional
measurements are in each stroke's timing fields. The existing evidence snapshot
also retains discrete finish/end references, separate from fractional durations.

This checks the combined inference-to-report path rather than only isolated
signals. It does not establish real-video landmark or technique-fault accuracy.
