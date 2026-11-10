# Active overnight accuracy work

User scope: continue until they return; improve tracking, accurate body motion
for standard unobscured rowing, and rowing-analysis precision. Preserve the app's
offering/UI and all pre-existing workspace changes. Goal remains active.

Completed batches:

1. Ordered rowing-seat tracker and anatomical duplicate suppression.
   `tracking/README.md`: coverage 90.2% → 96.0%; small assistant identity audit
   141/160 → 153/160 correct; wrong-seat associations 3 → 0.
2. Confidence-weighted hip-relative body conditioning; fixed body-side selection
   excludes ankles; conservative isolated-jump rejection with explicit provenance.
   `body_motion/README.md`: controlled noisy-motion error improves, clean motion
   unchanged; no independent real-video joint accuracy claim.
3. Fractional catch/finish clock consistently measures rate and drive/recovery
   durations. Integer evidence indices remain. `stroke_timing/README.md`.
4. Missing-aware rhythm calculation retains actual sample timing, observed-pair
   support, and finite-input behavior. Generic single-rower selection shares the
   same policy. `rhythm/README.md`.

Validation:

- Latest full suite: 784 tests, same ten existing application failures and one
  existing cold-model preview timeout; no additional failures. The four legacy
  synthetic analysis/fault checks also pass.
- Before rhythm changes, 82 focused tracking/body/timing/evidence tests passed;
  rhythm adds seven passing regressions.
- Original failure categories were reproduced against the original tracker.
  Do not alter unrelated UI/product code to hide baseline failures.

Experiments completed:

- `body_motion/detector_sequences.py`: nano/small/medium ONNX, same fixed crops,
  two 20-second source windows. Six sequence pose caches are under
  `results/body-motion-evaluation/detector-candidates/`, with SHA-256 ledger.
  Original diagnostic results are preserved in `backbone_sequence_results.json`.
  IMPORTANT: original subprocess used body v1 but predated fractional timing and
  source-time rhythm changes. Replaying caches now uses the newer measurement
  code; cached load time must not be presented as extraction speed.
- The medium model gave a small coverage increase but roughly 5× CPU time. Six
  approximate assistant arm-joint annotations do not establish better joint
  accuracy; their uncertainty exceeds most model differences. Default nano model
  is unchanged. Official candidate weights stay in ignored `models/`.
- Decoded timestamps on all three videos differ from the nominal clock by <1.6 ms.
  Do not prioritize a cross-cutting source-clock rewrite without stronger need.

Next work:

- Improve actual stroke-event selection on noisy signals, with source-frame
  review to distinguish missed/extra events. See
  `results/body-motion-evaluation/9673-cycle-diagnostics.png`.
- Wrist estimates can alternate between plausible and incorrect locations even
  in clear footage. Smoothing cannot disambiguate these. Larger backbones alone
  did not show a convincing win. Investigate targeted pose refinement and
  confidence/identity consistency, with paired real-frame evidence.
- Strengthen the small localization/event audits; they are not independent human
  labels or held-out validation. Avoid optimizing solely for more cycles or
  smoother curves. Preserve real rate changes and individual timing offsets.

No footage upload, no neural fine-tuning, and no independent human ground truth.
The app's offering/UI and existing technique thresholds remain unchanged.

Latest batch: crew synchrony

- Replaced reference-rower nearest catches with majority-supported, one-use event
  association. Preserves disconnected accepted-cycle endpoints, rejects duplicate
  identities/seats, and clears stale rower offsets. Nine focused regressions pass.
- `synchrony/README.md` and `results.json` document fixed-track comparisons. One
  short segment now abstains (only one majority-supported catch). Changed offset
  magnitudes are not independent accuracy evidence.
- Full suite: 792 tests with the same ten pre-existing application failures; no
  new failures. Prior intermittent preview timeout did not recur. Ninth synchrony
  test added subsequently, focused run passes all nine.
- Targeted pose crops at three padding levels did not consistently improve six
  approximate assistant arm annotations: base 4.30 px, crops 5.38/5.33/4.40 px.
  These uncertain labels do not justify adopting crop refinement. Private evidence:
  `results/body-motion-evaluation/crop-refinement/`.

Next evidence from source-frame event audit:

- `evaluation/events/review.py` generates source-pixel contact sheets and frame
  ledger. In IMG_9673 leftmost rower cycle 100–139, current mixed-cue finish at
  frame 125 is visibly already in recovery. Hand minimum is frame 112 (0.877 s
  earlier), near arm draw, though exact reversal remains uncertain in blur.
- This suggests phase-specific cue choice: knee extension has a long plateau
  and knee noise should not dominate hand-reversal timing. Audit neighboring
  disagreements and test a supported hand-based finish candidate before adoption.
- No production phase changes in this batch; evidence and hypothesis recorded
  in `events/README.md`. Avoid claiming hand minima are exact blade events.

Adopted phase-specific finish selection:

- Supported hand reversal now determines finish when existing local evidence
  gates and observed neighboring samples pass. Catch selection is unchanged;
  unsupported hand evidence retains the previous mixed cue. Fractional finish
  timing uses the selected signal. Version `supported-hand-finish-v1`.
- Real source review confirmed the prior frame-125 finish was in recovery;
  candidate selects frame 112 near arm draw. Three additional large-disagreement
  cycles support separating knee and hand phase cues, while exposing uncertainty
  from flat/blurred hand motion. No exact real-video timing accuracy claim.
- `evaluation/events/` holds frozen baseline/candidate, paired five-segment event
  comparisons, source-sheet generation, and rationale. Three analytic tests pass.
- Full suite: 796 tests, same ten existing application failures, no new failures.
  All four standalone legacy rowing/fault checks pass.

Fresh integrated verification:

- Current CLI rerun on 20 seconds of IMG_9673 with fresh inference, eight-seat
  tracking, all revised measurements, annotated video, snapshots and reports.
  Completed successfully in 32 seconds with the configured ONNX providers.
- Eight rowers, 36 accepted cycles, six supported crew events; estimated cadence
  22.465 spm. Counts/rate are diagnostics, not independent accuracy labels.
- `evaluation/pipeline/verify.py` passes saved fractional-clock arithmetic,
  provenance counts, one-use majority events, and evidence graph/digest checks.
  See its README/results.json and private `results/final-pipeline-evaluation/`.

Offline temporal pose consensus experiment:

- Warped four neighboring-frame nano predictions to each target frame with
  bidirectional Lucas–Kanade flow; used identity, confidence and flow gates.
- Six approximate assistant arm cases show no overall improvement (4.2992 →
  4.2998 px). Wrist mean worsens 4.5444 → 5.1294 px; one clear case worsens despite
  all five flow estimates passing. These labels remain uncertain/non-independent.
- Not adopted. `evaluation/body_motion/temporal_flow.py` reproduces it; private
  vote arrays, images, and results are in `results/body-motion-evaluation/temporal-flow/`.
  Temporal agreement does not resolve repeated anatomical localization bias.

Mirror inference and angle geometry:

- Offline mirrored-frame nano inference with proper anatomical side remapping
  does not improve the six-case approximate arm audit: baseline 4.299 px,
  mirrored 5.594 px, average 4.729 px. Not adopted into production.
- Corrected undefined projected angles: coincident/nonfinite endpoints now
  return unavailable measurements rather than fabricated 90°/0° values.
  Unit-vector normalization preserves angles across coordinate scales; a
  collapsed torso cannot support a stroke. Four new analytic regressions pass.
- Five-cache scan contains no exact coincident smoothed limb segments, so this
  is a validity safeguard, not an asserted real-footage accuracy improvement.
  All four standalone legacy rowing-analysis tests still pass.
- Full suite after geometry correction: 800 tests, the same ten pre-existing
  application failures, no new failures. Log in private body-motion results.

Full-source-frame experiment:

- Fresh 20-second IMG_9673 CLI at 29.645 fps compared with 14.823 fps. Every one
  of the 296 common frames has exactly identical detection boxes/keypoints.
- Full run: 34 cycles, six supported events, estimated 22.077 spm, 72 seconds;
  half run: 36 cycles, six events, 22.465 spm, 32 seconds. Full output passes
  measurement/provenance verifier. Counts and agreement are not accuracy labels.
- Some nearest-matched catches/finishes shift by ~0.24/~0.32 seconds. Same minimum
  five-frame smoothing window spans different durations at the two frame rates.
  Isolate time support versus observation density in a subsequent controlled
  experiment; no default sampling change. `evaluation/sampling/` holds details.

Controlled sampling/filter separation:

- `evaluation/sampling/filter_support.py` tests known 20/32/40 spm motion with
  white and correlated noise, holding production settings unchanged. Wider
  full-rate smoothing reduces 3 px white-noise elbow RMSE 8.205° → 6.198°, but
  worsens clean RMSE 0.131° → 0.845° and barely helps correlated errors
  (11.865° → 11.476°). Complete diagnostic results are retained.
- Real full-rate replay changes accepted cycles 34 → 35, not an accuracy label.
  Uniform time-support matching is not adopted: it would discard clean temporal
  detail without resolving persistent pose-localization errors. Future real-frame
  validation should broaden beyond the small existing arm/event audit.

Expanded source-frame phase audit:

- Added four large finish disagreements from IMG_9674 via
  `evaluation/events/review_additional.py`, retaining source ledgers and joint
  confidence/angle traces. One obvious recovery-as-finish error is corrected
  on this second video. Other cases have long drawn-in poses or partial overlap;
  exact timing cannot be certified visually.
- One revised finish still appears slightly early. Hip-relative reach minimum
  precedes shoulder-relative reach/elbow minima by one sampled frame, alongside
  large high-confidence trunk-angle fluctuations. Investigate hip/torso
  localization rather than assuming all remaining event errors are wrist jitter.
- No additional production heuristic adopted from this selected, non-independent
  review. Source images and traces remain private under event-evaluation/additional.

Concrete torso-localization mechanism found:

- Both sides fluctuate, so bilateral averaging does not solve the audited case.
- Matching source/model hashes verified. Replays separate CPU/configured provider
  and 20/21-second auto-crop grids. At frames 212–213, a crop truncated at x=418
  gets a slightly higher person score than a complete crop; its torso estimate
  differs by ~17–20 degrees and has lower torso confidence. Current score-only
  duplicate ordering can therefore prefer an anatomically weaker partial pose.
- `torso_candidates.py`, `torso_replay.py`, and body-motion README record concrete
  scores/bounds and the mechanism. Next candidate: crop-edge-aware same-person
  duplicate preference, preserving partial-only detections and overlapping people.
  No new production suppression rule in this batch.

Adopted crop-boundary-aware duplicate preference:

- Complete same-person alternatives can replace truncated winners only with
  substantial torso-confidence improvement and comparable person score. Partial
  detections remain usable without a qualifying alternative; source-image edges
  are not treated as crop truncation; no joint fusion.
- Shared postprocessing version bumped to `torso-landmarks-v4-crop-edges`, so
  base/refined caches invalidate. Eight new targeted tests, six existing merge
  tests and updated cache-identity test pass. Full suite: 808 tests, same ten
  pre-existing application failures; four standalone rowing checks pass.
- Identical-proposal replay corrects the two audited torso failures, preserving
  detection counts in all twelve frames and leaving six existing arm cases
  unchanged. Source overlay confirms removal of crop-edge hip/knee collapse.
  This is a selected failure correction, not an independent general accuracy rate.
- Fresh configured-provider 21-second IMG_9674 run completed in 33 seconds with
  v4 recorded in cache identity: eight rowers, 54 accepted cycles, nine supported
  crew events, estimated cadence 25.074 spm. Saved numerical/provenance checks
  pass. These counts/rate are diagnostics, not independent ground truth.
  Outputs and verifier results remain private in `results/crop-edge-pipeline/`.

Commit preparation:

- The isolated staged application snapshot ran 794 tests with the same ten known
  failures and no new failures. It excludes unrelated pre-existing upload/job/UI
  changes and their additional tests; the earlier full workspace ran 808 tests.
- The delivered six-page PDF and its generation source are preserved in
  `evaluation/reports/`. Model weights, raw footage and runtime intermediates are
  excluded from version control.
