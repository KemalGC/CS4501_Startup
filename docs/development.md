# Development and review

## Branch workflow

`dev` contains the integrated teacher MVP. Feature PRs target `dev`; `main` is the
release target and requires separate release authorization. There is no automatic
hosting or promotion. Read [codex.md](../codex.md), preserve user changes, then:

```sh
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c codex/your-change
```

PRs #1–#4 built the original practice flow; #5 updated product scope; #6 added the
teacher backend; #7 added uploads, model adapters, the teacher interface, and
browser CI. Use focused PRs for future changes and inspect exact-head CI before
merging. Integrated `dev` also runs the checks after merges.

## Local setup and checks

Follow [README setup](../README.md#development), including the teacher account
command. `/` and `/teacher` open the teacher workspace; `/practice` is the original
student interface. The default workflow needs no API key.

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

On Linux, Playwright may need `npx playwright install --with-deps chromium`.
`npm run test:browser` creates a temporary account/database, starts and stops its
own server, and checks both flows, including image upload, manual source review,
partial credit, approval, exports, targeted practice, revision invalidation,
mobile overflow, and browser errors. It writes screenshots to ignored
`test-results/`. An already running student app can also be tested with
`PROOFGRADE_TEST_URL=http://127.0.0.1:8000 node tests/browser-smoke.cjs`.

CI runs Python 3.11/3.12, regression evaluation, offline fault injection,
JavaScript syntax, both Chromium flows, and a Docker runtime smoke check.
Screenshots are uploaded as `teacher-browser-previews`. On 2026-10-20 these
checks passed for the teacher workspace and the screenshots were inspected.
Local Chromium launch is blocked in the authoring sandbox; CI provides the
browser execution evidence. No API credentials are used in tests.

`requirements.lock` pins runtime dependencies; `package-lock.json` pins browser
test dependencies. Update pins intentionally. The current httpx-backed TestClient
emits a Starlette deprecation warning; it does not fail the suite.

## Container

Use the same persistent volume for account creation and the application:

```sh
docker build -t proofgrade .
docker run --rm -it -v proofgrade-data:/data \
  proofgrade python -m proofgrade.teacher_cli kemal
docker run --rm -p 127.0.0.1:8000:8000 \
  -v proofgrade-data:/data proofgrade
```

The image runs as a non-root user. Both teacher records/source pages and optional
student metrics use `/data`. Without the volume, recreating a container loses its
accounts and assignments. `/health` is the health endpoint. Student practice
collection remains off unless `PROOFGRADE_STORE_ATTEMPTS=true`; enabled collection
still requires per-request consent.

For real model calls configure `PROOFGRADE_TEACHER_AI=openai`, `OPENAI_API_KEY`,
and a vision/Structured Outputs model in `PROOFGRADE_VISION_MODEL`. Model hints
also need `PROOFGRADE_HINT_MODE=openai` and `OPENAI_MODEL`. See `.env.example`;
local Python does not auto-load it. Use exported variables or a private Docker
`--env-file`. Never commit secrets or put them in frontend assets or the image.

## Pilot hosting and current boundaries

For a hosted pilot use HTTPS and `PROOFGRADE_SECURE_COOKIES=true`. Accounts,
ownership checks, bounded uploads, a login limiter, and teacher-model concurrency
limits are implemented. Add host-level rate limits, appropriate request/time
limits, access restrictions, and storage/backups for the intended pilot. In-process
limits and SQLite support one instance; multiple workers/instances need shared
limits and storage. Public registration, password recovery, school rosters,
student portals, LMS posting, and production operations are outside this MVP.

The app retains normalized pages and teacher records until deleted through the UI
or API. Deletion cascades through dependent records; operator backups and external
provider retention have separate lifecycles. Agree on a pilot deletion date.
The repo does not publish automatically. Docker is verified in GitHub Actions;
no hosted instance has been created.

A credentialed model smoke test, independent instructor review, teacher-time
measurement, and the [pilot](pilot-plan.md) are still outstanding. See
[datasets.md](datasets.md) for licensed evaluation sources and preparation commands.

## Technical references

- [SymPy parsing warning](https://docs.sympy.org/latest/modules/parsing.html): raw input uses a restricted parser.
- [SymPy solveset](https://docs.sympy.org/latest/modules/solvers/solveset.html): explicit real solution sets.
- [OpenAI vision inputs](https://developers.openai.com/api/docs/guides/images-vision).
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
