# Resilient results and qualified crew cadence

## Update and run

Stop the old server, update `dev/strokesense-2026-10-26`, and start from the outer strokesense directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

Open a fresh `http://127.0.0.1:8766/library` page. Use the saved permitted recording; no deletion or re-upload is needed. A server restart marks interrupted jobs failed. Use **Retry analysis** on a retryable failed job or **Choose rowers** to create a new analysis. Old reports are not rewritten. The existing startup banner is unchanged by this increment.

## Server and optional video output

Production analysis runs in a separate process using the same virtual environment. A child native exit or timeout can fail the job without terminating the HTTP server. The page uses the existing analysis_failed/retry contract; PowerShell prints a child exit code. Keep the server window open. The default upper limit is one hour per production analysis; external encoding is bounded to120 seconds. Closing PowerShell, system-wide resource exhaustion and faults in other server/preview code are not solved by child isolation.

The renderer no longer tries the unchecked OpenCV VP80/WebM fallback. It uses an existing local FFmpeg executable with libx264 support, checks its exit and decodable output, and only then publishes the MP4. It checks PATH first and can use an already installed imageio_ffmpeg executable. No automatic installer or package replacement is performed.

When the encoder is missing or raises a catchable rendering failure, the application keeps report/metrics generation and explicitly says **Annotated video unavailable**. It does not advertise a nonexistent video. A hard native child crash instead leaves a failed job; partial reports are not automatically salvaged. Previous output is not overwritten by a failed encode. Temporary intermediate data can remain for local diagnosis.

The reported VP80 tag warning alone did not establish the original Windows server-exit cause. The uploaded video encoded correctly as H.264 in the implementation Linux environment, but Windows/native pose execution was not reproduced.

## Crew cadence is not eight forced equal numbers

Raw per-rower stroke rates remain unchanged. The report, console and video HUD can show an **estimated shared crew cadence** supported by several rowers, including how many rowers and cycles support it.

Each supporting rower needs at least two valid cycles with bounded variability. For an eight-person crew at least three eligible rowers must agree, and the supporting set must be a strict majority of eligible rowers. Agreement is within max(2spm,10% of the candidate centre). The shared rate is the median of supporting per-rower medians. Singles/doubles and insufficient agreement retain explicit unavailable states where needed.

A45spm estimate from one cycle among several33–35spm multi-cycle estimates is labeled **Unconfirmed: fewer than 2 cycles**. It is not silently changed to34. Repeated outliers are labeled inconsistent with the crew estimate. Zero-cycle rowers are not assigned invented rates. Raw rates and qualifications remain available for inspection.

This is a heuristic agreement estimate, not proof of synchronized catch timing, corrected peak detection or an accuracy score. Rate changes and different visible intervals can produce genuine differences. Use the existing catch-timing evidence and coach review for timing assessment; do not force measurements to match expectations.

## Reproducible checks and limits

From repository root:

```text
python -m unittest discover -s strokesense/tests -p test_resilient_results.py -v
python -m unittest discover -s strokesense/tests -p test_result_pipeline.py -v
python strokesense/quality.py
python strokesense/quality.py --doctor
```

Tests use real child processes for abrupt-exit/timeout behavior and synthetic detections for report/rate cases. Actual source-video encoding was tested separately without rower overlays. Full exact-tree CI passed on Python3.11. The local Python3.13 full suite exposed a pre-existing fixture connection-cleanup warning entering a stderr-only assertion; it was disclosed, not suppressed. Windows/Python3.14, real-model cadence accuracy and human/coach review remain unverified.
