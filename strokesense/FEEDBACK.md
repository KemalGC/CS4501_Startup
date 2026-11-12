# StrokeSense athlete review website

A separate, private review application in the existing Python package. It consumes saved StrokeSense outputs; reviewers do not rerun an expensive model. No additional web framework, cloud service, analytics library, or account system is required.

## Run

Use Python 3.10+ from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -m strokesense.feedback --pack "C:\path\to\private-study\study" --port 8767
```

A ready-to-run private study bundle can also include `run_review.py` and the small standalone app package. That launcher needs only Python's standard library. Open the **Rower review** URL printed by the server. The separate **Owner dashboard** URL contains a secret key in its fragment; keep it private. Do not share a screenshot of that key.

The command above binds only to `127.0.0.1` for supervised local reviews on the host computer. A localhost URL does not work from a teammate's device. For the HTTPS gateway and Render deployment, use the separate instructions in [`RENDER_DEPLOY.md`](../RENDER_DEPLOY.md). Do not expose the loopback development server directly to the internet; the hosted gateway provides the deployment boundary and uses the study database on its persistent storage.

## Reviewer workflow

1. Choose rower, coach, coxswain or observer, optionally give an experience band, and explicitly consent. No name/email is collected. A random reviewer ID is not an authenticated identity; one person creating several sessions can bias results.
2. Choose a recording. Original footage, model overlay (when available), source-window disclosure and saved report appear alongside five aspect-specific review tabs.
3. Rate **usefulness** and **perceived accuracy** separately from 1 to 5. `Cannot judge` and `No applicable output` are not low-accuracy scores and are excluded from the numeric mean. When an aspect has no output, numeric accuracy is disabled. A failure message can still be reviewed for usefulness.
4. Add a specific comment and optional source timestamp. The timestamp button converts an annotated segment's time back to the original source-video time.
5. Save each aspect. Reloading the same browser session restores saved responses. Editing a response updates it; it does not create a new participant. Feedback is bound to an exact analysis/display revision.
6. Complete the nine technical judgments below the aspect tabs: the target eight and rower identities (excluding the coxswain), shared boat stroke rate, catch/finish body angles, drive/recovery sequence, crew timing, specific actionable advice, and uncertainty. Hidden seats do not prove that all eight rowers were detected. Add a separate timestamp/correction for any criterion. `Correct`, `Partly correct`, `Incorrect`, `Cannot judge`, and `No applicable output` remain categorical judgments; unjudgeable answers are never converted to wrong answers. When no output exists for a criterion, the three correctness judgments are disabled and rejected by the server.
7. Optionally count consecutive catches for one identifiable rower. Supply total catches, first/last catch time and a non-identifying seat/clothing reference. The server derives strokes per minute as `60 × (catches − 1) / (last − first)`. For example, five catches over eight seconds produce 30 spm. Use one identifiable rower and the same time interval as the shared boat-rate claim before comparing. Early or late catches are timing differences, not separate assigned rowing rates. A manual count is stored as an **unverified reviewer observation**, not accepted as ground truth and not automatically used to score the model. Body-angle judgments must account for the image-plane view and visible joints.
8. Complete the four overall report-quality questions: clarity, specificity, completeness and actionability. These remain separate from the five aspect ratings and the technical checklist. Evidence remains available in the full report; the review form does not ask participants to score it.
9. Finish the session before another participant uses the computer. That clears the reviewer cookie and any owner-dashboard session key, but keeps saved feedback. `Withdraw my feedback` instead deletes that session and all its responses. Once its cookie is gone, the participant cannot self-withdraw through that session. The local study owner controls retention of the database and exports.

Keep the owner dashboard in a separate private tab/profile away from participants to avoid showing prior responses and introducing social influence. Recruit actual participants; there are no seeded responses, testimonials or fabricated customer results.

## Owner results and data

`study/.feedback/reviews.sqlite3` holds consent timestamps, role/experience, pseudonymous reviewer IDs and versioned per-clip/per-aspect responses. Raw session tokens are not stored in SQLite. `study/.feedback/owner.key` protects summary/export endpoints. Both are private local study state; do not commit them. Back up the database only as needed and delete it when the study's retention period ends. Sharing a completed study directory may expose the raw feedback; distribute a clean pack without `.feedback`.

The owner view shows response counts, valid-rating denominators, means, cannot-judge counts and not-applicable counts. CSV/JSON contain timestamped comments and per-response data for analysis. CSV text that could become a spreadsheet formula is escaped. These ratings measure perceived accuracy/usefulness, NOT labeled detection precision/recall or validated biomechanics. A small or self-selected sample is not representative customer validation. Paired encodings of one recording must not be treated as independent clips.

## Technical evaluation storage and integration

The `technical-v2` questionnaire uses a separate `technical_evaluations` table in the same consent-owned SQLite database. Its key is `(reviewer_id, clip_id, analysis_version, questionnaire_version)`. An edit atomically replaces that participant's assessment for that exact revision. New analysis versions retain the older answers separately; the browser restores only the version currently shown. Installation and ordinary saves do not rewrite previous aspect/quality feedback. Withdrawing the session cascades to all three questionnaires.

`GET /api/evaluation?clip=<id>` returns only the current session's assessments. `POST /api/evaluation` accepts exactly `clip_id`, `analysis_version`, `questionnaire_version`, `answers`, `stroke_measurement`, and `comment`. Each of the nine `answers` has exactly `verdict`, optional-valued `timestamp_seconds`, and `comment` (up to 500 characters). `stroke_measurement` is either `null` or `{catch_count, first_catch_seconds, last_catch_seconds, rower_reference}`; clients cannot override the derived rate. Times must be finite and inside the displayed clip, the catch count must be an integer from 2–1000, and the last catch must follow the first. For a trimmed study clip, playback timestamps start at zero; original recording offsets belong in its provenance. A separate overall comment permits 2,000 characters. Requests require the existing reviewer cookie, same-origin validation and CSRF token.

Owner-only `/api/owner/evaluation.json` exports revision-bound assessments, question definitions and categorical response counts. `/api/owner/evaluation.csv` exports one criterion per row, retaining evidence timestamps, comments and manual observation fields. Manual fields repeat across that assessment's criterion rows; deduplicate by the full assessment key before counting observations. Text is protected against CSV formula execution. These exports explicitly identify participant judgments and manual measurements; they provide no percentage model-accuracy claim. The owner summary shows technical-assessment and manual-observation counts alongside the original aspect statistics.

A hosted gateway must permit the new `/evaluation.js`, `/evaluation.css`, `/api/evaluation` GET/POST routes and owner-only `/api/owner/evaluation.json`/`.csv` routes. The catalog schema keeps all six `ASPECTS` IDs, including evidence. Public bootstrap and aspect validation use five `REVIEW_ASPECTS`, excluding evidence. `technical-v2` removes `evidence_alignment`; `actionable_specificity` is an overall advice question. `quality-v2` removes `evidence_support`. Historical responses retain their original questionnaire versions and evidence answers in owner exports, and only current question IDs restore into the public form. Bootstrap includes `evaluation_version` and `evaluation_questions`.

## Private study manifest

`catalog.json` has `schema_version: 1` and a `clips` list. Each clip includes a stable `id`, display `title`, recording `group_id`, finite source `duration`, relative `video` path, optional `poster`, `report` and `annotated` paths, and an `analysis` object with a revision and all six aspects. File paths must remain inside the pack. Only manifest-listed assets can be served. Existing HTML reports run in a script-disabled sandbox. Source footage and original metrics stay out of GitHub.

Use `strokesense.feedback_prepare.summarize_metrics(metrics, start=..., end=..., note=...)` to map an existing `metrics.json` to the six aspects and a content-bound revision. It preserves absent results rather than creating fake rates, posture scores or timing. The report evidence distinguishes actual pose-model outputs plus deterministic scoring from unexecuted LLM analysis. The rate aspect uses only a defensible shared boat estimate and is unavailable when none is released. Raw per-track interval estimates remain diagnostic evidence in the full report and metrics; they are not different rowing rates assigned to crew members.

Browser preview derivatives in the supplied study pack are silent H.264 MP4 at 1280 pixels wide/24 fps. Their source recordings were used for inference. Each analysis window is disclosed; the entire video is not claimed analyzed when only an excerpt was processed. Derivative video compression can affect visual judgment, so retain originals for fine-grained annotation work.

## Verification

```text
python -m unittest discover -s strokesense/tests -p "test_feedback*.py" -v
python strokesense/quality.py
python strokesense/tests/browser_feedback.py
python strokesense/hosting_tests/browser_tester_links.py
```

The browser commands need Chrome/Chromium and test-only Playwright; they use synthetic video and isolated temporary databases. The HTTPS tester-link harness also needs the hosting dependencies described in `RENDER_DEPLOY.md`. The browser checks cover consent, rating submission, reload/resume, desktop/mobile width, private export and withdrawal. Offline tests check session isolation, analysis/questionnaire revisions, exact criterion schemas, finite timestamp bounds, manual-cadence interval arithmetic, additive persistence, cross-questionnaire withdrawal, path traversal, media range/HEAD, consent/CSRF, formula-safe exports and no-results handling. The HTTPS tester-link browser harness additionally exercises the nine-criterion technical form, manual-rate save/restore and owner export. These are software tests, not human customer feedback or model-accuracy evidence.
