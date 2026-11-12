# StrokeSense current handoff

Previous root is preserved byte-for-byte in [llm-history-2026-11-04-render-preparation.md](llm-history-2026-11-04-render-preparation.md), original blob7c139d1985d292629eb5309196af383c93ce4553. Earlier histories remain linked. Expired October schedules are not resumed.

## Current: 2026-11-04 — shared boat cadence, simpler review and email entry (#115)

The current topic is `dev/2026-11-04-boat-cadence-trend`, based on the merged
PR116 integration head `3183f8e2f4ec662a0c80f375e7de3d8eb7726ddf`.
Ownership was split among the cadence estimator, report/review presentation,
independent cache evaluation and public Site email access. The root owns media
packaging, source integration and publication. Coordination remains in issue115.
Do not edit `rowing-technique-analyzer` or promote `main` from software checks.

The user replaced the Render destination with a public ChatGPT Site:
https://strokesense-review.kemalgcortuk.chatgpt.site/ . Its canonical source is
the existing Sites-managed repository, separate from this Python repository.
Preserve its opaque project identity and public audience. No new Render service
is needed. Publication and current browser verification are recorded in issue115.

### Current behavior

- `shared-boat-cadence-v3` fits one shared boat rate from overlapping observed
  periods. Fixed phase offsets do not imply different rowing frequencies.
  A fixed six-second neighborhood smooths observed periods; each distinct
  rower gets one local vote. A strict majority, near-tie rejection, multiple
  unique intervals per contributor, adequate overlapping time and majority
  coverage prevent a noisy rower or a short clear tail from defining the boat.
  No catches, missing strokes, harmonic corrections or gap-spanning periods
  are invented. Exact catch events, aligned cycles and five-cycle readiness
  remain separate diagnostics.
- The report headline, rower cards and overlay show the same shared rate.
  Raw rower rates remain in a collapsed diagnostic table and saved JSON.
  A withheld boat rate stays unavailable everywhere. Trend ranges are model
  min/max values, not accuracy intervals. Contributor counts are unions over
  supported windows, not claims of simultaneous agreement throughout a clip.
- Evidence snapshots, source links, curves and candidate explanations remain
  in full reports. The test review no longer asks about evidence alignment,
  evidence support or evidence-as-an-aspect. Canonical analysis data retains
  six aspects for compatibility, while the review offers five aspects.
  `technical-v2` has nine questions; `quality-v2` has four. Advice specificity
  is independent of evidence availability. Historical responses remain stored
  and exportable; they do not count as current-revision completion.
- The public Site offers email entry with no password or verification email,
  plus optional native ChatGPT sign-in. Typed email is private, self-declared
  contact information. Random browser sessions last 30 days; the same email
  in another browser never restores another participant's answers. Owner
  exports still require verified native identity. Guest withdrawal removes
  contact information, session, profile and all saved revisions. An additive
  D1 migration preserves existing responses.

### Seven-eights revision

The selected study remains seven continuous cuts, 124 seconds, with eight
target rowers per clip and the coxswain excluded. The September 9 broadside,
September 9 close and September 26 reverse recordings replaced weaker earlier
clips during the prior Site curation. Source cuts are unchanged in this revision;
boat switches were already excluded. Seven clips do not imply seven independent
crews. Source originals, pose caches and private reference notes stay outside
public Git. The selected public videos/reports are in the authorized Site.

| Clip | Shared model rate (SPM) |
| --- | ---: |
| September 9 broadside | 19.9 |
| September 9 close | 19.1 |
| October 1 second crew | 30.6 |
| September 26 reverse | Unavailable |
| October 13 daylight | 24.9 |
| October 13 close | 23.5 |
| October 13 stable side view | 27.1 |

Reverse is withheld because clear support covers only 4.10 of 12.21 seconds
with sufficient simultaneous observations (33.6%); its full clip is 20 seconds.
These are model estimates, not manually verified cadence labels. Systematic
shared tracking error remains possible, and body angles remain projected 2D.

All seven outputs were rebuilt from source/model-identity-verified pose caches;
no new detector inference was needed. All 56 raw rower cycle sequences and
measured values match their prior versions. Execution metadata correctly records
the change from four measurement workers to one. Reports and analysis revisions
are genuine regenerated outputs; no participant responses were fabricated.

The private pack is `eights-2026-11-04-v3`, catalog SHA-256
`58961a43d83702f57142c3148d3d1560e9ed90b4a1870cbfb716b7399c6af40a`.
The normal library imported seven new analysis revisions: ten registered
recordings, seventeen saved analyses and zero inference jobs. Existing rows,
recordings and analyses were retained; repeated import reuses all seven IDs.

### Verification and remaining release boundary

The frozen cadence source SHA-256 is
`b95324a44e1e2d5a6449d3ff0263a66816c88438756530f2c351ad082ff11a65`.
Full offline verification passed four standalone synthetic checks and 718
unittest executions in 48.745 seconds. Seventeen new cadence regressions,
fourteen existing cadence/measurement tests, eleven independent adversarial
probes and all seven real-cache reconstructions passed. All 24 hosted HTTP
tests passed. Python browser fixtures were updated; current CI results belong
in the PR and issue115 rather than being inferred from compilation.

The separate Site passed all sixteen protocol/export tests, TypeScript,
production builds and disposable D1 route/persistence tests covering email
isolation, expiry, tampering, owner authorization, saving/reopening, historical
responses and withdrawal. No production participant data was used for tests.
Managed preview reported a URL but refused connections; no alternate preview,
network workaround or mock production authentication was introduced. Verify
the deployed UI and record that result separately from isolated backend tests.

Retain the conditional main-release gate and open issues114/115. Human technical
review is still pending; software tests and model agreement are not coach labels.

## Historical: 2026-11-04 — seven-eights evaluation and normal-library analyses (#115)

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
