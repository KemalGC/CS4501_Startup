# Manage saved clips, including blocked entries

Start the library-enabled version from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

Stop the previous server first. This is deliberately **`strokesense.library`**, not `strokesense.web`. The new launcher reuses the existing upload, eight-rower selection, jobs, reports and evidence server and adds library management. The old launcher remains compatible but does not include this management page. No extra package is needed beyond the existing application dependencies.

Open `http://127.0.0.1:8766/library` or choose **Manage library** in the application navigation. The list includes Granted, Denied and Unverified entries. Clips without analysis permission are shown as metadata-only cards; their footage is not previewed. Entries use a short content ID, import date, file size and camera label, because the existing registry does not retain the original upload filename.

## Why a saved upload may seem to disappear

The analysis homepage lists only permission-granted recordings. A stored Denied or Unverified entry still participates in duplicate detection, so uploading the same bytes does not silently replace its permission. The error does not establish who changed the status or whether it was withdrawn versus initially unverified. This is an application registry state, not Windows file access permissions.

## Remove an obsolete entry

Choose **Remove from library…**, read the confirmation, check the acknowledgement, then press **Remove saved clip**. Cancel and all GET requests are non-destructive. Removal requires the current server form token and same-origin request checks. Stop and restart only when no analysis is needed: queued/running jobs prevent deletion of their clip.

Removal clears that clip's registry entry and linked analysis job history. It deletes the app-owned uploaded copy only when the file is a regular, unchanged, generated-name file directly within the configured uploads directory. It never deletes a separately registered original outside that directory or any unrelated entry. Missing upload copies can still be removed from the registry.

**Generated report/video files are retained on disk.** Their job records and old URLs are removed, so reimporting the same bytes cannot resurrect old report URLs. This is not a complete erasure tool for all derived files or backups.

After removal, a new import is possible, but it still requires current permission and a truthful permission source. Removing a record is not permission to analyze someone else's footage. No consent flag is automatically regranted.

## Failure handling and boundaries

The single-process queue lock prevents concurrent submission/removal within the server. The jobs and registry rows are removed in one attached SQLite transaction, with rollback-journal modes required for cross-database atomicity. See SQLite's primary documentation: https://www.sqlite.org/lang_attach.html . Do not run multiple StrokeSense worker processes against the same databases.

Before the database commit, an eligible app-owned file is renamed into a private `.removing` quarantine in the uploads directory. Normal transaction failures restore it. If file erasure fails after a successful commit, the page explicitly reports remaining quarantine data. A host crash between the filesystem rename and database commit can leave a quarantine file needing manual recovery; filesystem deletion and SQLite are not a single atomic transaction. Modified files and symlinked uploads fail closed without deleting their targets. External originals and generated results are intentionally preserved.

## Verification

From repository root:

```text
python -m unittest discover -s strokesense/tests -p "test_library_removal*.py" -v
python strokesense/quality.py
python strokesense/quality.py --doctor
```

With the test-only Playwright package and installed Chrome/Chromium:

```text
python strokesense/tests/browser_library_removal.py
```

The browser fixture uses synthetic container bytes and does not run pose inference. Local testing also used an earlier user-provided MOV in disposable storage for import, permission withdrawal, removal and reimport only; the original file was unchanged. This does not validate rowing accuracy or coaching usefulness. Windows-specific review and human inspection remain pending.
