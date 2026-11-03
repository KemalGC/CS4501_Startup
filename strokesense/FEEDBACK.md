# StrokeSense athlete review website

A separate, private review application in the existing Python package. It consumes saved StrokeSense outputs; reviewers do not rerun an expensive model. No additional web framework, cloud service, analytics library, or account system is required.

## Run

Use Python 3.10+ from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -m strokesense.feedback --pack "C:\path\to\private-study\study" --port 8767
```

A ready-to-run private study bundle can also include `run_review.py` and the small standalone app package. That launcher needs only Python's standard library. Open the **Rower review** URL printed by the server. The separate **Owner dashboard** URL contains a secret key in its fragment; keep it private. Do not share a screenshot of that key.

This release binds only to `127.0.0.1`. It is for supervised local reviews on the host computer, NOT an internet-hosted or remote participant service. A localhost URL does not work from a teammate's device. Public or LAN deployment requires a separately authorized authenticated HTTPS deployment and appropriate footage permission; no footage has been published by this feature. Do not simply expose this development server to the internet.

## Reviewer workflow

1. Choose rower, coach, coxswain or observer, optionally give an experience band, and explicitly consent. No name/email is collected. A random reviewer ID is not an authenticated identity; one person creating several sessions can bias results.
2. Choose a recording. Original footage, model overlay (when available), source-window disclosure and saved report appear alongside six aspect-specific review tabs.
3. Rate **usefulness** and **perceived accuracy** separately from 1 to 5. `Cannot judge` and `No applicable output` are not low-accuracy scores and are excluded from the numeric mean. When an aspect has no output, numeric accuracy is disabled. A failure message can still be reviewed for usefulness.
4. Add a specific comment and optional source timestamp. The timestamp button converts an annotated segment's time back to the original source-video time.
5. Save each aspect. Reloading the same browser session restores saved responses. Editing a response updates it; it does not create a new participant. Feedback is bound to an exact analysis/display revision.
6. Finish the session before another participant uses the computer. That clears the reviewer cookie and any owner-dashboard session key, but keeps saved feedback. `Withdraw my feedback` instead deletes that session and all its responses. Once its cookie is gone, the participant cannot self-withdraw through that session. The local study owner controls retention of the database and exports.

Keep the owner dashboard in a separate private tab/profile away from participants to avoid showing prior responses and introducing social influence. Recruit actual participants; there are no seeded responses, testimonials or fabricated customer results.

## Owner results and data

`study/.feedback/reviews.sqlite3` holds consent timestamps, role/experience, pseudonymous reviewer IDs and versioned per-clip/per-aspect responses. Raw session tokens are not stored in SQLite. `study/.feedback/owner.key` protects summary/export endpoints. Both are private local study state; do not commit them. Back up the database only as needed and delete it when the study's retention period ends. Sharing a completed study directory may expose the raw feedback; distribute a clean pack without `.feedback`.

The owner view shows response counts, valid-rating denominators, means, cannot-judge counts and not-applicable counts. CSV/JSON contain timestamped comments and per-response data for analysis. CSV text that could become a spreadsheet formula is escaped. These ratings measure perceived accuracy/usefulness, NOT labeled detection precision/recall or validated biomechanics. A small or self-selected sample is not representative customer validation. Paired encodings of one recording must not be treated as independent clips.

## Private study manifest

`catalog.json` has `schema_version: 1` and a `clips` list. Each clip includes a stable `id`, display `title`, recording `group_id`, finite source `duration`, relative `video` path, optional `poster`, `report` and `annotated` paths, and an `analysis` object with a revision and all six aspects. File paths must remain inside the pack. Only manifest-listed assets can be served. Existing HTML reports run in a script-disabled sandbox. Source footage and original metrics stay out of GitHub.

Use `strokesense.feedback_prepare.summarize_metrics(metrics, start=..., end=..., note=...)` to map an existing `metrics.json` to the six aspects and a content-bound revision. It preserves absent results rather than creating fake rates, posture scores or timing. The evidence view distinguishes actual pose-model outputs plus deterministic scoring from unexecuted LLM analysis.

Browser preview derivatives in the supplied study pack are silent H.264 MP4 at 1280 pixels wide/24 fps. Their source recordings were used for inference. Each analysis window is disclosed; the entire video is not claimed analyzed when only an excerpt was processed. Derivative video compression can affect visual judgment, so retain originals for fine-grained annotation work.

## Verification

```text
python -m unittest discover -s strokesense/tests -p "test_feedback*.py" -v
python strokesense/quality.py
python strokesense/tests/browser_feedback.py
```

The last command needs Chrome/Chromium and test-only Playwright; it uses synthetic video and an isolated temporary database. It checks consent, rating submission, reload/resume, desktop/mobile width, private export and withdrawal. Offline tests check session isolation, versions, bounds, path traversal, media range/HEAD, consent/CSRF, formula-safe exports and no-results handling. These are software tests, not human customer feedback or model-accuracy evidence.
