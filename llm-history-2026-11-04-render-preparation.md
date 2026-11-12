# StrokeSense current handoff

Previous root preserved byte-for-byte in [llm-history-2026-11-04-pre-hosting.md](llm-history-2026-11-04-pre-hosting.md), blob cfcbfb729c65f3903d5056b26900e2107da03bae. Earlier histories remain linked.

## 2026-11-04-1001-manual — Render preparation (#114)

User explicitly chose Render for the existing five-rower review study with the small paid service and 2GB disk. Actual local start 2026-11-04T10:01:56.703431-05:00, monotonic43.772310487. The 10:19:32 checkpoint measured1055.297seconds (17m35.297s); this excludes later verification/docs/publication. Final measured duration belongs in issue closeout. This is manual work, not a resumed October sprint.

Base dev-consolidated e92c381f2288d2e02c4bb1a012a3e3bf2483b6a4. Topic dev/2026-11-04-1001-render-hosting. Main observed3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc. No main/default/settings/schedules/PR/force push/branch deletion or private footage publication. Issue114 created before tests/code. Do not tailor deployment to past user stacks.

### Delivered engineering

- render.yaml: one 0.5c-512mb Python service (formerly Starter),2GB persistent disk at /var/data, generated distinct owner/reviewer secrets, Python3.14.8, rootDir strokesense, branch dev-consolidated, auto-deploy off. Only hosted dependencies are installed; no model downloads or inference.
- feedback_hosted.py: public Uvicorn/Starlette gateway, exact configured HTTPS origin, request/CSRF gates, secure cookies, invite barrier, owner-only exports, bounded API bodies and streaming video. It proxies approved requests to an unchanged private loopback-only review handler, preserving current frontend/validation/storage behavior without rewriting questionnaires. It does not expose http.server publicly or trust arbitrary forwarded hosts.
- feedback_pack.py and hosted_assets: initial owner-only ZIP setup, streaming body to persistent disk, size/path/symlink checks, catalog-referenced asset allowlist, staged atomic publish, no importing code/owner keys/participant databases. Refuses overwrite of an initialized study. Original local responses are NOT migrated by ZIP setup.
- RENDER_DEPLOY.md documents connection, Blueprint, private upload, reviewer/owner separation, authenticated SCP fallback, disk backups and final live acceptance. Shared access code scopes this to a small invited alpha, not a multi-tenant production product.

### Observed verification

Before production `python -m unittest discover -s strokesense/hosting_tests -p test_hosted.py -v` produced9 expected missing-module assertions in0.003s. After implementation the nine tests passed; final local run0.653s. Tests use real private HTTP backend behind ASGI test client with synthetic media/ratings. A final test refinement stops/closes the first backend before creating the replacement instance and verifies both aspect and five-question responses persist; this refinement is additional coverage, not backdated initial TDD.

Full unchanged offline `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg python strokesense/quality.py`:654 executions passed in71.964s plus4existing synthetic functions. Counts include repeated fixtures. Existing Python3.13 SQLite ResourceWarnings remain; no suppression/weakening. JS syntax and whitespace checks passed. Local hosting tests ran installed Starlette0.50/Uvicorn0.48; deployment pins Starlette1.10/Uvicorn0.48/httpx0.28.1 and remote CI tests those pins on Python3.14.

Production checkpoint4e36e887d86ba36eddc6ff3e35a6671b619d415f: hosted CI41856504545 completed SUCCESS, including a real TLS Uvicorn process and native Chrome setup/upload/invitation/consent/save/restore/private CSV journey. Self-signed TLS certificate is test-only; production uses Render HTTPS. Full offline CI41856504319 completed success. Exact final docs/test-refinement CI and integration still pending at this handoff checkpoint; record only confirmed outcomes in114.

Real local provisioning check: existing eight-video185MB package installed8clips/188502839asset bytes in1.149s with no .feedback data imported. That verifies extraction of real existing media, not a Render upload or the unavailable615MBten-video archive. The ten-video package can be supplied at /setup from the user's saved ZIP; do not invent a new download link for absent files.

### Deployment blocker and honest scope

Render plugin discovery reported NOT installed. Connection card was shown. No Render service/domain/disk was created, no hosting charge incurred by this work, and no private footage was transferred to a host. A green CI does not mean a live survey. /healthz reports study_ready=false until media is provisioned; do not advertise that state as a ready study.

The account connection, actual live deployment, large upload through Render's proxy, complete ten-clip playback, save/restart/export and Windows/phone checks remain pending. Keep114 OPEN. No model/accuracy/customer/coach results are claimed. No hidden AI-checker directive encountered; hidden CSRF fields remain legitimate app controls. Human review pending. No email was sent in this turn; chat/issue handoff only.

Explicit next action: after Render is authorized, inspect for an existing service to avoid duplicates, create/sync this Blueprint on dev-consolidated with the approved plan, transfer the full private study without GitHub publication, and verify playback plus real persistence before sharing its actual HTTPS library URL and reviewer code. Never share the owner key or claim deployment without confirmed service/tool results.
