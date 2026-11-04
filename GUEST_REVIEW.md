# StrokeSense: no-login, named, video-by-video review

**Participant experience:** visit the Render service's `/library` HTTPS URL.
No code, signup, or password is required. Enter a name (2–80 characters),
select rowing experience, and explicitly consent. Choose any recording. The
full report and original/model overlay can be reviewed on the same page.

Every recording is independent. A reviewer may save a single aspect's
usefulness + perceived accuracy, or the full five-question quality section,
or the full ten-criterion technical checklist. Save the edited form(s), then
click **Submit this video's feedback**. A receipt records the exact clip,
analysis revision and counts of saved responses. Completing the other six
(or more) recordings is entirely optional. The **Review another video** and
**Finish reviewing** controls follow a successful submission.

**Privacy and security:** real participant names are personally identifying.
They are only in the private SQLite database and organizer-only CSV/JSON;
no name is required in a URL. Existing anonymous sessions migrate without
deletion and retain an empty historical name. The owner key remains mandatory
for setup and export, HTTPS Host/Origin checking and CSRF remain, video assets
still require a consented session, and reports retain sandbox restrictions.
No account means there is no independent proof of the typed name and anyone
with the public URL can enroll. Only host footage licensed/authorized for this
scope. Owner should document retention and export backups.

**Acceptance:** `python -m unittest discover -s strokesense/hosting_tests -p
 'test_*.py' -v`, `python strokesense/hosting_tests/browser_hosted.py`,
`python strokesense/hosting_tests/browser_tester_links.py`, plus the existing
full offline and browser workflows. Browser fixtures are synthetic. Real
Render deployment and real participant testing must be verified separately.

**Not yet hosted:** adding source code to GitHub does not create a Render
service. Account connection, persistent study ZIP transfer, a working HTTPS
link and a save/restart/export check are required before sharing.
