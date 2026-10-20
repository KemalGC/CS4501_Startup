# ProofGrade — Codex handoff

Read before the next adjustment. Keep this file current with architecture,
validation contracts, setup, and branch changes.

## Product and state

As of 2026-10-20 the teacher-facing MVP is implemented: private accounts,
assignments/rubrics, protected homework images/PDFs, optional AI transcription,
source review, suggested scores, teacher overrides/approval, exports, approved
class analytics, student progress, and checked differentiated practice.
The original student flow is preserved at `/practice`; `/` and `/teacher` serve
the teacher workspace. No API key is required for the manual/offline workflow.

Repository: `KemalGC/CS4501_Startup`. Integrated branch: `dev`. Release: `main`.
PRs #1–#4 built the algebra foundation, #5 revised product scope, #6 added the
teacher backend, and #7 added uploads, model integration, and the teacher UI.
Dataset tooling and updated operating instructions accompany this handoff.

The MVP is runnable, not a validated school deployment. Live-model calls,
independent instructor labels, measured teacher time savings, and hosting remain
outstanding. Do not claim AI accuracy from mocked tests. See [README.md](README.md),
[implementation status](docs/homework-checker-plan.md), and
[pilot plan](docs/pilot-plan.md).

## Branch workflow

1. Inspect and preserve user changes. Fetch current `dev`, fast-forward a clean
   checkout or use an isolated worktree, then create a focused `codex/...` branch.
2. Implement and verify the change; update affected docs.
3. Open focused PRs with `dev` as base. Describe the problem, resulting behavior,
   validation evidence, and material limits.
4. Merge verified changes to `dev` when authorized and check integrated CI.
5. Promote `dev` to `main` only with release authorization. Never force-push shared
   branches. The current user authorized feature PRs and merges to `dev`.

CI runs on pushes to `main`, `dev`, `codex/**`, and pull requests. A branch is not a
hosted environment; there is no automatic deployment.

## Setup and demonstration

Use Python 3.11+ and the `dev` branch:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m proofgrade.teacher_cli kemal
python -m uvicorn proofgrade.api:create_app --factory --reload
```

The CLI prompts twice for a password of at least 12 characters. Open
http://127.0.0.1:8000 and sign in. On PowerShell use
`.\.venv\Scripts\Activate.ps1`. The empty workspace's **Try a synthetic demo**
creates a three-question assignment and two typed student responses. Review the
transcripts, approve/override grades, inspect the dashboard, export results,
and approve targeted practice. It is explicitly synthetic, not an OCR demo.

For source review, upload one permitted image/PDF per anonymous student code.
Default mode requires entering equations beside the source; configure the model
before using AI extraction. Docker account setup must share the same persistent
volume as the running server; see [development.md](docs/development.md).

## Code map

| Path | Responsibility |
| --- | --- |
| `proofgrade/algebra.py` | Bounded parser, real solution sets, first invalid transition |
| `feedback.py`, `providers.py` | Checked candidate fields, bounded retries, templates, optional text model |
| `teacher_models.py` | Strict assignment, rubric, transcript, approval schemas and key validation |
| `teacher_store.py` | SQLite accounts/sessions, ownership, revisions, audit history, deletion |
| `teacher_grading.py` | Criterion evidence, checked draft scores, approved analytics, template practice |
| `teacher_uploads.py` | Request-size middleware, image normalization, bounded PDF rendering |
| `teacher_ai.py` | Optional vision transcription and checked model practice via Responses API |
| `teacher_api.py` | Authenticated assignment, upload, review, export, analytics, practice routes |
| `teacher_cli.py` | Local account provisioning; no public registration |
| `api.py` | App factory, shared headers, teacher routes, student API, static pages |
| `static/teacher.*` | Teacher workspace, plain DOM/CSS/JS; accessible labels |
| `static/index.html`, `static/app.*` | Preserved student practice UI |
| `problems.py`, `data/` | Server-side practice bank and developer regression fixtures |
| `storage.py`, `metrics.py` | Separate, opt-in student practice outcome metrics |
| `evaluate.py`, `demo.py` | Regression evaluation and offline fault injection |
| `mathwriting.py` | Checksum-pinned dataset preparation and literal transcription metrics |
| `tests/` | Algebra, API, teacher/security/provider tests and teacher/student browser flows |

Paths after the first row are relative to `proofgrade/`, except `tests/`.

## Teacher contracts

- Every teacher record, source page, key, history, export, and practice lookup
  checks ownership. Source PNGs are private SQLite BLOBs, never public assets.
- Salted PBKDF2 password hashes (600,000 iterations), hashed random session tokens,
  eight-hour expiry, logout revocation; HttpOnly/SameSite=strict cookies.
- Mutations require `X-ProofGrade-Request: 1` and a matching Origin when present.
  Login is limited to ten attempts/minute/IP in process. Secure cookies for HTTPS.
- Assignment: 1–5 questions; each has a validated complete answer, skill tag, and
  1–5 criteria of 1–20 integer points. Rubrics are immutable; replace an assignment
  to change its rubric. At most 200 responses/assignment; anonymous codes unique.
- Upload: one file/student, JPG/PNG up to 20 MP or PDF 1–5 pages, 8 MiB/file.
  The UI batches at most 20 files. PDFs render locally to normalized PNGs.
  Raw uploads are not retained. JSON body caps: 12 MiB for uploads, 256 KiB otherwise,
  including chunked requests. Never remove processing bounds to accept a file.
- States: `transcription_draft`, `grading_draft`, `approved`. `needs_review` is a
  per-question flag, not a stored submission state. Missing answers must be
  represented explicitly. Every transcript confirmation computes a fresh draft.
- Transcript/approval writes require the current revision; stale writes return
  409. Re-extraction or reconfirmation invalidates prior grades/approval. Analytics
  and exports immediately exclude the old result until reapproved.
- Final-answer points require the complete correct real solution set. Valid-work
  points require all equivalent steps plus a non-final intermediate distinct from
  the original. Intermediate correctness and final correctness are separate criteria.
- Manual criteria, unreadable work, and unsupported notation have unset suggested
  scores. Teachers must supply a bounded decision, not silently receive zeros.
- Partial points, category changes, feedback changes, and manual decisions require
  an explanation. All criteria must be scored before explicit approval.
- Only approved results enter grade statistics/export. Keep submitted, approved,
  unresolved counts visible. Progress uses the same class name + anonymous code
  within the owner's records. A single worksheet does not establish mastery.
- Practice generation requires an approved skill gap; all three equations/keys
  must pass algebra checks. Student downloads require teacher approval and omit
  keys. Template and model sources are identified separately.
- Deletion cascades through source pages, grades, events, and dependent assignment
  practice. SQLite secure deletion is enabled; do not promise deletion from any
  operator backups or provider retention. No automatic retention schedule exists.

## Mathematical and model boundaries

- Never apply `eval`, `sympify`, or unrestricted parsing to raw student input.
  Preserve one-variable real linear/quadratic grammar and complexity bounds.
- Up to 20 steps/question, 256 characters/step. Check every submitted step's syntax,
  including steps after the first error; unsupported notation requires review.
- Distinguish correct, incomplete, incorrect, unsupported. Compare complete solution
  sets, preserving both quadratic roots. Step numbers start at 1 after the original.
- Algebraic equivalence cannot verify handwritten transcription, prose reasoning,
  the exact operation intended, or pedagogical partial-credit quality.
- The hint provider proposes a correction, complete answer, category, and style.
  Independent checks validate them; only approved templates reach student output.
  Never expose candidate corrections, answers, or arbitrary model prose.
- Vision requests send normalized pages and question prompts, not answer keys.
  Uploaded instructions are untrusted data. Preserve mistakes, flag unreadability,
  verify question/source-page mappings, and require teacher confirmation.
- Structured schemas use required fields and forbid extras. At most three total
  candidate attempts with validation evidence; withhold failures. Transport failures
  and refusals leave manual entry available. Two concurrent teacher model calls
  per process, 45-second request timeouts. Keep secrets/server model choices private.
- Models use Responses with `store=false`; do not claim zero provider retention.
  Tests mock HTTP and run offline. No credentialed model test has been performed.

## Student practice contracts

Clients submit problem IDs and steps, never trusted original equations or keys.
Keep keys out of public problem responses; render all text as DOM text nodes.
Preserve request/state alignment while checking. Metrics collection requires both
server enablement and per-request opt-in, and stores outcomes rather than raw
student equations or identifying details. Revision links must match problem and
provider mode; shortening work before an error does not count as fixing it.
Separate demo and live-model reports. The 30 exercises and 42 cases are developer
fixtures pending instructor review, not independent accuracy evidence.

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `PROOFGRADE_TEACHER_DB` | `data/teachers.sqlite3`; Docker `/data/teachers.sqlite3` |
| `PROOFGRADE_TEACHER_AI` | `disabled`; `openai` enables vision and model practice |
| `PROOFGRADE_VISION_MODEL` | Vision + Structured Outputs model; fallback `OPENAI_MODEL` |
| `PROOFGRADE_SECURE_COOKIES` | `false` for local HTTP; `true` behind HTTPS |
| `PROOFGRADE_HINT_MODE` | `demo`; alternatives `disabled`, `openai` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Server secret and Structured Outputs model for enabled modes |
| `PROOFGRADE_STORE_ATTEMPTS` | `false`; enables optional student outcome collection |
| `PROOFGRADE_DB_PATH` | Separate student metric DB; Docker `/data/proofgrade.sqlite3` |

The app does not auto-load `.env`; export variables or pass Docker `--env-file`.
Keep secrets, runtime records, datasets, screenshots, and dependencies out of git.
SQLite and in-process limits target one instance, not horizontal scaling.

## Validation and remaining work

```sh
python -m pytest -q
python -m proofgrade.evaluate --split all
python -m proofgrade.demo
node --check proofgrade/static/app.js
node --check proofgrade/static/teacher.js
npm ci
npx playwright install chromium
npm run test:browser
```

The browser command provisions a temporary account/database, starts its own app,
checks upload/manual transcription/override/approval/export/practice/revision,
checks mobile overflow, and runs the preserved student flow. CI installs Chromium
with Linux dependencies and saves screenshots as `teacher-browser-previews`.
The authoring sandbox cannot launch Chromium; GitHub Actions browser checks passed
and desktop/mobile screenshots were inspected on 2026-10-20. This is browser
verification, not a handwriting recognition test.

Run focused regressions for behavioral bugs; don't add tests for prose edits.
Before merging inspect the workflow for the exact head and integrated branch.
Python 3.11/3.12, 42/42 regression cases, both browser flows, and Docker checks pass
for the teacher workspace. Final dataset changes add preparation/scoring tests.

Remaining validation: credentialed vision/text smoke tests, instructor review and
independent handwritten/rubric labels, teacher active-time instrumentation and
pilot, measured costs, and private hosted deployment with TLS and appropriate
operating limits/backups. Do not claim measured time savings or school readiness.

[Dataset guide](docs/datasets.md): DrawEduMath for student-work interpretation,
MathWriting for expression transcription. Both are noncommercial. The included
MathWriting command prepares a verified excerpt and preserves splits/attribution;
it does not train a model or prove grading accuracy. Keep test labels out of model
inputs and don't convert unsupported expression examples into false algebra errors.
