# ProofGrade

ProofGrade's product goal is to help math teachers grade handwritten homework,
review suggested scores and feedback, identify class learning gaps, and create
targeted follow-up practice. See the
[selected startup brief](README-startups/readme-startupSelected.md) and
[homework-checker implementation plan](docs/homework-checker-plan.md).

## Current implementation

The runnable app is the typed-algebra foundation: students select a practice
problem, enter their steps, find the first invalid transition, and revise using a
checked hint. Handwritten uploads, rubric scoring, teacher review, classroom
analytics, and differentiated practice are planned features, not available yet.
The default provider is an offline demo; it makes no real AI calls.

## Development

Use the `dev` branch for the integrated MVP; feature PRs target `dev`. Read
[codex.md](codex.md) before the next adjustment for the project handoff and checks.
Requires Python 3.11 or newer.

```sh
git clone --branch dev https://github.com/KemalGC/CS4501_Startup.git
cd CS4501_Startup
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m pytest -q
python -m uvicorn proofgrade.api:create_app --factory --reload
```

On Windows PowerShell, activate the environment with `.\.venv\Scripts\Activate.ps1`
instead of `. .venv/bin/activate`. For an existing clone, fetch and switch to `dev`
before running the setup commands.

Open http://127.0.0.1:8000. Select a practice problem, enter equations one line at
a time, and check your work. The default mode is explicitly labeled as a local
demo. Use “Try an example mistake” on the first problem to demonstrate distribution
feedback, then revise to `2x+6=10`, `2x=4`, `x=2` and check again.

The browser calls `GET /api/problems`, `GET /api/config`, and `POST /api/check`.
Only problem IDs and submitted steps are accepted; answer keys stay server-side.
The UI renders submitted and returned text as text nodes, not HTML, and disables
editing during a check to keep the highlighted step aligned with the request.
The 30 practice exercises are developer fixtures awaiting instructor review.

## Supported algebra

- One real variable, `x`; linear or quadratic expressions.
- Exact integers, fractions, decimals, parentheses, implicit multiplication
  (`2x`, `2(x+3)`), and powers `^` / `**` with exponents 0, 1, or 2.
- `sqrt(number)` for nonnegative rational constants, including irrational roots.
- State both roots on one line: `x = -2 or x = 2`.
- Use `no real solutions` or `all real numbers` when appropriate.
- Up to 20 submitted steps, 256 characters per step, and bounded expression complexity.

Variable denominators, inequalities, complex numbers, handwriting, arbitrary
functions, and reasoning outside this grammar need manual review. Unsupported
syntax is distinguished from a mathematical error. Step numbers start at 1 for
the first submitted line after the original problem.

The checker compares real solution sets. This detects lost and added roots; it
does not certify every explanation or prove which operation the student intended.
A valid sequence is only marked complete when the final line states all roots
or the applicable special solution set. No AI-generated text is used by this layer.

## Teacher MVP acceptance goals

The revised pilot will measure total teacher grading time, rubric-score agreement,
transcription corrections, teacher overrides, class-summary correctness, and
follow-up practice quality. Proposed targets include 30% lower median total grading
time, 90% exact draft-score agreement on supported, legible work, and teacher
approval for every released result. These are unmeasured targets for the planned
teacher workflow. See the [pilot plan](docs/pilot-plan.md) for denominators,
review coverage, and evaluation procedures.

The existing developer fixtures and practice metrics validate only the current
typed-algebra foundation; they cannot establish handwriting or grading accuracy.

## Verified hints

The checker supplies the first invalid transition. The candidate provider proposes
a corrected transition, complete final answer, error category, and hint style.
Pydantic checks the schema, and independent algebra checks validate the cited
transition, correction, and final answer against a server-side answer key. Only
approved templates matching a verified category are shown; candidate corrections,
final answers, and arbitrary model prose never reach the student response.

Candidates that fail validation are regenerated with the failure evidence, for at
most three total attempts. Refusals, timeouts, incomplete responses, and persistent
validation failures withhold the hint. Template usefulness still needs tutor review.

`PROOFGRADE_HINT_MODE=demo` is the default: a deterministic offline provider,
explicitly identified as a demo. It does not call or simulate a real LLM's quality.
`disabled` turns hints off. For real model calls, set `PROOFGRADE_HINT_MODE=openai`,
`OPENAI_API_KEY`, and `OPENAI_MODEL` in the server environment. Choose a model with
Structured Outputs support. Never commit a key. The adapter sends only the selected
problem and relevant transition to the Responses API, with `store=false`.
The live provider has transport-mocked tests; a real API smoke test remains required.

Reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Evaluation, pilot data, and deployment

Run `python -m proofgrade.evaluate --split all` for the 42 labeled developer cases.
Every case is marked pending instructor review. Run `python -m proofgrade.demo`
to demonstrate fault injection and the bounded retry/fallback behavior offline.

Attempt storage is disabled by default. Set `PROOFGRADE_STORE_ATTEMPTS=true` to
offer an unchecked opt-in box; only consenting requests are saved. SQLite records
outcomes and optional ratings, not entered equations or personal details. Set
`PROOFGRADE_DB_PATH` to choose the database file. Report results locally using
`python -m proofgrade.metrics --mode demo` (or `--mode openai` for real model data).

See [development and deployment](docs/development.md) for Docker commands,
configuration, remaining validation, and the branch workflow. PRs #1–#4 are merged
into `dev`, which contains the combined MVP. CI runs on `dev` pushes and pull
requests, including Python tests, regression evaluation, fault-injection demos,
JavaScript syntax checking, and a container smoke test. Run the app locally or in
Docker from `dev` before proposing a release PR from `dev` to `main`. Creating the
branch does not publish an application; hosted deployment is a separate step.
