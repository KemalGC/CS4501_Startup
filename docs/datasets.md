# Evaluation datasets

## Recommended sources

| Dataset | What it contributes | License | Use in ProofGrade |
| --- | --- | --- | --- |
| [DrawEduMath](https://huggingface.co/datasets/Heffernan-WPI-Lab/DrawEduMath) | 2,030 real student-work images, teacher descriptions, and 11,661 teacher-written QA pairs | CC BY-NC 4.0 | Review interpretation of handwritten work and mistakes |
| [MathWriting](https://github.com/google-research/google-research/tree/master/mathwriting) | Handwritten expression strokes paired with LaTeX labels | CC BY-NC-SA 4.0 | Test expression transcription separately from grading |

DrawEduMath is the closer fit to the homework product. Its
[dataset card](https://huggingface.co/datasets/Heffernan-WPI-Lab/DrawEduMath/blob/main/README.md)
describes work from 188 problems spanning Grade 2 through high school. Use
`Image Caption` and `QA Teacher` as human references; keep model-generated QA
separate. Its code repository's Apache license does not replace the dataset
license. The CSV links the source images; it does not include a ProofGrade rubric.

Download the [official CSV](https://huggingface.co/datasets/Heffernan-WPI-Lab/DrawEduMath/resolve/main/Data/DrawEduMath_QA.csv)
and retain the [dataset card and usage guidance](https://huggingface.co/datasets/Heffernan-WPI-Lab/DrawEduMath/blob/main/README.md).
Record the downloaded revision/checksum. Group any development/evaluation split
by problem ID so variants of one question do not leak across the split. Select
supported algebra examples before testing this MVP; do not interpret other topics
as automatic grading failures. This source was located and documented, not yet
curated or run through the model.

Both licenses restrict commercial use. Keep these as attributed research datasets;
obtain appropriate permission or collect separately licensed material before
using them for a commercial product. Do not place their data under this repo's
code license. Original work collected for grading validation needs its own
permission and deletion policy.

## Reproducible MathWriting starter

The official MathWriting excerpt is small enough for a quick evaluation setup.
The included tool renders its human InkML strokes to PNG and keeps the normalized
LaTeX labels. These are individual expressions, often outside the MVP algebra
grammar, not photographs of entire assignments or teacher-assigned grades.

```sh
python -m pip install -r requirements-media.lock
python -m proofgrade.mathwriting prepare --download \
  --out datasets/mathwriting-valid --split valid --limit 20
```

Dataset rendering uses the optional Pillow library. Run preparation on a machine
where that library is allowed. Homework photo upload and the scoring command do
not require it; the app's browser image path is independent of this tooling.

Or use a previously downloaded official excerpt:

```sh
python -m proofgrade.mathwriting prepare \
  --archive /path/to/mathwriting-2024-excerpt.tgz \
  --out datasets/mathwriting-valid --split valid --limit 20
```

The source is
`https://storage.googleapis.com/mathwriting_data/mathwriting-2024-excerpt.tgz`.
The verified archive contains 1,620,634 bytes and has SHA-256:

```text
cba038def001480a89962b25cb20a60df4c4145e94c86ef9d2af65f192cb82bc
```

The command selects 1–100 human samples from one original split (`train`, `valid`,
or `test`) and writes:

- `images/`: rendered PNGs.
- `manifest.jsonl`: sample IDs, source split, normalized label, image path,
  license, source URL, and archive checksum.
- `ATTRIBUTION.txt`: source attribution and adaptation notice, including the
  upstream notice about Wikipedia-derived LaTeX labels.
- `predictions.example.jsonl`: empty prediction rows, not model results.

Raw downloads and derived data stay in ignored `datasets/`. No dataset images are
bundled in the app or Docker image. On 2026-10-20, preparation of 20 validation
samples succeeded and two rendered examples were visually inspected. This
confirms the data pipeline only; no OCR accuracy has been measured.

## Measure transcription without leaking labels

Use `train`/`valid` while developing; reserve `test` for a frozen configuration.
Never send the reference label alongside an image when requesting a prediction.
The teacher extraction endpoint emits bounded plain algebra rather than LaTeX,
so use a separate transcription evaluation prompt for this dataset. Do not
compare the endpoint's raw plain-text output against LaTeX and call it accuracy.

Fill a separate JSONL file with actual predictions in normalized LaTeX:

```json
{"sample_id":"<ID from manifest>","prediction":"<model transcription>"}
```

Then run:

```sh
python -m proofgrade.mathwriting score \
  --manifest datasets/mathwriting-valid/manifest.jsonl \
  --predictions predictions.jsonl
```

The report gives literal exact match and character error rate over every manifest
row. Missing predictions count as errors; unknown/duplicate IDs are rejected.
Equivalent LaTeX spellings may count as mismatches. This simple metric is not a
reproduction of the paper's tokenized benchmark. Save the model, prompt version,
split, sample IDs, cost, and failure count with any result. No model call is made
by the preparation/scoring commands, and no training has been performed.

## Grading validation still needs a local reference set

Prepare 30–50 permitted algebra responses with source pages, teacher-confirmed
transcripts, complete keys, point rubrics, reference scores, and error locations.
Include correct alternatives, partial work, missing roots, unreadable symbols,
and unsupported notation. Have independent educators resolve disagreements and
hold out examples from prompt development. Measure transcription separately from
score agreement and teacher time; see the [pilot plan](pilot-plan.md).

The repository's existing 42 cases remain developer-authored algebra regression
fixtures. Neither those cases nor a handwriting dataset establish reliable
classroom grading.
