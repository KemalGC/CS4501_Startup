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
python -m pip install -r requirements-media.lock
python -m pytest -q
python -m proofgrade.evaluate --split all
python -m proofgrade.demo
node --check proofgrade/static/app.js
node --check proofgrade/static/teacher.js
node --check proofgrade/static/image-upload.js
npm ci
npx playwright install chromium
npm run test:browser
```

On Linux, Playwright may need `npx playwright install --with-deps chromium`.
`npm run test:browser` creates a temporary account/database, starts and stops its
own server, and checks both flows, including browser image preparation/upload,
mocked AI transcription, source review,
partial credit, approval, exports, targeted practice, revision invalidation,
mobile overflow, and browser errors. It writes screenshots to ignored
`test-results/`. An already running student app can also be tested with
`PROOFGRADE_TEST_URL=http://127.0.0.1:8000 node tests/browser-smoke.cjs`.

The browser server deliberately blocks Pillow/PDFium imports and replaces only
the model's HTTP transport with synthetic fixtures. PNG/JPEG preparation,
orientation, resizing, white transparency background, PNG source decoding and
the review/grade workflow run normally. This is integration coverage, not an
OCR-quality evaluation. Windows/Python 3.14 CI installs no Pillow/PDFium packages.

CI runs Python 3.11/3.12 with optional media, regression evaluation, offline fault injection,
JavaScript syntax, both Chromium flows, and a Docker runtime smoke check.
Screenshots are uploaded as `teacher-browser-previews`. On 2026-10-20 these
checks passed for the teacher workspace and the screenshots were inspected.
Local Chromium launch is blocked in the authoring sandbox; CI provides the
browser execution evidence. No API credentials are used in tests.

`requirements.lock` pins the default runtime; `requirements-media.lock` pins the
optional PDF/dataset libraries (also available as `.[media]`). `package-lock.json`
pins browser test dependencies. Update pins intentionally. The current httpx-backed TestClient
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

The default image supports JPG/PNG photos without the optional native media
libraries. To build a PDF-enabled image, use
`docker build --build-arg WITH_MEDIA=true -t proofgrade .` and set
`-e PROOFGRADE_PDF_UPLOADS=true` when running it. Both installation and explicit
enablement are required for PDFs.

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

## Windows: a native library is blocked

`ImportError: DLL load failed while importing _imaging: An Application Control
policy has blocked this file` means the operating system refused to load Pillow's
native image code. Installing the Python package can succeed even when loading
one of its binaries is blocked. This message alone does not identify which policy
or binary dependency caused the block; upgrading pip does not resolve that policy.

The standard photo workflow does not load Pillow or PDFium at all. A current
browser decodes the JPG/PNG, applies orientation, and sends bounded RGB pixels.
The server checks dimensions/byte counts and builds a metadata-free PNG using
standard-library `struct`, `zlib`, and `binascii`. This removes the dependency on
third-party image DLLs; it does not mean Python itself uses no native code.
Photo upload, source review, optional AI extraction, grading, and exports work
without changing Windows security settings. Existing source pages still work.

After pulling the fix on `dev`, restart from the same project directory and
virtual environment; an already created teacher account does not need recreation:

```powershell
git fetch origin
git switch dev
git pull --ff-only origin dev
python -m pip install -r requirements.lock
python -m pip install -e .
$env:PROOFGRADE_PDF_UPLOADS="false"
python -m uvicorn proofgrade.api:create_app --factory --reload
```

Keep using the same activated environment, project directory and teacher database.
An existing installation may still contain Pillow/PDFium; they do not need to be
uninstalled because the photo path never imports them. Refresh the browser after
restarting. Open `/teacher`, create/select an assignment, add a JPG/PNG homework
photo, and open **Review**. Review the saved image for legibility.

For automatic handwriting transcription, stop the server and configure these
variables in that PowerShell session before restarting:

```powershell
$env:PROOFGRADE_TEACHER_AI="openai"
$env:OPENAI_API_KEY="<your API key>"
$env:PROOFGRADE_VISION_MODEL="<your vision model with Structured Outputs>"
python -m uvicorn proofgrade.api:create_app --factory --reload
```

Enter the key locally; never commit it or put it in frontend code. In **Review**,
select **Extract handwriting with AI**, compare/correct every equation, confirm
the transcript, then approve the suggested grades. A model and API key are still
required for automatic reading; without them, enter equations beside the photo.
AI transcription accuracy has not been measured on real homework.

PDF decoding and the MathWriting rendering command still use the optional media
extra. If you need those, use a machine where the libraries are allowed or ask
the policy administrator to review the blocked binary. The photo workflow does
not need the restriction removed. See
[Microsoft's troubleshooting guide](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/appcontrol-debugging-and-troubleshooting).

Windows/Python 3.14 CI covers startup, browser-pixel intake, grading, and simulated native
import blocks. It cannot reproduce the specific policy installed on a user's PC.

## Technical references

- [SymPy parsing warning](https://docs.sympy.org/latest/modules/parsing.html): raw input uses a restricted parser.
- [SymPy solveset](https://docs.sympy.org/latest/modules/solvers/solveset.html): explicit real solution sets.
- [OpenAI vision inputs](https://developers.openai.com/api/docs/guides/images-vision).
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
- [Browser image decoding and EXIF orientation](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap).
- [Canvas pixel data](https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/getImageData).
