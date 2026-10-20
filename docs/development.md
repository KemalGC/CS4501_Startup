# Development and review

## Pull request stack

1. `codex/algebra-checker`: package foundation and independent equation checking.
2. `codex/verified-hints`: validated candidates, three-attempt retry loop, providers.
3. `codex/student-web-app`: FastAPI endpoints and student interface.
4. `codex/pilot-deployment`: practice bank, opt-in outcomes, evaluation, CI, Docker.

Each PR targets the preceding branch so the diff isolates its component. Review
and merge in order. After merging a predecessor, retarget the next PR to `main`.
Using merge commits preserves the stack's ancestry; squash/rebase merges require
rebasing the remaining branches to avoid replaying predecessor commits. The last
branch contains the whole application and can be checked out for a combined demo.

## Local checks

```sh
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m pytest -q
python -m proofgrade.evaluate --split all
python -m proofgrade.demo
node --check proofgrade/static/app.js
```

`requirements.lock` records runtime versions used for local validation; development
tests are installed by the `dev` extra. Current Starlette emits a deprecation
warning for its httpx-backed TestClient. It does not fail the test suite.

For a browser smoke test, start the app and run `node tests/browser-smoke.cjs`
with Playwright and its Chromium browser installed. The script checks a wrong
step, a verified hint, successful revision, missing-root feedback, mobile overflow,
and browser JavaScript errors. Browser execution could not be completed in the
authoring environment because the Chromium download returned an invalid archive.
Do not describe the UI as browser-verified until this check has run successfully.

The optional OpenAI adapter is tested with mocked HTTP responses. A credentialed
live-model test, instructor review, student pilot, and hosted deployment remain
separate tasks. Model access is explicitly configured; tests never use an API key.

## Container

```sh
docker build -t proofgrade .
docker run --rm -p 127.0.0.1:8000:8000 proofgrade
```

The image runs as a non-root user and checks `/health`. It starts in offline demo
mode and does not save attempts. For an opt-in pilot, use a persistent volume:

```sh
docker run --rm -p 127.0.0.1:8000:8000 \
  -e PROOFGRADE_STORE_ATTEMPTS=true \
  -v proofgrade-data:/data proofgrade
```

Set `PROOFGRADE_HINT_MODE=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` through the
hosting service's secret/environment settings for real model calls. Use a model
that supports structured outputs. The example environment file is documentation;
the local app does not automatically load `.env`. Use exported shell variables or
a container `--env-file`. No real key belongs in git, frontend assets, or an image.

For initial hosted use, place the app behind the host's private access gate, TLS,
request-size limits, and rate/concurrency limits, especially in paid model mode.
The app has no accounts or application-level rate limiter. Keep it private until
those controls are configured. Use one instance with SQLite or move to a shared
database before scaling. The repository does not deploy or publish automatically;
the container workflow only builds and smoke-checks the image in CI. Docker is not
installed in the authoring environment, so the image build must be verified by CI
or on a machine with Docker before deployment.

## Technical references

- [SymPy parsing warning](https://docs.sympy.org/latest/modules/parsing.html):
  this project uses a restricted parser instead of applying eval-based parsing to
  raw student input.
- [SymPy solveset](https://docs.sympy.org/latest/modules/solvers/solveset.html):
  every equation is checked over the real domain explicitly.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  schema-constrained responses still undergo independent mathematical validation.
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
