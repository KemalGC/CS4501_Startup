# Send one reviewer link to the five alpha testers

This feature requires a deployed HTTPS service and the complete private study.
There is no working public URL until those are actually provisioned. A passing
GitHub workflow is not a Render deployment. See RENDER_DEPLOY.md for setup.

## Owner flow

1. Deploy the Blueprint from dev-consolidated after authorizing Render. Review
   the existing approved small-service/2GB configuration; avoid duplicate services.
2. On the service's real HTTPS address, open `/setup`, authenticate with the
   private `STROKESENSE_OWNER_KEY` from Render Environment, and upload the FULL
   seven-video **eights-only** study package. Do not publish videos or credentials to GitHub.
3. Open `/owner`, enter the owner key privately, and choose **Generate tester
   link**. The current configuration requires seven recordings, seven saved reports/diagnostics,
   original playback assets, declared model overlays, and posters before issuing a link.
   A diagnostic explicitly stating that no analysis was produced may omit an overlay.
   Missing files or a changed catalog block it. This is file readiness, not
   independent model accuracy or assurance that arbitrary reports describe
   the correct recording.
4. Click **Copy tester link** and send only that reviewer invitation to the
   five intended testers. Never send the owner dashboard link or owner key.

## What the tester sees

The link opens the hosted Reports library after exchanging a signed invitation
for a secure cookie. Testers then consent and receive separate reviewer sessions.
The site requires no Python, Ollama, installation, model download or new inference.
Each card offers **Open report** (or diagnostic) and **Review video** for that
specific recording. Reviewers can switch source/annotated playback, inspect the
saved report, complete six aspect assessments, ten technical judgments and five
report-quality questions, and reload without losing saved answers. Optional
manual cadence uses consecutive catches of the same visible rower. Owner
exports remain private; technical results have their own CSV and JSON exports.

The hosted `/` now redirects to `/library`; old `/?clip=...` links retain their
clip selection. Local-only review launchers remain unchanged. The main library
shows catalog-backed reports rather than manufacturing values or new diagnoses.

Invitations expire after seven days. The token is in a URL fragment, not its
query, and the page removes it from browser history before redeeming it by POST.
Anyone possessing the link can enter until expiry; this is bearer access, not
individual email/identity verification. Send it only to the invited testers.
Changing the reviewer-code secret invalidates existing links/access cookies,
without deleting saved feedback. Keep backups before changing live configuration.

## Actual release checks still required

After setup, test the real public domain from another device/network. Verify all
seven actual eights videos, annotations and reports; save an aspect, all five
quality answers, all ten technical judgments and a manual count, restart the Render service, then confirm restored responses and
owner exports. Withdraw synthetic test responses before collecting real data.
The source preparation and test fixtures do NOT complete this live acceptance.

The user has conditionally authorized promotion to main if everything is good.
Until real hosted assets/access/persistence are verified, keep the tested code
on dev-consolidated and leave main unchanged. Do not resume any old automation.
A Git update does not contain the private media and cannot make an empty hosted
study complete. Use the current `StrokeSense-Eights-Review.zip` and set
`STROKESENSE_EXPECTED_CLIPS` to its actual seven clips. Existing older studies
can retain their explicitly configured count and their participant responses.

## Reproducible software checks

```sh
python -m unittest discover -s strokesense/hosting_tests -p 'test_*.py' -v
python strokesense/hosting_tests/browser_tester_links.py
python strokesense/quality.py
```

The new HTTP tests cover expiry/tampering/origin/owner checks, ten report mappings,
missing assets, independent reviewer data and main-library routing. The browser
harness runs a real TLS Uvicorn process and Chrome against generated MP4 media,
ten synthetic reports and five isolated browser contexts. It checks playback,
seeking, report navigation, ratings, reload and private exports. These are not
five human participants, real-video analysis or a live Render host. FFmpeg is
explicitly installed on the CI runner to generate the playback fixture; a missing
dependency must fail the test rather than silently skip media verification.
