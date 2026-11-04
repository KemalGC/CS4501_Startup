# StrokeSense current handoff

Previous root is preserved byte-for-byte in [llm-history-2026-11-04-render-preparation.md](llm-history-2026-11-04-render-preparation.md), original blob7c139d1985d292629eb5309196af383c93ce4553. Earlier histories remain linked. Expired October schedules are not resumed.

## 2026-11-04-1029-manual — tester links, report library and conditional release (#115)

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
