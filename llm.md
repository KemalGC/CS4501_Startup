# StrokeSense current handoff

Previous root is preserved byte-for-byte in [llm-history-2026-11-04-render-preparation.md](llm-history-2026-11-04-render-preparation.md), original blob7c139d1985d292629eb5309196af383c93ce4553. Earlier histories remain linked. Expired October schedules are not resumed.

## Current: 2026-11-04 — seven-eights evaluation and normal-library analyses (#115)

The user's current scope explicitly limits the selection to eights. It supersedes
the older ten-clip study count in the historical checkpoint below. Keep the
existing tester-link/authentication work and the live-deployment gate on main.
Work is isolated on `dev/2026-11-04-video-evaluation-study`, based on the other
model's `169fb1825443dfadbc7b58f468c396a944ddb262`. Ownership was split among
evaluation forms, normal-library import and video curation; the integration
agent owns packaging/hosting. Coordination is recorded in issue115. Do not edit
the teammate's `rowing-technique-analyzer` project or publish private footage.

### Implemented in this checkpoint

- Ten revision-bound technical judgments: identity/coxswain exclusion, stroke
  rate, catch and finish angles, drive and recovery sequence, crew timing,
  evidence alignment, usable advice, and uncertainty. Each allows an explicit
  cannot-judge/no-output answer, correction and timestamp. Optional consecutive
  catch counting computes 60*(N-1)/(last-first) on the server. It is a reviewer
  observation, never adjudicated ground truth. Existing six aspect ratings and
  five quality answers are retained, with private CSV/JSON exports and withdrawal.
- Normal `strokesense.library` imports actual saved reports, metrics, overlays
  and clips with hashes and provenance into its own managed storage. This does
  not rerun inference or invent successful job records. Existing regular job
  results are also linked from recording cards. Unchanged imports are idempotent;
  changed outputs create revisions; removal/revocation invalidates result access.
- A new private pack builder enforces 5–7 selections with rowers=8, explicit
  target boats, valid source windows and preview hashes. Completed runs must
  match the selected inference-input SHA-256. Missing results remain diagnostics.
- Hosted readiness now checks the configured count and actual required assets;
  the default/Blueprint require seven clips. Existing ten-clip installations can
  still explicitly configure ten. Declared metrics survive ZIP provisioning.
- The HTTPS browser harness requests real muted playback before checking frame
  advancement and seeking. Its synthetic ten-report compatibility fixture adds
  fifty technical judgments and five manual cadence save/reload checks. The old
  failure waited for decoded frames while only requesting metadata preload.

### Actual private footage and verification

All five supplied archives and 23 recordings were inventoried and visually
sampled. Seven distinct recordings containing eights were selected (143 seconds,
two dates), with camera transitions trimmed. The selection does not establish
seven independent crews. All seven higher-resolution cuts were actually analyzed
with YOLO11n pose ONNX and deterministic StrokeSense at 10 requested analysis FPS;
all seven reports/overlays exist. Five crew rates were reported and two withheld.
The original recordings, media, reports, manifests and provisional visual notes
remain outside public Git. No participant responses were generated.

Sparse visual inspection (two overlay frames per clip) found tracking dropouts
and a global/per-rower phase-label disagreement. Eight track records do not prove
continuous tracking or correct identities. Body angles are projected 2D estimates,
not calibrated biomechanics. Assistant visual cadence estimates are private
reference notes, not coach labels or participant answers. Preserve these limits.

PR116 targets dev-consolidated. Published head5050e5a passed all692offline test
executions in43.892s and all24hosted HTTP tests. The actual final seven-clip pack
was imported into isolated normal-library storage: seven clips, seven saved
analyses and zero jobs. All35assets matched source bytes/hashes, video ranges
worked, repeat import reused all IDs, and a real close/reopen without reimport
preserved every record and asset. No participant feedback was created.

Initial native browser CI found narrow-screen overflow in the expanded form;
the CSS now explicitly allows grid/fieldset/input shrinking and header wrapping.
The original width assertions remain. Hosted browser CI reached actual playback
but its wait_for_function helper was rejected by strict CSP; it now polls within
a supplied function while keeping the production CSP enabled. No assertion or
security check was removed. Final browser rerun and integration/deployment status
will be recorded in PR116 and issue115. Synthetic browser identities are tests,
not human study participants.

### Deployment status and next action

Render discovery reports the account integration is not connected. No Render
service, public hostname, live upload or charge was created in this checkpoint.
Finish available code/pack verification and save the clean seven-eights study;
then connect Render, inspect for an existing service, deploy the verified
development branch, provision the private pack and verify public playback,
feedback save/reload, service restart and owner exports. Only successful live
acceptance permits the user's conditional main promotion. Keep114/115 open.

See `EIGHTS_STUDY.md`, `RENDER_DEPLOY.md`, `TESTER_LINKS.md`, and
`strokesense/LIBRARY.md` for entry points. An unconnected account is not a passing
deployment, and green synthetic tests are not real-video model-accuracy evidence.

## Historical: 2026-11-04-1029-manual — tester links, report library and conditional release (#115)

User requests a sendable tester link, video reports in the main website library, and promotion to main IF everything is good. This is new conditional main authorization, not the older permanent no-main instruction. Public deployment/media/persistence are not yet verified, so do NOT call the release ready or promote main from software tests alone. No main edit has occurred in this checkpoint.

Actual start2026-11-04T10:29:04.210645-05:00, monotonic52.891936558. Checkpoint10:48:00.115516 measured1135.906seconds (18m55.906s), excluding later CI/docs/integration. Final measured closeout belongs in issue115. Topic dev/2026-11-04-1029-tester-links continues prior verified hosting head611a60b39a23d4230d47c1c8f673644860ec64a0. Inspected integration dev-consolidated e92c381f2288d2e02c4bb1a012a3e3bf2483b6a4 and main3d383110dcfcbfcb1cf7a46681c6523f6e20a4fc. Issue115 was created before new code. No PR, settings, schedules, force history, branch deletion or private media commits.

### Implemented

Owner /owner page generates/copies a signed seven-day reviewer URL, not an owner credential. /join clears the URL fragment before any fetch, validates/redeems via same-origin+CSRF POST into a Secure/HttpOnly/Strict cookie and opens /library. Consent and per-browser reviewer sessions remain required. The link is bearer access (forwardable), not individual email identity verification. Revoking the reviewer-code secret invalidates all such links; never expose owner keys in logs or chat.

New feedback_sharing.py checks token signature/expiry/origin and checks expected study size plus source video, annotation, poster and report presence. The default and Blueprint require10clips. Missing/empty files or changed catalog block link generation/redemption rather than create a knowingly incomplete invite. Readiness is file availability, NOT correctness/accuracy of supplied model reports.

Hosted / redirects to /library preserving clip queries. Every catalog entry keeps its report/diagnostic and review actions; the native browser test checks all ten report destinations instead of just opening the first report. Setup links to owner invitations. The existing six aspect assessments, five quality questions, consent, private exports, SQLite persistence and local launcher are unchanged. No model inference or new footage processing in this task.

TESTER_LINKS.md describes owner/tester flow, bearer-link limitations and final live release checks. RENDER_DEPLOY.md retains deployment prerequisites. The complete private study is supplied separately at setup; GitHub only contains code/config/tests. This session found earlier eight-video packages and source archives but did not find the complete ten-video ZIP in the runtime or returned Library ZIP listing. Do not invent its download path, substitute eight clips silently, or call it uploaded to Render. The user's saved full package or a later explicit reconstruction is still needed for actual provisioning.

### Verification observed

Before production: `python -m unittest discover -s strokesense/hosting_tests -p test_tester_links.py -v` ran10 expected failures in1.639s for missing routes/redirect/invitation behavior, not import or environment errors. Local test-only commit899b00a retained. All19 hosting tests (10new+9existing) then passed in5.616s. Remote production commit573b52590d498d84b4bf03134258aacb5cc357c1 includes tests/code together; do not describe it as a separate remote red checkpoint.

Full local `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg python strokesense/quality.py` passed654 executions in97.471s plus4existing synthetic functions. Counts include rediscovered fixtures. JS syntax and whitespace checks passed. Existing SQLite warnings were not suppressed.

Initial exact-source hosted CI41861294280 passed19HTTP tests and the previous HTTPS setup/consent/save/restore/export browser test, then FAILED the new media browser harness before its journey because FFmpeg was absent from the runner. This is an environment/test-dependency failure, not a tested successful playback and not a failed survey save. The workflow now explicitly installs FFmpeg from Ubuntu repositories; no check removed, no fake video success and no weakened timeout. Final rerun and integration status are PENDING at this documentation checkpoint; record confirmed outcomes in115.

New browser harness uses a real TLS Uvicorn server, Chrome, generated MP4 and ten unique synthetic reports. Planned checks: all10report links, source+annotated video seek, mobile width, five isolated reviewer contexts,25quality answers and5aspect answers, restore on reload, no owner exports for reviewers and no invitation token in request URLs. These are automated test identities, not five human participants or real-video model accuracy. Prior hosting tests stop/restart backend and verify persistent responses.

### Deployment blocker / next action

Render discovery still reports not installed. No Render service, real public hostname, live media upload, paid disk or charge was created. No real remote tester link is available yet; do not fabricate a strokesense-alpha.onrender.com address. CI is not actual Render verification. Keep114/115 open for live acceptance. Human review and actual study sessions remain pending. No extra email/outreach in this task.

Next action: authorize the Render connection, inspect for an existing service, deploy the verified dev-consolidated Blueprint, provision the complete private ten-video pack, then exercise the actual public invite/library/report/playback/save/restart/export flow. Only after those release conditions pass, recheck main ancestry/concurrent changes and use the user's conditional authorization for safe promotion. Do not overwrite human work or imply that code promotion itself deploys media.
