# StrokeSense — markerless rowing technique analysis

Drop in ordinary side-on video (erg or launch footage of a full crew). StrokeSense finds every rower,
maps their joints with a pretrained pose model (no markers, no sensors), splits the footage into
strokes, and flags technique faults with coaching cues. For crews it also measures **who is early or
late at the catch**.

Outputs (by default in `results/<video stem>--<source-path hash>/`):

| File | What it is |
|---|---|
| `<video>_annotated.mp4` | The clip with each rower's skeleton, seat label, live body angle and stroke rate |
| `report.html` | Coaching report: per-seat score, top faults + cues, catch/finish snapshots, sequencing chart, crew timing chart |
| `metrics.json` | Every stroke's numbers, for further analysis |
| `detections.npz` | Versioned cached person detections (re-runs skip pose inference when the input/settings/model match) |

## Setup (Windows, PowerShell)

Everything stays on Z:.

```powershell
cd Z:\
# copy/unzip the strokesense folder to Z:\strokesense first
cd Z:\strokesense
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No PyTorch or GPU needed — the pose network runs through onnxruntime on the CPU. The model file is in
`models/` (it is downloaded automatically if missing).

For browser-playable output video, have `ffmpeg` on PATH (`winget install Gyan.FFmpeg`); without it the
video is written as `.webm`, which Chrome/Edge also play.

## Run

```powershell
# whole clip
python -m strokesense.cli "Z:\footage\IMG_3945.MOV"

# 30 s starting 5 s in (faster, and skips the launch turning around)
python -m strokesense.cli "Z:\footage\IMG_3945.MOV" --start 5 --duration 30

# erg / single sculler: analyse just the clearest rower
python -m strokesense.cli "Z:\footage\erg.mp4" --single
```

Useful flags: `--tiles auto|none` (`auto` finds a person band and tiles it, `none` uses the whole frame),
`--fps 30` (finer catch-timing resolution, ~2× slower), `--fresh` (ignore the cached pose).

CLI numeric options are validated **before analyzing any footage**: `--start`
requires finite nonnegative seconds (zero is valid), `--duration` requires
finite positive seconds when supplied (omit it for a whole-clip run), and
`--fps` must be finite and positive. Bad values such as `nan`, `inf`,
negative time, or zero FPS fail with an argparse error (exit code 2)
instead of invoking inference. Valid fractional rates/times remain supported.

Speed: pose detection is the slow step — about 7 minutes for a 37 s 1080p clip of a full eight on a
2-core CPU (faster with more cores). It is cached in `detections.npz`, so re-running the analysis or
re-rendering takes ~2 minutes.

## Private local video registry (Alpha)

Index an existing local file in a SQLite database with SHA-256, a stable clip
ID, source path/size, a permission claim, optional rights/consent provenance,
recording group, evaluation split, camera/FPS, and initial unreviewed status.
**Import does not copy, upload, decode or analyze video.**

From `strokesense/`, for example:

```powershell
python -m strokesense.registry import "Z:\footage\crew.mp4" --group practice-2026-10-27 --split development --camera side-on --fps 30
python -m strokesense.registry list
# Optional: deliberately show local source paths
python -m strokesense.registry list --show-path
```

The default database `strokesense/results/video_registry.sqlite3` is Git
ignored. Use `--db PRIVATE_PATH` to override. Protect the database and video
storage locally: SQLite is not encrypted and stores sensitive paths and
provenance. Ordinary `list` and import output omit source paths/provenance.

Permission defaults to `unverified`. Only claim `--permission granted
--provenance "documented consent reference"` after obtaining actual rights;
the registry cannot verify consent. `denied` is also supported. Identical
content yields `created: false` and cannot silently overwrite existing
permission, session/split or other explicit metadata. Non-`unassigned`
evaluation splits require a `--group`; clips in a group cannot be divided
between development and held-out sets.

This is only a local catalog: the existing analysis CLI does **not** consult
registry permission status, and group IDs do not independently prevent athlete
or adjacent-frame leakage. Neither media validity nor real-video accuracy is
measured here. Source modification after hashing, malicious symlink changes,
and consent enforcement in the analysis API remain future engineering work.

## How it works

1. **Pose** — YOLO11-pose (ONNX) finds every person and 17 joints per frame. The boat's band of the
   frame is covered with full-resolution tiles so rowers ~100 px tall are still found.
2. **Crew tracking** — the cox (facing the other way) is removed, then each seat is tracked as a slot:
   on frames where the whole crew is detected the left-to-right order says who is who; otherwise
   each slot is matched to the nearest rower after compensating for the camera panning. Seats are
   named from the rowing direction (rowers face the stern, so the seat nearest the cox is stroke).
   For a single rower (`--single`) a generic tracker keeps the clearest rhythmic track.
3. **Rower-centric frame** — every joint is expressed relative to the hip and scaled by torso length,
   so boat motion and camera panning cancel out. Feet are usually hidden by the hull, so leg drive is
   measured from the thigh angle rather than the knee.
4. **Strokes** — catch = hands at full reach with knees up (each cue weighted by how cleanly rhythmic
   it is, so a hidden wrist can't derail it); finish = the opposite extreme. Slow drift in the body
   angle (the launch changing its viewing angle) is removed. Arm and shin faults are only judged
   when those joints are tracked reliably.
5. **Faults** — per stroke, then kept if they recur in ≥25% of strokes:

| Fault | Rule (side-on 2D) |
|---|---|
| Not enough body angle at catch | body angle at catch < 12° forward |
| Lunging / over-reaching | body angle at catch > 42° |
| Over-compressed | shins > 12° past vertical (only when ankles are visible) |
| Too much layback | body angle at finish < −32° |
| Upright finish | body angle at finish > −3° |
| Shooting the slide | body angle closes > 5° during first 30% of leg drive |
| Breaking the arms early | elbows bend > 25° before legs are 70% down |
| Opening the back early | > 50% of body swing done when legs are 40% down |
| Rushing the slide | recovery:drive < 1.25 at rates below 30 |
| Knees up before body set | < 50% of body angle set when knees are 30% up |

Thresholds live in `strokesense/strokes.py` (`FAULTS` and `analyse`) so a coach can tune them.

6. **Crew timing** — each rower's catch time (sub-frame interpolated) is compared with the crew's
   median catch on every stroke.

## Limits (be upfront about these)

- 2D from one camera: angles are exact only when the camera is level with and perpendicular to the
  boat. Oblique shots compress angles; the trend across strokes is still meaningful.
- Rowers partly hidden behind each other are dropped or tracked less reliably.
- The nano pose model trades accuracy for speed; a larger model would tighten joint estimates.
- At 15 fps one frame is 67 ms, so catch timing is interpolated between frames; per-stroke timing
  is noisy (±~100 ms) and the per-seat averages over a piece are what to trust. `--fps 30` halves it.
- Fault thresholds are first-pass coaching heuristics, not yet validated against coaches — that is
  exactly what the validation study is for.

## Footage tips

Side-on from the launch, level with the boat, whole crew in frame (e.g. IMG_3942, IMG_3951). Shots
from behind the stern can't measure body angles.

## Evidence snapshot for coaching verification (Alpha)

The CLI now includes a versioned `evidence` snapshot inside `metrics.json`
without changing the existing `rowers` and `sync` fields. Each successful
analysis with detected rowing motion records deterministic, analysis-scoped
seat, stroke and observed-fault IDs; catch/finish/next-catch frames and source
timestamps; and explicitly counted fault observations. IDs are computed from
the analysis identity (source path/stat metadata, clip options and model
identity), package version and single-rower mode, **not from athlete names**.
The private source path is hashed and does not appear in evidence IDs.

`observed_fraction` is **observed fault strokes / analyzed strokes**, not
the fraction of strokes independently confirmed *eligible* for that fault.
The per-fault eligible-stroke denominator is currently unknown
(`eligible_strokes: null`). Every finding has
`coaching_eligible: false`, including those with three or more segmented
strokes; the distinction between `candidate_unreviewed` and
`insufficient_evidence` only describes a provisional sample-size rule. No
existing fixed coaching cue has documented approval. The independent LLM
validator must not treat candidate status or heuristic scores as approval.

`snapshot_sha256` detects accidental alterations to the serialized
snapshot when checked with
`strokesense.evidence.verify_evidence_snapshot()`. It is **not a signed
attestation, an append-only data store, or a proof of accuracy**: an editor can
change the file and recompute the digest. The cache identity still relies on
source path, size, and modification time; a same-size/same-time in-place
replacement may not invalidate it. A later quality/validation increment
must record trustworthy eligible denominators, versioned labels and
independently reviewed cues before any generated coaching is released.
No real-video accuracy or live LLM generation is established by these tests.

## Independent coaching release gate (Alpha, offline)

`strokesense.validation.validate_candidate(candidate, *, evidence_snapshot,
reviewed_cues)` is a pure deterministic validator for future structured LLM
messages. The caller supplies evidence and a coach-reviewed cue catalogue
**separately from model output**. Only explicitly supported reference IDs,
measured counts/fractions, an eligible/reviewed finding and an approved cue
can release a candidate. It rejects unexpected fields that try to smuggle
`coaching_eligible`, approvals or rewritten measurements into the generated
candidate. Invalid results contain errors but **never the rejected advice**.

Every current v1 evidence finding has `coaching_eligible: false` and an unknown
per-fault eligible-stroke denominator, and this project has no verified
coach-approved cue catalogue. Thus **real generated coaching cannot pass
this gate yet**. Offline success tests use explicitly synthetic approval and
reliability fixtures; no actual coach review or real-video accuracy is inferred.
The existing deterministic heuristic cues in legacy HTML reports are not
LLM-generated or reviewed under this gate.

Passing deterministic ID/number checks **cannot verify arbitrary explanatory
free text or the effectiveness/safety of advice**. The return value warns
`free_text_unverified`; a later upload/UI integration must escape text for
HTML and withhold unverified model output. `snapshot_sha256` is not a
signature; upstream storage and approval data require separate trust controls.

## Bounded correction loop (offline Alpha)

`strokesense.correction.run_correction(generator, *, evidence_snapshot,
reviewed_cues, max_attempts=3)` calls a provider-agnostic candidate generator
up to **three total attempts** (including the initial attempt). A rejected
candidate receives only machine-readable validator error codes for the next
attempt; no failed candidate text or exception message is returned. Trusted
evidence and cue metadata are copied before generation, so the generator
cannot amend validator inputs via references during the loop. A persistent
failure or generator exception produces `status: withheld` and
`released: null`. Invalid attempt caps are rejected.

The correction tests use explicit synthetic generators and fictional review
fixtures; they do not establish real provider correctness or human review.
A configurable HTTPS chat adapter is available below, but it has not been run
against a live provider. All current v1 evidence still fails the release gate,
and HTML integration of validated coaching remains future work.

## Optional LLM adapter (configured, not yet live-verified)

`strokesense.provider.OpenAIChatGenerator` implements an OpenAI-compatible
HTTPS Chat Completions JSON adapter and can be passed directly to
`strokesense.correction.run_correction()`. It is an **optional integration**,
not an automatically running cloud service: importing or constructing the
adapter performs no HTTP request. It requires explicit model/provider choice,
credentials, and a separate permission decision before external inference.

Set these environment variables locally (do not commit their values):

- `STROKESENSE_LLM_MODEL` — explicitly selected compatible chat model ID.
- `STROKESENSE_LLM_API_KEY` — secret bearer token; never print or commit.
- `STROKESENSE_LLM_ENDPOINT` — optional HTTPS Chat Completions endpoint
  (defaults to `https://api.openai.com/v1/chat/completions`).
  Redirects are blocked rather than forwarding tokens to another host.

The Python call sequence, **only when you have consent and approved cues**, is:

```python
from strokesense.provider import OpenAIChatGenerator
from strokesense.correction import run_correction

# Obtain evidence_snapshot from a saved metrics.json and a separately
# verified cue catalogue. Do not invent approval/coverage for live use.
generator = OpenAIChatGenerator.from_env(evidence_snapshot, reviewed_cues)
result = run_correction(
    generator, evidence_snapshot=evidence_snapshot,
    reviewed_cues=reviewed_cues, max_attempts=3,
)
# Present only result["released"] when status == "released".
```

The adapter sends **only** allowlisted evidence IDs, validated eligible
finding counts/timestamps, and approved cue IDs/fault mappings; raw source
paths, video bytes, private registry fields, reviewer identities, and full
snapshots are not sent. Nevertheless, measurements may still be personal
data: an external API request requires a deliberate consent/privacy decision
and may incur provider charges. The configured server must be trusted.
The adapter rejects insecure URLs, unexpected redirects, malformed/oversized
responses and provider exceptions, returning sanitized error codes to the
fail-closed correction loop. A 60-second timeout ceiling and 128-KiB response
ceiling bound individual attempts. No provider calls occur in the offline tests.

**Current blockers:** the repository contains no verified human-approved
cue catalogue or independently eligible real-video evidence; the v1 report
snapshot marks all findings unreviewed, so the adapter refuses a provider call.
Real model generation, accuracy, content moderation, pricing and advice quality
have **not** been tested. A passing structural validator still cannot prove
free-text truth or coaching effectiveness. The UI must display only validated,
safely escaped text and clearly distinguish withheld results.

## Local analysis job service (backend for local Alpha)

`strokesense.jobs.JobQueue` supplies a **single-process, bounded** local worker
on top of the consent/provenance-claiming SQLite clip registry. It persists
`queued`, `running`, `succeeded` or `failed` states and a job-scoped relative
`report_path` in a private SQLite database. At most one job executes at a
time, with a configurable limit on running plus waiting jobs. An invalid
request, full queue or unregistered/unverified clip is rejected.

Example usage after registering a clip with an explicit permission claim:

```python
from strokesense.jobs import JobQueue

with JobQueue(
    registry_db="results/video_registry.sqlite3",
    job_db="results/jobs.sqlite3",
    results_root="results/job_outputs",
) as jobs:
    submitted = jobs.submit(clip_id)  # clip_id from private registry
    status = jobs.get(submitted["job_id"])  # poll rather than block the UI
    # For a terminal-only demonstration: jobs.wait(submitted["job_id"])
```

The production local-job worker first performs a bounded OpenCV decoder
preflight: it checks that the media opens, reports finite FPS and sensible
dimensions (64px minimum, 4K pixel-budget, up to 240 fps), a known
positive frame count and nominal duration at most 120 seconds, and yields
at least one readable frame. A failed preflight returns the safe
`invalid_media` status without starting the pose model. Fake analyzers in
offline unit tests explicitly bypass this media-only production check.
Container frame counts and FPS are estimates, not verified truth:
variable-frame-rate/unindexed media may be rejected, and this is NOT a hard
CPU/runtime timeout. The local Alpha is intentionally conservative.
This is not a full-file decode or a security/malware scan; supported codecs
and corrupted later frames remain possible real-video blockers.

The worker rehashes the registered source **before and after** analysis
using streamed SHA-256, and refuses success/report publication if the clip
changed or disappeared during processing (safe `source_changed` failure).
This is best-effort source consistency, not immutable media storage; bytes
can still change between checks or be maliciously restored. Each job has
a unique output root, so repeat
analysis cannot replace a previous job's reports. Returned public status
records never contain absolute video paths, traceback messages or raw
exception text. Reports are published only after verifying that the
`report.html` file exists under the job's dedicated output directory.
Worker failures and unavailable result directories use safe error codes;
unfinished jobs from an interrupted previous local process are marked
`interrupted` on restart.

**Limitations:** This is not a hosted queue, durable cross-machine worker
or complete upload/UI application. Jobs execute in a local thread and the
process must remain running. Permission is still an unverified operator
attestation, not a cryptographic or legal proof of consent. The source
can change between the pre-run hash check and decoding; production
handling requires stronger immutable ingest/storage. The job worker itself does not authenticate callers. Use only the dedicated
loopback interface below; neither component is designed for public hosting. Tests inject fake analysis and
synthetic file bytes; no real video/model/LLM execution was performed.

## Local browser Alpha (registered clips to completed reports)

The standard-library `strokesense.web` module provides a **local-only**
browser flow: import a small video file with a permission/provenance claim
(or choose an existing registered clip), submit a bounded local analysis job,
inspect the status, and open its job-scoped HTML report. It does not require
installing a third-party web framework. From the `strokesense/` directory:

```powershell
# Register a permitted existing video locally; no upload or copying occurs.
python -m strokesense.registry import "Z:\\footage\\practice.mov" --permission granted --provenance "Operator confirms permission for local analysis"

# Start the UI using the default private registry/job databases and job outputs.
python -m strokesense.web --port 8765
# Visit http://127.0.0.1:8765/ in the browser.
```

The homepage also lists the latest 20 persisted analyses, with links to
reopen their status and successful reports after an app restart. Recent entries
show the registered, operator-supplied camera viewpoint (or `unspecified`),
with HTML escaping and no private source path/provenance. The camera label is
not inferred from pixels or verified against the footage. The
read-only `GET /api/jobs` endpoint returns at most 20 public status records
(no private source locations or provenance), ordered newest first. The
backend `JobQueue.list_recent(limit=20)` accepts limits 1–100 for local
callers and never returns private registry paths. Jobs are retained until
an operator separately removes their private database/results files.

When an analysis fails with a potentially transient error
(`analysis_failed`, `interrupted`, or `output_unavailable`), its status
page provides a **Retry analysis** button. This uses the existing protected
`POST /jobs` operation to queue a *new* job for the same permitted clip;
the failed record remains in history. Permanent invalid-media/source errors,
rejected consent, queued jobs and completed jobs do not show that button.
A retry is not a guarantee of success, and this Alpha provides no automatic
retries or public-facing authentication.

Local API failures under `/api/` use machine-readable
`application/problem+json` with `type=about:blank`, a generic `title`
and numeric HTTP `status`. They carry no raw exception details, source
paths, provenance, or file content and remain `Cache-Control: no-store`.
Browser error pages (e.g., `/jobs/<missing-id>`) still return HTML;
clients should branch on the HTTP status and media type, not parse error
HTML. Test these failure routes with
`python -m unittest discover -s strokesense/tests -p test_api_errors.py -v`
from the repository root.

The private browser import form also allows an **optional camera-view
label**: Unspecified (default), Side-on, Bow-on or Stern-on. The selection is
a human-supplied registry label—not an inferred, calibrated camera pose—and
does not modify the analyzer's model configuration. Legacy multipart
uploads omitting `camera` continue to work. Unknown/duplicate camera
fields are rejected before storing video; identical footage is deduplicated
without silently changing its earlier camera label. The private registry
can be listed to inspect the saved label.

The browser import form (also reachable with `POST /upload`) accepts a
**maximum 25 MiB multipart request**, enforces nonempty bytes and a video
extension allowlist (`.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`), and
requires a checked operator permission attestation plus a nonempty
provenance statement. Files are stored locally in a private uploads directory
under randomized opaque names with restrictive permissions; the registry
computes a full SHA-256 and deduplicates identical content, without exposing
private source paths. The upload handler also rejects obviously incorrect container headers (ISO BMFF
`ftyp` for MP4/MOV; RIFF/AVI; EBML for MKV/WebM) before writing private files
or indexing a clip. Invalid or truncated headers return HTTP 415 without
publishing private content. This lightweight signature check is **not** a
decoder, malware scanner, consent proof, or guarantee of a usable video stream.
Some older QuickTime files without an initial `ftyp` box may be rejected and
need conversion; real media decoding/codec compatibility are still untested.
The browser upload form now offers an explicit **Analyze immediately after
import** checkbox (checked by default). With it selected, a valid
permission-attested upload first registers/deduplicates the private clip,
then submits one bounded job and redirects to `/jobs/<opaque-job-id>`.
Uncheck it for register-only behavior: `POST /upload` without the optional
`analyze=now` field still redirects to the homepage without running analysis.
A full/unavailable job queue returns a generic HTTP 503; the registered
clip remains available for a manual retry rather than falsely claiming success.
Malformed or repeated analyze fields are rejected before upload persistence.
Decoder verification occurs later in the worker, not at upload time;
a queueing success does **not** prove decodability or permission.
Local files cannot be downloaded using HTTP routes.
Set `--uploads` to move the private upload directory.

Offline integrated-flow checks are available via
`python -m unittest discover -s strokesense/tests -p test_upload_analyze.py -v`
from the repository root. These use **synthetic container headers and a fake
analysis callback** to exercise upload, job status, report reopen, validated
evidence, explicit coaching withholding and failure paths. They are not a
real rowing video demo, live model execution, consent audit or accuracy result.

The interface binds only to IPv4 loopback, checks the Host/Origin headers,
requires a randomized per-process anti-CSRF token on job submissions
**and uploads**, caps form, upload and report sizes, and restricts report reads
to successfully completed jobs' own result directories. Hostile path
traversal/symlinks do not expose unrelated files; it sends no source paths or
raw worker exceptions to browser clients. Rendered reports use a sandboxing
Content Security Policy.
The browser does not receive credentials or automatically call any LLM; all
existing heuristic cues are unreviewed and **not** validated LLM output.
The app and reports are **not authenticated**: anyone using this local
computer/browser session can inspect reports. Do not port-forward, proxy,
or deploy it to a public interface.

**Not implemented yet:** production authentication, durable distributed
execution, verified file type/codec safety, independently proven footage
consent, coach-approved cues, and real-video evaluation. Uploads are not
virus-scanned; treat footage as untrusted and use only permitted files from
known sources. Crash-recovery garbage collection for interrupted uploads is
not yet implemented. Server tests are synthetic and use a fake analysis
worker; they do not establish pose accuracy or a full end-to-end model run.


### Saved evidence navigation (local browser, issue #22)

Successful jobs expose an **unreviewed, read-only** evidence view at
`/jobs/<job-id>/evidence` and allowlisted JSON at
`/api/jobs/<job-id>/evidence`. Only a job-local `metrics.json` inside a
verified result root is read; failed/unknown jobs, oversized files,
traversal/symlinks outside the job root, corrupt checksums and malformed
version-1 schemas fail closed. The checks cover frame/time numeric types,
finite rates, measured denominators, seat/stroke/fault cross-references,
and reject unsupported coaching-eligibility/approval claims even when a
checksum has been recomputed. All label text is HTML-escaped.

On the evidence HTML page, each candidate finding now shows its
observed-count / analyzed-stroke denominator and links to the exact saved
stroke rows that support it. Each target lists seat, stroke index, catch and
finish times. To bound page rendering, the HTML links at most 50 cited
strokes per finding; the read-only JSON evidence endpoint keeps the complete
validated reference list. Links navigate within the evidence page, **not**
to a decoded frame or synchronized video player. These denominators are
segmented strokes, not verified per-fault eligible opportunities or
measured diagnostic precision/recall.

Successful saved evidence pages also offer **Export stroke evidence (CSV)** via
`/api/jobs/<job-id>/strokes.csv`. The export lists one integrity-checked
stroke per row (seat, index, saved catch/finish times, fault codes), only
after the same completed-job, permission, job-local path, digest and evidence
schema checks as the JSON view. The CSV retains segmented observations, not
coach-reviewed measurements or any calibrated accuracy. Untrusted labels
beginning with spreadsheet formula characters are prefixed with an apostrophe
to reduce spreadsheet formula injection risk; downstream software should
still treat this CSV as untrusted data. No source paths or provenance are
exported. This is a local read-only file response, not an external upload.

The UI always says `coaching_state=withheld`: none of the current version-1
findings has independently reviewed eligibility or approved cues, and this
page does not invoke an LLM. **SHA-256 integrity checks are not signatures**
and cannot prove that an editor has not deliberately changed a file or
that measurements are accurate. This local interface is not authenticated;
do not expose it outside loopback. Tests use synthetic metric fixtures,
not genuine coach-reviewed footage.

## Reproducible offline browser demo (synthetic, no model)

Run the complete local HTTP upload -> queued analysis -> saved report ->
validated evidence flow without any user footage, model download, external
provider calls, approved cues, credentials, or cloud deployment. From the
`strokesense/` directory:

```powershell
python -m strokesense.demo
python -m strokesense.demo --simulate-failure
```

The first command prints JSON with `mode=synthetic-offline`,
`status=succeeded`, `synthetic_report_observed=true`, three fabricated
stroke observations and `coaching_state=withheld`. The second simulates a
typed invalid-media analysis failure, expects `status=failed`, no report,
and withheld coaching. Both start a temporary loopback HTTP server, send
a real multipart request through the same upload/job/results routes as the
browser, and clean up temporary SQLite databases, dummy video bytes and
result files. The analysis adapter is intentionally FAKE and its report is
explicitly marked SYNTHETIC. It does **not** establish real-media
compatibility, actual pose analysis, label precision/recall, customer
validation, live LLM behavior or the effectiveness of advice.

The underlying tests run automatically in `python strokesense/quality.py`:
`test_upload_analyze.py` exercises real loopback request routing with
fake analysis and withheld evidence, and `test_demo.py` verifies the
runnable demo's success, failure and CLI JSON output. Production browser
usage remains `python -m strokesense.web --port 8765`, using genuinely
permitted footage and the installed model.

## Withdraw local permission for analysis

A clip operator can withdraw a previous permission claim by its opaque
SHA-256 clip ID; no private source path is required:

```sh
python -m strokesense.registry list
python -m strokesense.registry revoke <clip-id> --db strokesense/results/video_registry.sqlite3
```

The update is transactional and idempotent: the clip remains in the private
registry with `permission=denied`; original provenance and recording-group
metadata remain for local audit/reconciliation. A first explicit withdrawal
also sets a UTC `revoked_utc` timestamp in the private SQLite registry.
Repeating a withdrawal preserves the original timestamp. Clips imported
as `denied` (or denied in an older database) retain a null timestamp;
the software does not invent when that action happened.

The registry uses SQLite schema version 2 (`PRAGMA user_version`). On first
access, existing unversioned/v1 registries are upgraded additively without
dropping clips or rewriting their provenance/split. A database reporting a
newer schema, or an inconsistent v2 schema, fails closed rather than being
silently overwritten. Opening an old database may therefore perform a local
schema migration. Keep private backups before upgrading. This audit records
local operator claims, not independently verified consent or legal compliance,
and **does not delete** source media or historical reports.

New analysis requests reject
the revoked clip. Workers recheck permission before analysis and again before
marking a result successful; queued or in-progress jobs whose permission was
withdrawn fail with safe `permission_revoked` and no published report pointer.

The loopback browser offers a separate **Withdraw analysis permission**
form for granted clips. It reuses the same CSRF-protected, Host/Origin-checked
local request path as starting jobs, then redirects to the private homepage.
This is an explicit local operator action, not an independently validated
consent withdrawal.

The local browser also checks the **current** registry permission when serving
prior job status, report and evidence links. After withdrawal, these routes
return a safe 403 and omit withdrawn clips from recent-job listings. Private
previously generated files are retained on disk; the UI gate is not deletion
and does not revoke previously downloaded copies.

**Limitations:** Permission is only a local operator assertion, not verified
athlete consent. Revocation does **not** delete the source file or historic
reports, undo prior disclosures, forcibly terminate an already-running model,
or make the final permission check and report publication atomic. The UI must
remain on loopback and must not be treated as a consent-management service.
Ask the data controller to remove retained video/reports separately when needed.

## Quality checks

From the repository root, run the complete offline regression suite (legacy synthetic stroke checks, cache regressions, and quality-tool tests):

```powershell
python strokesense/quality.py
python strokesense/quality.py --doctor
```

`--doctor` is read-only: it reports local dependency discovery, whether the ONNX model file is cached, and optional FFmpeg availability. It does not download the model, run inference, decode footage, or establish real-video accuracy. It exits nonzero if required runtime modules are absent; the unit-test command works separately. For the older synthetic checks alone, run `python tests/test_analysis.py` from the `strokesense/` directory. CI also runs the offline suite for `dev/**` branches.

**Collision-safe results:** Since the October 27 sprint, each video uses a stable
`results/<video stem>--<20-character source-path SHA-256 prefix>/` directory.
The hash is computed from the canonical absolute input path (so path aliases
such as symlinks resolve to the same directory), not the video contents.
Different videos named `crew.mp4` in different folders no longer overwrite
each other's detection caches, `report.html`, `metrics.json`, annotated
videos, or snapshots. Identical source paths keep their result directories
across reruns; changed input file stats/settings/model still invalidate the
cached detections.

**Existing output folders:** Previous releases used `results/<video stem>/`.
These legacy folders are left untouched rather than being automatically
migrated or replaced, because the original source owner cannot always be
verified. You can still open old `report.html` files directly. To regenerate
a clip with the new version, rerun the CLI; its results will appear in the
new path-scoped directory. Re-inference may be required on the first run.
The suffix is based on source *path*, not content: replacing a clip at that
same path retains the output directory, while the **pose cache identity now
streams SHA-256 of the actual video bytes** (as well as size, mtime, analysis
settings and model digest). This prevents stale reuse even when changed bytes
have identical size and nanosecond mtime. Older stat-only cache metadata is
invalidated and recomputed. A source change detected during estimation is
not cached. Each identity computation reads the complete source in 1 MiB
chunks, so reruns incur additional disk I/O proportional to clip size.
A digest does not prove authorship or eliminate adversarial file-edit races.
Synthetic rowers with injected faults (shooting the slide, early arms, rushed slide, late body prep,
excess layback, short catch) verify each detector fires and a clean stroke scores ≥ 85.


## Offline evaluation from reviewed opportunities (Alpha)

For future empirical tests, `strokesense.evaluation.evaluate_fault_records(rows)`
accepts a **nonempty, bounded list** of independently reviewed stroke/fault
opportunities. Every row must have these keys: `clip_id`, `seat_id`,
`stroke_id`, `fault_code`, `actual` (strict boolean truth),
`predicted` (strict boolean algorithm flag), `review_status="reviewed"`,
`group_id` (whole recording/session/athlete group as appropriate), and
`split` (`development` or `heldout`). **Explicit false labels are required**
to measure false positives and true negatives; unlabeled strokes are not
silently treated as negative. The helper does not access footage or a model.

The returned version-1 report includes per-split/per-fault TP, FP, FN, TN,
reviewed opportunity counts, precision and recall with their **numerators and
denominators**. An undefined rate (zero denominator) is JSON `null`, not zero
or a fabricated accuracy. The aggregate omits clip, athlete and group IDs.
Duplicates and the same group across evaluation splits are rejected. Accurate
leakage prevention still depends on trustworthy real annotation and group IDs.

Only synthetic unit tests are available in this repository; **no per-fault
real-video precision/recall, catch-timing error, confidence intervals or
coach-approved label coverage has been measured**. A `review_status` string
alone does not verify a human review or recording permission. Future empirical
results need permitted footage, documented annotators, appropriate grouped
heldout evaluation and explicit labeled denominators before publication.


### Reproducible local evaluation command (synthetic tests only)

After preparing a **locally held** UTF-8 JSON array of independently reviewed,
per-fault labeled opportunities in the schema above, run from the
`strokesense/` working directory:

```bash
python -m strokesense.evaluation reviewed_opportunities.json
```

The tool reads at most 2 MiB and prints only aggregate counts/denominators as
JSON. It does not upload media, load the pose model, contact an LLM, or reveal
source identifiers on stdout. Invalid/missing/unreviewed input exits nonzero
with a generic error that does not echo private input paths. This tool cannot
verify that human review really occurred; no real-video accuracy is claimed.


## Local HTTP form framing safeguards (Alpha)

Local `POST /jobs`, `POST /revoke`, and `POST /upload` accept only a
single decimal `Content-Length` and no `Transfer-Encoding` request header.
Duplicate/conflicting length headers, chunked framing and missing body-length
metadata are rejected before any write. Non-upload form bodies must arrive
in full within the 5-second socket-read timeout; a clean EOF with too few
bytes or a stalled sender returns a generic error without submitting an
analysis or changing a permission claim. Uploads retain their own separate
bounded size/read timeout and multipart validation. These are local-only
defenses and are not a substitute for TLS, user authentication or an
independent security assessment of a publicly exposed service.


### Reproducible demo with *fabricated* review-shaped data

From the `strokesense/` directory, this command prints an aggregate
versioned JSON report and requires **no model, video, credentials or network**:

```bash
python -m strokesense.evaluation examples/synthetic_opportunities.json
```

This file contains exactly **eight fictional stroke/fault opportunities** in
separate development and held-out *synthetic* recording groups. One development
fault has one TP, FP, FN and TN, giving arithmetic precision=0.5 and
recall=0.5; another has an undefined precision denominator. Its
`review_status: "reviewed"` entries are intentionally fabricated to
exercise the evaluator's strict schema: **no person or coach reviewed these
strokes**. These numbers are sample software-test outputs, **NOT accuracy
estimates** for rowing footage, and must never be presented as observed
precision/recall. No raw clip/session/stroke IDs appear in the aggregate.
For genuine evaluation, replace the fixture with independently annotated,
permission-cleared footage with documented groups and denominators.


## Saved local result integrity (Alpha)

Jobs database schema version 4 records **private SHA-256 digests** of
the completed HTML report and, if present, its `metrics.json` evidence. The
local browser verifies the exact report bytes before showing HTML or saved
evidence, and verifies the exact metrics bytes before parsing/showing evidence.
Absent or mismatched required digests return HTTP 409. Report and metrics
readers enforce the 32 MiB / 16 MiB limits on bytes actually read, rather
than relying only on possibly stale file metadata. Public status/history JSON
never includes digests or private source paths.

Upgrading old jobs databases (versions 2 and 3) is **non-destructive**:
existing rows, videos and reports remain on disk. Historical report or
evidence surfaces lacking the corresponding saved digest cannot be released
until a new analysis creates an integrity-checked job. Older jobs that retain
a valid HTML digest can still open that unchanged report even if their
metrics digest is unavailable; unbound evidence remains withheld. Checksums
detect accidental or file-only changes but are **not cryptographic
signatures** and cannot prevent edits by someone who can modify both the
local database and result files. Evidence remains unreviewed and no
generated coaching is approved by this mechanism.


## Explicit saved-evidence coaching verification CLI (Alpha)

See [COACHING_CLI.md](COACHING_CLI.md) for the reproducible offline
reject/correct/withhold command and a separately opted-in configurable
HTTPS LLM mode. All offline success examples use **fictional review-shaped
fixtures**, not real coach approvals. The CLI validates evidence and cue IDs
against separately supplied data, bounds inputs and limits correction to
three attempts, but **does not change the job database or publish feedback**.
The existing browser continues to withhold coaching. A locally validated
candidate is not proof of coaching effectiveness, genuine consent or
reviewer identity.


## Filter the private recent-analysis library (Alpha)

The loopback browser home page offers **Filter analyses by camera**: All
(default), Side-on, Bow-on, Stern-on or Unspecified, plus **Filter analyses by
status**: All (default), Queued, Running, Succeeded or Failed. Both selectors
can be combined to find attention-needed or completed jobs without modifying
records. A selected status is the local job queue state, not a coach-reviewed
technique verdict. The filter only narrows
the at-most-20 most recent permission-granted jobs shown on the page; it does
not change or delete registered clips, queue state, saved reports or the
`/api/jobs` JSON response. The label comes from the operator's registry
metadata, **not** automatically classified video. Selecting Unspecified
shows records without a camera label. Direct local URLs such as
`http://127.0.0.1:<PORT>/?camera=side-on&status=failed` have the same effect;
unknown, duplicate or extra filter values fail with HTTP 400. Data are displayed only in the
loopback application, and filtering does not verify recording rights, video
quality or rowing-technique accuracy.


## Private annotated-video playback (Alpha)

For a completed, permission-granted local job, the status page can show an
HTML5 **Annotated video** player when the analyzer returned a rendered MP4 or
WebM file inside that job's private output directory. The local job database
schema version 5 stores only its job-relative location and SHA-256 digest;
public status/history responses contain neither location nor digest. Existing
jobs with no media remain accessible, but do not show a player. Earlier jobs
can be upgraded non-destructively; a fresh analysis is required to bind media.

The loopback-only `GET /media/<job_id>` route rechecks current permission,
completion, withheld-coaching state, job-local path and the saved digest before
serving. Changed files, revoked permissions, symlink escapes and unsupported
output types are withheld. Output is limited to **64 MiB per rendered file**;
a larger rendered artifact fails that job rather than being served. This
Alpha supports a single bounded byte-range request for local video seeking:
`Range: bytes=start-end`, `bytes=start-` or `bytes=-suffix` returns
HTTP 206 with `Content-Range`, `Accept-Ranges: bytes` and only the selected
bytes after verifying the **entire** saved artifact SHA-256. Invalid, multi-
range, reversed or unsatisfiable requests get HTTP 416 with the safe
`Content-Range: bytes */<size>`; no Range preserves full 200 responses.
This remains an in-memory, at-most-64-MiB local response, not streaming,
so it still uses memory/bandwidth; browser seek/codec compatibility has not
been empirically measured. Do not expose this loopback endpoint over a
proxy, LAN or internet.

The synthetic tests exercise file and HTTP authorization behavior, **not**
actual browser video decoding, accurate pose overlays, permission verification,
real human coach review, or end-to-end inference on genuine footage.

## Jump from saved stroke evidence to annotated footage (Alpha)

For a completed, permission-granted job with a saved annotated-video artifact,
`/jobs/<job_id>/evidence` offers **Watch catch** next to each eligible,
digest-verified saved stroke. Following the link opens the same job's video
player at that stroke's catch time via a browser HTML5 media fragment,
`/media/<job_id>#t=<seconds>`. The absolute saved evidence time is adjusted
by the analysis `start_seconds` because the rendered annotated clip starts
at time zero even if the original source video was trimmed for analysis.
No source clip filenames, private paths, external scripts, or raw model URLs
are embedded in these navigation links.

Only a single `at` query with a decimal position from **0 through 120
seconds**, to at most **three decimal places**, is accepted. Invalid,
ambiguous, nonfinite, repeated or extra query parameters return HTTP 400.
Media is still governed by the existing local permission, job status,
64 MiB, path-containment and SHA-256 checks; video-free legacy jobs
keep readable evidence but show no dead watch links. Generated coaching
remains **withheld**.

These links are tested with **invented data and synthetic media bytes**.
Actual timestamp seeking and decoding in a browser are **not yet empirically
verified**. Browser support for media fragments and efficient seeking can
vary by container/codec and HTTP Range behavior. Timestamp rounding to
milliseconds can differ from the original saved evidence value by up to
0.5 ms, and this is navigation, not a claim of technique or timing accuracy.


## Watch one supporting example from a candidate finding (Alpha)

In the saved evidence browser, a candidate fault finding with a validated,
saved supporting stroke now includes **Watch first example** when the job has
an available annotated-video artifact. This goes directly to the same
job-scoped player using the first supporting stroke's saved catch time,
translated from source time to exported-video time. The existing links to
the complete stroke table, JSON and CSV evidence are unchanged; coaching
is still shown as **withheld**, not reviewed or proven. No link is shown if
a recording has no saved media, the finding has no supporting stroke, or
the timestamp cannot be safely represented inside the 120-second Alpha cap.

The link is generated from digest-checked local evidence, never a raw model
URL, and reuses the strict timestamp/permission/media integrity checks.
Synthetic HTTP tests verify the link and offset arithmetic; they do **not**
prove real browser seeking, video codec compatibility, technique detection
accuracy or an approved coaching recommendation.


## Blank coach-review worksheet for real validation later (Alpha)

On a completed, permitted job's **Saved evidence** page, **Blank coach-review
worksheet (CSV)** exports the digest-checked candidate stroke records through
the loopback-only `/api/jobs/<job_id>/review.csv` route. It includes stable
saved stroke ID, seat label, stroke number, catch seconds and candidate fault
codes; the `coach_fault_present` and `coach_comments` columns are deliberately
**empty**, with `review_status=unreviewed` on every row. This is an
annotation **template**, not an evaluation result or actual review; there is
no import/approval workflow yet. Any real annotations must be collected by
the team from consent-cleared people/footage and independently quality-checked
before use.

The same permission, withheld-coaching state, completed-job, saved report
and metrics integrity, snapshot schema, bounded output and no-cache checks as
existing stroke exports apply. Seat labels are CSV formula-hardened. The CSV
does not contain private source filenames, URLs, storage roots, consent notes,
credentials or full raw metrics. It never enables a verified coaching state.
Synthetic HTTP tests cannot establish real customer demand, coach agreement,
false-positive rates, or permission to redistribute recordings.


### Optional video position in the blank coach-review CSV (Alpha)

When a completed, permission-granted analysis has a saved annotated video,
the blank `/api/jobs/<job_id>/review.csv` worksheet includes
`video_seek_seconds` for each saved stroke. It is derived from the
integrity-checked evidence as `catch_seconds - start_seconds`, rounded to at
most three decimal places and bounded to 0–120 seconds. This is a **position
in the exported annotated clip**, not an absolute timestamp in the original
source. When the job has no saved media, the recorded file has been removed or
modified, or the position is outside the supported bound, the field remains
blank; no video or labels are fabricated. Links and CSV navigation are offered
only after a bounded SHA-256 recheck of the saved job-scoped media. Playback
performs its own integrity check again, since files may change between reads.
The original `catch_seconds` and all preexisting blank human-label columns
are preserved.

These values help a human reviewer find a candidate stroke in locally
permitted footage; they do **not** indicate independently verified rowing
faults, real-world timing accuracy, coach approval, or customer validation.
The worksheet remains a manual, **unreviewed** template. Opening, decoding,
and seeking real video in a browser have not been measured by synthetic tests.


## Complete per-fault coach review grid (Alpha)

To prepare independent, **human** validation for a completed permitted clip,
open its **Saved evidence** page and select **Complete per-fault coach-review
grid**. The loopback-only `/api/jobs/<job_id>/fault-review.csv` export emits
one row for *every validated saved stroke and every currently supported
candidate fault*, including predicted-negative pairs. The stable header has
`schema_version=1`, saved opaque seat/stroke references, seat label, stroke
index, `fault_code`, source `catch_seconds`, optional
`video_seek_seconds` (0–120 s into intact job-scoped annotated video),
`predicted=1` for flagged candidates and `predicted=0` otherwise.

The independent-review fields `coach_fault_present` and `coach_comments`
are **empty**, and every `review_status` is **unreviewed**. Neither a
candidate positive nor a candidate negative is ground truth. Reviewers must
explicitly inspect permitted footage and label both types for each applicable
fault. Real precision and recall require complete, legitimate gold labels and
explicit denominators, with sessions and athletes separated across evaluation
splits. This export does not verify reviewers, consent, labels, split leakage,
or model accuracy, and cannot itself approve an LLM cue.

The endpoint uses the same job permission, status, withholding, saved-report
hash and metrics-snapshot integrity checks as the other evidence exports.
The CSV is bounded, formula-safe for seat labels and omits source paths,
private filenames and provenance. Existing `review.csv` and `strokes.csv`
are unchanged; this new worksheet is an additional option, not an automatic
evaluation or an annotation import workflow. Synthetic tests verify row
construction and fail-closed routing, **not** actual athlete performance,
customer validation or coaching effectiveness.


## Aggregate manually reviewed fault-grid CSV locally (Alpha)

After a human coach has **independently reviewed every included stroke/fault
opportunity** in the additional `fault-review.csv` worksheet, they may set
`review_status=reviewed` and fill `coach_fault_present` with exactly `0`
(absent) or `1` (present) for **each row**, including algorithm-negative
opportunities. Do not label the file reviewed unless that actual review took
place; leaving fields blank intentionally blocks evaluation.

The local offline CLI accepts a completed version-one worksheet using:

```bash
python -m strokesense.evaluation --review-csv --clip-id LOCAL_OPAQUE_CLIP_ID --group-id SESSION_OR_ATHLETE_GROUP --split development completed-fault-review.csv
```

Run from the `strokesense/` directory (or configure the normal Python module
path). Use `--split heldout` only for genuine untouched held-out groups; do
not evaluate a session/athlete in both splits. The CLI validates exact CSV
columns and review markers, requires every 0/1 label, checks supported fault
codes, bounded input, duplicates, and private grouping. It prints aggregate
TP/FP/FN/TN, explicit precision/recall numerators/denominators and
`labels_independently_verified=false`; it never prints local paths or
individual stroke IDs. The original JSON evaluation mode remains available
without `--review-csv` and remains unchanged.

**Important:** The software cannot authenticate the human reviewer, verify
recording consent, determine whether every real stroke/fault opportunity was
included, audit session/athlete leakage, or turn an operator claim into
empirical accuracy. CSV rows in the automated tests are **fabricated**; any
computed fixture precision/recall is synthetic regression output, not field
performance. Actual Activity 1 customer validation and genuine independently
reviewed clips are still required.

## Filter saved candidate faults on the local evidence page (Alpha)

After completing a permitted local job, open **Inspect saved evidence** and use
**Select a candidate fault → Filter evidence** to limit the displayed
stroke/finding lists to one of the supported deterministic fault codes. The
link **Clear filter** restores all rows. A supported code with no recorded
candidate strokes explicitly shows an empty result; invalid/ambiguous query
parameters return 400 without disclosing data. For example, on the local
loopback interface, `/jobs/LOCAL_JOB_ID/evidence?fault=early_arms` displays
the corresponding saved stroke candidates and playback links, when the
integrity-checked rendered media exists. This does not change or recompute
the original finding counts, annotate footage, or change saved results.

The `/api/jobs/LOCAL_JOB_ID/evidence` JSON and CSV/coach-review exports
remain **unfiltered** and protected by the existing permission and integrity
checks. This is an HTML navigation feature, **not a fault-accuracy measurement,
real coach approval, independent LLM verification, or customer validation**.
The synthetic HTTP regression fixture is invented, not a real video review.

### Native candidate-frequency meters

For each validated saved **candidate** finding, the local evidence page
shows a compact accessible HTML `<meter>` with the original count of flagged
strokes and its explicitly saved `analyzed_strokes` denominator (for example,
**1 of 3**). This represents only the prevalence of the heuristic candidate
among analyzed strokes; **it is not model confidence, precision, recall, human
confirmation, clinical advice, or coach-approved feedback**. The meter is not
rendered when no finding exists or there is no valid positive denominator.
The selected-fault HTML filter narrows visible meters, while underlying JSON
evidence and CSV worksheets remain complete and unchanged. No client-side
JavaScript, remote assets, or new dependencies are required.


### Filter recent analysis history by registered clip

On the local Alpha homepage, the **Filter analyses by clip** dropdown selects
one currently permission-claimed registered clip (displayed by an abbreviated,
opaque SHA-256 ID). Choose **All clips** or **Clear filters** to restore the
full permitted recent-history list. The clip selector can be combined with
existing camera-viewpoint and analysis-status filters; no job records are
modified. Unknown or revoked clip IDs and invalid/ambiguous queries are
rejected. The separate `/api/jobs` endpoint is deliberately not filtered
by the HTML view, and no source path or permission-provenance text appears
in the list. This is local navigation over synthetic-tested job state, not
a new model inference, verified human permission, empirical accuracy
measurement or customer validation.


### Direct report shortcuts from recent analyses

A successful, permission-scoped job in the local homepage **Recent analyses**
list offers **Open technique report** alongside its existing job-status link.
The shortcut points at the existing local `/reports/<job-id>` endpoint, which
independently rechecks permission, completion, saved report path and SHA-256,
and withheld coaching state before returning HTML. Failed, queued and running
jobs have no report shortcut. The new clip/camera/status filters preserve these
links when the job is visible. Use the job page to inspect saved evidence where
an analysis produced an evidence snapshot; older reports may not contain one.

This convenience navigation does not expose private footage, grant coach
approval, release LLM advice or establish empirical rowing accuracy.
Synthetic regression tests use invented report bytes and operator claims.

### Download permission-scoped recent-analysis history (Alpha)

On the private loopback homepage, choose the **camera**, **status** and/or **clip**
filters under **Recent analyses**, then click **Download analysis history CSV**.
The link uses `GET /history.csv` with the same optional `camera`, `status`
and `clip` parameters as the current HTML view. For example, the local URL
`http://127.0.0.1:<PORT>/history.csv?status=succeeded&camera=side-on`
downloads at most the 20 latest permission-granted, withheld-coaching records
that match those filters (empty views contain only column headings).

Columns are `job_id`, `clip_id`, operator-assigned `camera`, job `status`,
`created_utc`, `finished_utc`, `coaching_state` and `report_available`.
No private source paths, consent/provenance strings, footage, metrics or provider
messages are exported. Revoked or unknown clips are excluded; explicit invalid
clip filters and malformed/duplicate filters return HTTP 400. The CSV is a
local file download only, not an external upload or an assessment of technique.
`report_available=yes` means the job status is `succeeded`, **not** that
the report bytes have just been revalidated; opening a report still performs
its existing independent SHA-256/path/permission checks. Any spreadsheet
processing the file should treat it as untrusted input despite formula escaping.
Exports are not a substitute for real user testing or measured accuracy.

### Compare two saved technique-analysis runs (Alpha)

When at least two completed, currently permitted analyses are listed in the
private browser library, **Compare saved analyses** lets a coach select an
earlier and later run. A local request such as
`http://127.0.0.1:<PORT>/compare?before=<32-hex-job-id>&after=<32-hex-job-id>`
shows a side-by-side table of **candidate fault counts over analyzed strokes**
for the two saved versioned evidence snapshots. The comparison accepts exactly
two distinct job IDs; extra, repeated or invalid query parameters fail with
HTTP 400. It creates no analysis jobs and invokes no provider.

For **both** jobs, the server independently checks current clip permission,
completed status, `coaching_state=withheld`, job-local result paths, bounded
saved report/metrics sizes, stored SHA-256 hashes, and validated evidence
schema before showing any counts. Missing legacy metrics cannot be compared;
revoked clips, unexpected release flags and altered artifacts are not shown.
Links reopen the already-gated report and stroke/fault evidence views.

A count such as **1 of 3** means one segmented stroke was flagged by a
deterministic heuristic among three analyzed strokes, **not** measured
precision, recall, coach agreement or a controlled before/after improvement.
Different cameras, clip conditions, tracking quality and denominators are not
normalized. With no findings, the view explicitly avoids claiming a
coach-reviewed negative label. These browser tests use only invented data and
do not establish real-video accuracy, coaching usefulness or informed consent.

For each run, the comparison also shows its **operator-entered camera
viewpoint** (Side-on, Bow-on, Stern-on or Unspecified). When the two current
registry viewpoints differ, the page explicitly warns that candidate fault
counts cannot be normalized across viewpoints. These labels are human-entered
metadata, not camera-classification results, and matching labels do not make
the runs a controlled before/after study. No raw provenance, private video
path or arbitrary camera text is displayed.

The side-by-side candidate-fault table also makes each per-run **count a
clickable evidence link**. Select, for example, `1 of 3 analyzed strokes` to
reopen that run's `/jobs/<job-id>/evidence?fault=<validated-code>` page.
A `0 of N` cell still opens the evidence page, which explains that no strokes
were flagged for that candidate. The destination independently rechecks
current clip permission, saved report/metrics hashes and evidence format;
opening a link does not release unreviewed AI advice. These counts are heuristic
candidates, not accuracy or proof of technique improvement.

### Download the two-run candidate comparison (Alpha)

The verified **Compare saved analyses** browser page also offers
**Download comparison CSV**, which requests
`/compare.csv?before=<job-id>&after=<job-id>`. This is a read-only attachment
with fixed columns `fault_code,before_job_id,before_flagged,before_analyzed,
after_job_id,after_flagged,after_analyzed` (the line wraps here for readability).
It shares the comparison page's strict IDs, current permission, withheld
coaching, job-owned path, SHA-256 and saved evidence schema checks. If neither
run flags a candidate fault, only the header row is returned; a missing or
tampered result never produces an unverified data export. The CSV contains no
private footage or filesystem/provenance metadata, and remains a local download.

These counts are **heuristic candidates across analyzed strokes**, not coach
labels, true positives/false positives, precision/recall, measured improvement,
or evidence that an LLM cue is useful. Different sample sizes, rowing conditions
and camera setups make comparisons uncontrolled. Use coach-reviewed labels and
per-video denominators before reporting empirical performance.

### Versioned persisted coaching-withholding metadata (Alpha)

Local analysis-job records now contain `coaching_schema_version=1` alongside
`coaching_state=withheld`. An existing jobs SQLite database is upgraded
**non-destructively** to `PRAGMA user_version=6`, preserving historical jobs,
reports, and stored hashes. New and reopened records expose only the safe,
versioned withholding metadata; failed jobs also remain withheld. This change
does **not** enable a validated `released` state, change deterministic
approval rules, approve existing heuristic cues, or invoke any paid provider.
The local UI continues to refuse unexpected stored release flags. Synthetic
regression tests verify migration and persistence, **not** live model outputs,
genuine coach review, customer validation, or measured rowing fault accuracy.

## Responsive local browser workspace (Alpha, issue #86)

The existing loopback-only browser UI now uses a self-contained visual design
system: navy/teal navigation, a prominent analysis header, styled upload and
consent inputs, analysis history, responsive forms/lists, a skip-to-main link,
and visible keyboard focus. The interface is **still the same local Python
application**, not a public deployment or a ChatGPT website. No framework,
JavaScript, remote stylesheet, tracking pixel, font download, or new network
service is required. Layout CSS lives in `strokesense/web_style.py` and is
inlined under the existing restrictive Content Security Policy.

From the repository's `strokesense/` directory on Windows PowerShell:

```powershell
py -3 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe -m strokesense.web
# Open http://127.0.0.1:8765/ in your browser
```

The top navigation links to the same homepage's **Register a new local clip**
and **Recent analyses** sections. The file control uses the native operating
system picker; it is **not** an implemented drag-and-drop upload widget.
Existing upload limits, permission attestation, CSRF, private job isolation,
saved evidence integrity checks and withheld coaching state are unchanged.
The page-refresh mechanism for queued/running jobs still works without scripts.
The browser must run on the same machine (127.0.0.1); do not port-forward it
to the public internet.

Contract tests cover escaped titles, structural navigation, CSS keyboard
focus/mobile/reduced-motion hooks and automatic refresh, plus a real loopback
homepage response and its anchor targets. These tests cannot determine whether
every browser/font/zoom combination looks correct. **No manual visual
screenshot, real footage evaluation, coach approval, customer study, or live
LLM provider call was performed as part of this design-only increment.**
