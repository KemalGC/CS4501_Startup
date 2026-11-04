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

## Reopen saved code analyses in the normal app

The library now shows the latest analysis attempt and latest completed report
for each permitted recording. The report, stroke/angle evidence, evidence
metrics JSON, analysis workspace and available annotated video can be opened
from its card. Failed or running attempts remain visible without hiding an
earlier completed report. Missing or modified report files are explicitly
unavailable.

The curated eights study can also be imported into this normal application.
Its source previews and precomputed output are copied into managed local
storage. Importing does **not** run pose inference, create completed queue jobs,
or assert that a model result is correct. Study cards show the saved status,
import date, exact analysis version and analyzed time window. Their detail page
includes the recording, real available report/snapshots, metrics JSON, annotated
video and the study's stated findings for stroke rate, body angles, tracking,
sequencing, timing and evidence. Missing findings remain unavailable.

From the outer `strokesense` directory, after extracting the private review ZIP:

```powershell
python -m strokesense.library --study-pack "C:\path\to\StrokeSense-Eights-Review\study" --permission-source "User supplied these rowing recordings and authorized this local study" --port 8766
```

Use a truthful permission source appropriate to the recordings. The pack path
can identify the directory containing `catalog.json` or that file itself. Open
`http://127.0.0.1:8766/library`. The seven selected study clips appear as named
cards; the importer itself remains compatible with other permitted studies.
Do not run another library server against the same databases at the same time.

On later launches, use the same storage settings and omit `--study-pack`:

```powershell
python -m strokesense.library --port 8766
```

The copied recordings and saved outputs still work after the original review
pack is moved. Repeating an unchanged import reuses the same saved-analysis IDs.
A changed report, metrics file, summary or analysis version creates a separate
revision and preserves earlier output. If a previously imported owned output
is missing or modified, importing the verified pack creates a fresh revision.

For explicitly located storage, use all four settings consistently on import
and subsequent launches:

```text
python -m strokesense.library --study-pack /path/to/study/catalog.json --permission-source "User authorized these private study recordings" --registry-db /path/to/local-data/video_registry.sqlite3 --jobs-db /path/to/local-data/analysis_jobs.sqlite3 --results /path/to/local-data/jobs --uploads /path/to/local-data/uploads --port 8766
```

### Import format and integrity

The JSON manifest uses `schema_version: 1` and a nonempty `clips` array. Each
clip requires `id`, `title`, `duration`, `video` and `analysis.version`.
`analysis` may include `status`, `method`, `window` (`start`, `end`), `note` and
`aspects`; the current study builder supplies all of these. `group_id`,
`provenance`, `report`, `metrics`, `annotated` and `poster` are optional. All file
paths are relative to the manifest directory. A field pointing to a missing
file is an invalid pack; omit fields for outputs that were never produced.
An explicit diagnostic HTML report is also supported and retains its
`analysis.status: "unavailable"` label.

The importer validates the pack before copying. It rejects path traversal,
symlinked assets, unsupported formats and oversized output. Limits are 150 MiB
per recording or annotated video, 32 MiB per report, 16 MiB per metrics file,
and 4 MiB per poster. HTML reports must be self-contained, as StrokeSense's
standard reports are: snapshots and plots are embedded data URLs. The browser
serves reports under the existing sandboxed report policy.

Source bytes and copied artifacts are bound by SHA-256. Opening any saved
analysis or asset checks the recording's current registration and permission;
asset reads also verify the requested bytes. Changed/missing recordings or
outputs fail closed. A duplicate recording with denied or unverified
permission cannot be regranted by study import. Provenance remains in the
private database; absolute source/storage paths are not exposed by these
browser routes.

Removing a clip also removes its saved-study analysis mappings in the same
registry/job removal transaction. Old saved-analysis URLs remain invalid after
reimport, and generated outputs are retained on disk under the existing removal
policy. The importer uses a separate `library_saved_analyses` table and does not
change the jobs schema version or the queue's success/withholding invariants.

### Programmatic import and verification

For packaging scripts that already own the queue lifecycle:

```python
from strokesense.study_library import import_study_pack

records = import_study_pack(
    jobs,
    "/path/to/study/catalog.json",
    upload_dir="/path/to/local-data/uploads",
    permission_source="User authorized these private study recordings",
)
# Each record has analysis_id, clip_id, study_clip_id, and reused.
```

Focused regression checks from repository root:

```text
python -m unittest discover -s strokesense/tests -p "test_study_library.py" -v
python -m unittest discover -s strokesense/tests -p "test_library*.py" -v
```

These tests exercise storage reload, idempotent import, independent revisions,
actual result bytes, missing/modified output, source changes, revoked permission,
range requests, route containment and removal/reimport over real local HTTP.
They use synthetic files and do not establish model accuracy. Validate the
actual seven eights clips and their generated reports separately.
