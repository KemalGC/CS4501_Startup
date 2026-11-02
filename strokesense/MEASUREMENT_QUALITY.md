# Evidence-grounded SPM and curves

Update the integration branch `dev/strokesense-2026-10-26` after confirmed publication, stop the old server, and run from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

Open a fresh `http://127.0.0.1:8766/library` tab. Choose rowers on an existing permitted clip and run a NEW analysis. Do not delete the registry, footage, or old results. The startup banner is unchanged. The new base-detector cache version intentionally recomputes old detections, so the first rerun can still take time. Git refuses conflicting local edits: preserve them rather than resetting.

## What changes in new reports

Observations, short-gap estimates and unavailable points are distinct. A fixed anatomical side is used rather than swapping individual far-side joints into a chain. Only enclosed gaps at most0.20s can be estimated; long gaps and edges are not extrapolated. The same canonical joint/angle signals are used by plots and scoring. Projected trunk angle is not detrended as presumed camera motion.

Negligible periodic jitter no longer qualifies merely because normalization expands it. Motion amplitude, noise, reliability, periodicity and observed-cycle checks apply before stroke analysis. Missing limb evidence suppresses dependent curves/phase findings. These thresholds are conservative engineering choices, not empirically validated measurement guarantees.

Shared crew cadence requires overlapping catch intervals supported by distinct multi-cycle rowers. Raw rates are retained. Shared boat cycles and rower-cycle contributions are separate counts. Five complete consecutive cycles require six catch events; the five-cycle estimate is300 divided by elapsed source seconds. A five-cycle sample is sufficient for the existing short-summary policy, not proof of coaching accuracy. The method confirms already detected events; it does not fabricate a missing peak to force rowers to match.

The shared-cycle table shows source times and supporting rowers. Body-angle plots show observed samples, short-gap estimates, catch/finish markers and source-video time. Sequencing plots show qualifying individual cycles, median, interquartile spread and contributing counts per signal; unsupported or negligible-motion curves are unavailable. Metrics JSON saves versioned measurement policy, joint observation counts, shared-event intervals and sequencing summaries. Old reports remain unchanged until regenerated.

Base detector merging now uses confident torso landmarks before box-overlap suppression can discard separate overlapping rowers. This is not a new trained detector or guaranteed identity tracking. Existing conservative crew confirmation/association protections remain.

## Verification and unresolved work

Run from repository root:

```text
python -m unittest discover -s strokesense/tests -p test_measurement_quality.py -v
python -m unittest discover -s strokesense/tests -p test_measurement_pipeline.py -v
python strokesense/quality.py
python strokesense/quality.py --doctor
```

Tests include false tiny-motion strokes, observed-versus-estimated masks, side consistency, physical-angle preservation, early overlapping-person suppression, canonical chart/scoring equality, finite JSON, renderer missing joints and time-overlapping crew cadence. Synthetic tests are not real-video accuracy measurements. The local Python3.13 full suite still has a previously observed SQLite ResourceWarning-related old-test failure; Python3.11 CI verification is recorded in105. Doctor is read-only diagnostics, not inference.

This increment does not implement full appearance-based re-identification, camera-motion calibration, true boat-relative handle travel or independent labeled real-video evaluation. Hip-relative handle motion is still a proxy. No claim is made that every wrong SPM/curve in the user's unavailable localhost report is now accurate. Issue103 remains open: label a longer recording's identities, visibility, catches and finishes, then quantify error before promising improved accuracy. Coach/test review and Windows validation remain pending.
