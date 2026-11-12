# Eights-only evaluation and saved analysis library

The November 4 study uses seven selected clips of **eight-person crews only**.
Four-person boats and singles are excluded. Every clip follows one target eight;
camera pans to another crew are removed. The private package contains the
selection, original recording offsets, preview hashes, real saved model reports,
overlays, measurements and a manifest. It contains no participant answers.

## Evaluate what the footage supports

The technical form has ten judgments: crew/rower identity (including coxswain
exclusion), stroke rate, catch body angle, finish body angle, drive sequencing,
recovery sequencing, crew timing, evidence alignment, specific usable advice,
and handling uncertainty. Each accepts correct, partly correct, incorrect,
cannot judge, or no applicable output, plus an optional timestamp/correction.
Unavailable model output cannot receive a positive or negative correctness
judgment. Existing usefulness/accuracy ratings and five report-quality questions
remain available, with their existing revision history.

An optional manual rate observation stores one rower's description, consecutive
catch count, and first/last catch times. The server computes
`60 * (catch_count - 1) / (last_time - first_time)`. For example, six catches
across twelve seconds give five intervals and 25 SPM. These are reviewer
observations, not independently adjudicated ground truth. Do not infer
model accuracy from synthetic tests or counts of detected tracks alone.

Player and evidence timestamps start at zero for each trimmed clip. The catalog
records the original recording offset; add it to recover the original time.
Source previews are browser-friendly H.264; inference runs use higher-resolution
copies of the same selected window. Original uploaded recordings are retained.

## Open the review study locally

Extract `StrokeSense-Eights-Review.zip`. From the repository's outer
`strokesense` directory, with Python installed:

```powershell
python -m strokesense.feedback --pack "C:\path\to\StrokeSense-Eights-Review\study" --port 8767
```

Open the printed reviewer address. This standard-library review app displays
precomputed reports and does not download a model or run inference. Participant
responses live in the study's private `.feedback` directory. Share clean packs,
not folders containing that directory or an owner key.

## Add the same analyses to the normal application

The normal app is `strokesense.library` on port 8766. Its study import copies
the selected recordings and actual report/metrics/overlay artifacts, preserves
source and analysis hashes, and makes them reopenable from `/library`.
It does not create fake completed analysis jobs or rerun the model.
Follow the exact `--study-pack` command in `strokesense/LIBRARY.md`.

Unchanged imports reuse their existing saved analyses. Removed or revoked
clips lose their saved-analysis links; changed source/report bytes fail the
integrity check. A missing result stays unavailable. The regular analysis
history and the review website use separate databases and serve separate purposes.

## Public review on Render

Use `render.yaml` with `STROKESENSE_EXPECTED_CLIPS=7`, as documented in
`RENDER_DEPLOY.md` and `TESTER_LINKS.md`. The hosted service serves the saved
study and feedback form; the small service does not run pose inference.
Complete the private ZIP setup and verify all seven clips before generating
a reviewer link. The owner export key must remain private.

An unconnected account is a deployment blocker, not a code-test failure.
Do not advertise a public address until Render returns the real service URL
and playback, feedback persistence across restart, and owner exports work there.

## Rebuild the private package from actual run outputs

The selected clips and run records remain outside public Git. Once actual
analysis has completed, from the outer `strokesense` directory run:

```text
python -m strokesense.curated_study --selection selection.json --runs-dir run_records --output private-study/study --model-info model-provenance.json
```

The builder requires 5–7 entries with `rowers=8` and refuses to overwrite an
existing study. It verifies preview hashes and binds each completed run to the
selection's exact inference-input SHA-256, records original clip offsets,
and writes an explicit diagnostic when a run failed or withheld output.
No model result or reviewer feedback is filled in to make a form look complete.
