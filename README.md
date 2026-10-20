# ProofGrade

ProofGrade helps math teachers check handwritten algebra homework, review grades
and feedback, identify class learning gaps, and prepare targeted practice.
The integrated MVP is on **`dev`**. `main` is reserved for an approved release.

## What works now

- Private teacher accounts and assignments with checked answer keys and rubrics.
- JPG/PNG and scanned PDF uploads, with source pages beside editable transcripts.
- Optional AI transcription; manual entry works without an API key.
- Suggested rubric scores, first invalid steps, checked hints, partial-credit
  overrides, teacher approval, and versioned review history.
- Approved-grade CSV and feedback exports, question/skill summaries, and student
  progress across assignments in the same class.
- Three-question practice sets for reviewed skill gaps, with independently checked
  keys and teacher approval before student download.
- The original student practice checker remains available at `/practice`.

The first release supports short linear/quadratic algebra worksheets, not general
math grading. Scores come from explicit rubric rules; teachers decide partial
credit and subjective criteria. Every released result needs teacher approval.

## Development

Requires Python 3.11 or newer. Read [codex.md](codex.md) before changing the project.

```sh
git clone --branch dev https://github.com/KemalGC/CS4501_Startup.git
cd CS4501_Startup
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m proofgrade.teacher_cli kemal
python -m uvicorn proofgrade.api:create_app --factory --reload
```

The account command prompts for a password of at least 12 characters. There is no
shared default password or public registration. On Windows PowerShell, activate
with `.\.venv\Scripts\Activate.ps1`. For an existing clone, fetch and switch to
`dev` first, preserving uncommitted changes.

Open http://127.0.0.1:8000 and sign in. Create an assignment or choose **Try a
synthetic demo** from the empty workspace. The demo creates typed, synthetic work;
it does not pretend to recognize handwriting. Review a response, confirm its
transcript, approve or override the suggested grades, and return to the dashboard
to export grades and create practice for a reviewed skill gap.

Use one file per student: an image up to 20 megapixels or a PDF up to 5 pages,
8 MiB per file. The UI accepts batches of up to 20 files; assignments support
1–5 questions and up to 200 student responses. Files become normalized PNG source
pages stored privately with the assignment. Delete a response or assignment to
remove its retained work and dependent records. Rubrics are immutable after
creation; create a replacement assignment to change a rubric.

## AI configuration

By default, `PROOFGRADE_TEACHER_AI=disabled` and `PROOFGRADE_HINT_MODE=demo`:
manual transcription, deterministic checking, checked hint templates, and varied
practice from checked templates work offline. No API key is required.

To enable model transcription and model-proposed practice, set these variables in
the server environment:

```text
PROOFGRADE_TEACHER_AI=openai
OPENAI_API_KEY=<your server-side secret>
PROOFGRADE_VISION_MODEL=<a vision model supporting Structured Outputs>
```

For model-proposed hint candidates, also set `PROOFGRADE_HINT_MODE=openai` and
`OPENAI_MODEL` to a model supporting Structured Outputs. The teacher model falls
back to `OPENAI_MODEL` when `PROOFGRADE_VISION_MODEL` is empty. The app does not
load `.env` automatically; export variables or use Docker's `--env-file`.

**Extract handwriting with AI** sends normalized source pages and question
prompts to the configured OpenAI model. Keys are not included in transcription
requests. Responses use `store=false`; this is not a claim of zero provider
retention. The model must preserve mistakes and flag unreadable work. Teachers
must confirm its transcript. Invalid candidates get at most three attempts;
persistent failures are withheld and manual review remains available.

Provider tests use mocked HTTP. A credentialed live-model smoke test and measured
handwriting accuracy remain outstanding. See [OpenAI vision inputs](https://developers.openai.com/api/docs/guides/images-vision)
and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Supported algebra and grading

- One real variable `x`, linear or quadratic expressions.
- Exact numbers, fractions, decimals, parentheses, implicit multiplication,
  powers 0–2, and `sqrt(number)` for nonnegative rational constants.
- Both roots on one line, for example `x=-2 or x=2`; also `no real solutions`
  and `all real numbers`.
- Up to 20 steps per question, 256 characters per step, bounded parser complexity.

The checker compares real solution sets and identifies the first invalid
transition. It accepts valid alternative equation sequences, but cannot certify
arbitrary prose or determine every operation the student intended. Variable
denominators, inequalities, complex numbers, diagrams, and unsupported notation
need a teacher decision. Unreadable/unsupported responses receive unset suggested
scores, not silent zeros.

Final-answer criteria award full points for the complete correct solution set.
Valid-work criteria award full points for equivalent transitions with a non-final
intermediate equation distinct from the original. Teachers review partial credit
and manual criteria, explaining overrides. Reconfirming a transcript invalidates
its old approval and removes it from summaries and exports until reapproved.
Only approved grades contribute to analytics; review coverage stays visible.

Checked hints use validated categories and approved templates. Candidate answers,
corrections, and arbitrary model prose are not exposed to students. Teacher-written
feedback is explicitly a human decision. Student practice downloads omit keys.

## Datasets and validation

See [docs/datasets.md](docs/datasets.md) for **DrawEduMath**, a closer benchmark for
interpreting real student work, and **MathWriting**, for expression transcription.
Both datasets carry noncommercial licenses. They do not provide a drop-in
reference rubric for this application's grading policy.

Prepare a small reproducible MathWriting evaluation sample:

```sh
python -m proofgrade.mathwriting prepare --download --split valid --limit 20
```

This downloads a checksum-pinned excerpt, renders InkML to PNG, and preserves
labels, split, source, and attribution. Dataset downloads stay out of git and
application storage; this command does not train or call a model.

```sh
python -m pytest -q
python -m proofgrade.evaluate --split all
python -m proofgrade.demo
npm ci
npx playwright install chromium
npm run test:browser
```

CI runs Python 3.11/3.12 tests, the 42 developer-labeled algebra cases, fault
injection, teacher/student browser flows including mobile checks, and Docker smoke
checks. The 30 practice exercises and 42 regression cases await instructor review.
Synthetic tests do not establish grading quality or time savings.

The [pilot plan](docs/pilot-plan.md) proposes measuring total teacher time,
transcription corrections, draft-score agreement, overrides, and practice quality.
The pilot has not been conducted. Teacher active-time measurement and independent
reference grades still need to be collected.

## Persistence and deployment

Teacher records and normalized source pages use `PROOFGRADE_TEACHER_DB`
(default `data/teachers.sqlite3`). Accounts use salted password hashes, expiring
sessions, ownership checks, and cross-origin mutation protections. Retain only
permitted work, use anonymous codes, and agree on a deletion date for a pilot.
The separate student-practice metrics remain disabled by default and require
per-request opt-in when enabled.

See [development and deployment](docs/development.md) for persistent Docker
volumes, HTTPS configuration, and the feature-PR-to-`dev` workflow. This is a
single-instance pilot application; hosted deployment, recovery operations,
rosters/LMS integration, and a public production release are not configured.

Product scope: [selected startup brief](README-startups/readme-startupSelected.md),
[implementation status](docs/homework-checker-plan.md), and
[teacher API](docs/teacher-api.md).
