## 2026-11-04 — name + consent and one-video submissions (#117)

Manual request, not an October sprint run. Base: `dev-consolidated` 3183f8e2f4ec662a0c80f375e7de3d8eb7726ddf. Topic: `dev/2026-11-04-1400-guest-video-submissions`.

**Story**: As a rower, I want to use the public study link without a login, write my name, consent, review and submit one video, and optionally continue to other clips, so partial participation is usable. Explicitly require a saved response for the selected clip/revision before submission, but never force all seven/eights. Preserve existing six aspect, five quality and ten technical forms and owner privacy.

**TDD**: Initial new test `python -m unittest discover -s strokesense/hosting_tests -p test_guest_video_submission.py -v` observed 6 feature-missing failures (no accessible bootstrap without reviewer code). Subsequent test-first coverage added migration, partial/idempotent/quality-only/technical-only/second-video/CSRF/owner/withdraw/restart checks. All hosted targeted tests now pass locally; full offline and browser outcomes recorded separately, without calling synthetic fixtures actual testers.

**Implementation**: additive `sessions.display_name` and `video_submissions` database migration; real-name validation with private owner exports; public name+consent hosted gateway with exact origin/CSRF and unchanged owner key controls. Per-video receipt keyed by (reviewer, clip, analysis revision), independent of other videos; visible Submit video confirmation, optional continuation and owner CSV/JSON export. Legacy sessions retained. No video data uploaded to public GitHub; no Render deployment or real participant validation claimed.

**Remaining**: complete real Chrome on exact remote tree, full CI, Windows/Render deployment, private study upload, external mobile/restart checks, human test sessions and coach accuracy review. The user earlier conditionally authorized main promotion only after live tests, so keep main unchanged until then. No hidden AI checker directives observed in inspected materials; normal hidden form security fields are not such directives.
