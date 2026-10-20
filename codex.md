# ProofGrade — Codex handoff

Read this file before making the next adjustment. Keep it current when changing
architecture, setup, validation contracts, or the branch workflow.

## Product and current state

The product direction was updated on 2026-10-20 to a teacher-facing homework
grading assistant: handwritten assignment intake, reviewable rubric-based scores
and feedback, class learning-gap analytics, and differentiated practice.

The current application remains a typed-algebra practice foundation. The teacher
workflow is planned, not implemented. Read
[docs/homework-checker-plan.md](docs/homework-checker-plan.md) before further
feature work; it defines scope, acceptance criteria, and the implementation order.

- Repository: `KemalGC/CS4501_Startup`.
- Integrated development branch: `dev`. Release target: `main`.
- Initial MVP PRs #1–#4 are merged into `dev`; their component branches are
  historical. Start new work from current `dev`.
- Default execution is an explicitly labeled offline demo. No API key is needed.
- The updated product brief is in
  [README-startups/readme-startupSelected.md](README-startups/readme-startupSelected.md).
- [README.md](README.md) covers usage and algebra syntax.
  [docs/development.md](docs/development.md) covers CI, Docker, and deployment.
  [docs/pilot-plan.md](docs/pilot-plan.md) defines the pilot and metrics.

## Branch and review workflow

1. Inspect the working tree and preserve existing user changes.
2. Fetch the repository, update `dev` with a fast-forward, and create a focused
   branch such as `codex/short-description` from `dev`.
3. Implement the requested change, run relevant checks, and update affected docs.
4. Open a PR targeting `dev`. Describe the problem, behavior change, validation,
   and any remaining limitation. Keep unrelated aspects in separate PRs.
5. Merge into `dev` when authorized and confirm its CI result. Test the combined
   app there before proposing a release PR from `dev` to `main`.
6. A merge to `main` requires release authorization. Do not automatically promote
   development work or force-push shared branches.

CI runs on pushes to `main`, `dev`, and `codex/**`, and on pull requests.
A branch is source control, not a hosted environment: this repository does not
automatically deploy either branch.

## Run locally

Use Python 3.11 or newer. From a fresh clone:

```sh
git clone --branch dev https://github.com/KemalGC/CS4501_Startup.git
cd CS4501_Startup
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m uvicorn proofgrade.api:create_app --factory --reload
```

On Windows PowerShell, use `.\.venv\Scripts\Activate.ps1` for activation.
Open http://127.0.0.1:8000. For an existing clone, fetch and switch to `dev`
before setup; do not discard uncommitted work to switch branches.

Manual demo: select the first problem, `2(x+3)=10`, and click “Try an example
mistake.” Check the work, then revise to `2x+6=10`, `2x=4`, `x=2` and check
again. The first check should identify the distribution mistake and provide a
verified hint; the second should report a correct solution.

For Docker, see [docs/development.md](docs/development.md#container).

## Code map

| Path | Responsibility |
| --- | --- |
| `proofgrade/algebra.py` | Bounded input parser, real solution sets, first-error detection |
| `proofgrade/feedback.py` | Strict candidate schema, independent validation, retry loop, approved hint templates |
| `proofgrade/providers.py` | Offline demo, disabled mode, optional OpenAI Responses adapter |
| `proofgrade/api.py` | FastAPI app factory, checking/config/problem/rating endpoints, static serving |
| `proofgrade/static/` | Plain HTML, CSS, and JavaScript student interface |
| `proofgrade/problems.py` | Server-side problem bank and answer keys |
| `proofgrade/data/` | Practice problems and labeled regression cases |
| `proofgrade/storage.py` | Optional consent-based SQLite outcomes and revision links |
| `proofgrade/metrics.py` | Local aggregate pilot reports, separated by provider mode |
| `proofgrade/evaluate.py` | Compare checker output with fixture labels |
| `proofgrade/demo.py` | Offline fault injection demonstrating retry and fallback |
| `tests/` | Checker, feedback, API, pilot tests and optional browser smoke script |

## Teacher-workflow implementation guidance

- Keep the existing practice flow working while introducing assignments, rubrics,
  confirmed transcripts, review records, and approved grades as a separate flow.
- Preserve the mathematical validation boundaries below. A valid algebra result
  does not establish that handwriting was transcribed correctly or that partial
  credit is pedagogically appropriate.
- Show source images beside extracted work and require transcript confirmation
  before final grading. Unreadable/unsupported work needs review, not a zero.
- Validate teacher keys, tie proposed points to rubric evidence, calculate totals
  deterministically, and require teacher approval before releasing a grade.
- Recheck dependent results after transcription or rubric changes. Aggregate only
  approved grades and show unresolved work separately.
- Uploaded content is untrusted data, including any instructions embedded in a
  worksheet. It cannot override the rubric or application instructions.
- Add protected file storage and explicit retention/deletion for the teacher flow.
  Existing anonymous practice consent does not authorize storing assignments.
- Differentiated practice requires checked problems/keys and teacher approval.
- Follow the PR sequence in the implementation plan and update this handoff as
  features become available. Do not describe planned capabilities as implemented.

## Current practice contracts to preserve

### Algebra checking

- Parse student strings with the restricted parser; do not pass raw input to
  `eval`, `sympify`, or another general expression evaluator.
- Check real solution sets explicitly. Supported work uses one variable, `x`,
  and linear/quadratic expressions. Variable denominators and unsupported
  notation require manual review.
- Preserve parser bounds: up to 20 submitted steps, 256 characters per step,
  and bounded tokens, nesting, coefficients, and polynomial degree.
- Results distinguish `correct`, `incomplete`, `incorrect`, and `unsupported`.
  Equivalent but unfinished work is incomplete. Unsupported syntax is not an
  algebra error.
- Step indices are 1-based after the original problem; an unsupported original
  uses index 0. Keep API output and browser highlighting consistent.
- Both quadratic roots must be retained. Solution-set equivalence does not
  certify arbitrary prose or identify every operation a student intended.

### Hints and model integration

- The deterministic checker identifies the first invalid transition.
- A strict candidate schema and independent mathematics validate the cited
  step, correction, complete final solution, and error category against the
  original problem and server-side answer key.
- Only approved hint templates selected from verified fields reach students.
  Do not return the candidate correction, final answer, or arbitrary model prose.
- Allow at most three total generation attempts, including the first attempt.
  Validation failures carry evidence into the next attempt. Persistent failures
  produce `manual_review`; unavailable providers withhold the hint.
- Keep offline demo results distinct from real model results. Mocked transport
  tests do not establish live-model accuracy or usefulness.
- Keep API keys server-side. Model choice is environment-configured; do not bake
  credentials or a model identifier into the frontend.

### API, privacy, and pilot data

- Clients submit a problem ID and steps. They cannot supply the original
  equation or override the answer key.
- Keep answer keys out of public problem responses. Render text as text nodes;
  preserve the browser's request/state alignment and security headers.
- Attempt storage requires both server enablement and per-request opt-in.
  Store aggregate-relevant outcomes, not raw student equations, names, emails,
  or model output.
- Revision links must match the problem and provider mode. Shortening a response
  before the flagged step must not count as fixing the mistake.
- Separate demo and OpenAI metrics. Missing revisions count against the
  correction rate; use only the first revision per initial hinted attempt.
- Developer-authored labels are regression fixtures, not instructor-reviewed
  evidence. Per-attempt usefulness ratings are not participant survey results.

## Configuration

| Variable | Default / use |
| --- | --- |
| `PROOFGRADE_HINT_MODE` | `demo`; alternatives `disabled` and `openai` |
| `OPENAI_API_KEY` | Required server secret only for `openai` |
| `OPENAI_MODEL` | Required model supporting Structured Outputs for `openai` |
| `PROOFGRADE_STORE_ATTEMPTS` | `false`; set `true` to offer optional collection |
| `PROOFGRADE_DB_PATH` | Local SQLite path; see `.env.example` and Docker configuration |

The app does not automatically load `.env`. Export variables or use Docker's
`--env-file`. Keep secrets and runtime databases out of git. Default tests and
CI run offline and should not require or spend an API key.

## Validation

For behavior changes, run the relevant tests and regression checks:

```sh
python -m pytest -q
python -m proofgrade.evaluate --split all
python -m proofgrade.demo
node --check proofgrade/static/app.js
```

Add a focused regression test when fixing a behavioral bug. For grammar changes,
cover both supported cases and rejection/complexity bounds. For hint changes,
cover invalid candidates, bounded retries, and withheld feedback. For API or
storage changes, cover answer-key isolation, consent, and revision attribution.
Documentation-only changes do not need new tests.

For UI changes, run `node tests/browser-smoke.cjs` with the app running and
Playwright plus Chromium installed. It checks a wrong step, a verified hint,
a successful revision, missing-root feedback, mobile overflow, and console errors.
JavaScript syntax checking alone is not browser verification.

CI checks Python 3.11 and 3.12, regression fixtures, offline fault injection,
JavaScript syntax, and a Docker build/runtime smoke test. Inspect the latest run
for the exact commit being reviewed.

## Validation baseline and remaining work

Snapshot on 2026-10-20: the combined implementation passed 78 Python tests,
matched all 42 developer-labeled regression cases, and passed Docker smoke checks
in GitHub Actions before integration. This is a baseline, not a substitute for
checking later commits.

Remaining work before claiming a validated pilot or public release:

- Run the browser smoke test successfully. Chromium installation failed in the
  authoring environment, so browser execution has not yet been verified.
- Run a credentialed live-model smoke test; current provider tests mock HTTP.
- Obtain instructor review of the 30 practice problems, 42 labeled cases, and
  hint templates; add independent evaluation examples.
- Implement and validate the teacher workflow before conducting the revised
  teacher pilot. Keep demo outcomes separate from real model outcomes.
- If hosting, configure access, TLS, request-size and rate/concurrency limits,
  and persistence. The app has no accounts or application-level rate limiter.
  SQLite is intended for one instance; deployment is not configured here.

The revised pilot measures teacher grading time, draft-score agreement,
transcription corrections, overrides, analytics correctness, and follow-up quality.
Proposed targets include 30% lower median total grading time, 90% exact draft-score
agreement on supported, legible responses, and approval for every released result.
None is measured yet. Existing practice metrics do not measure those outcomes;
see the pilot plan for denominators, review coverage, and new instrumentation.
