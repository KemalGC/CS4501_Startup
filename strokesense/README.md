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
same path reuses the output directory and invalidates caches when its path/stat
identity changes; a same-size, same-mtime replacement remains an unverified
edge case, pending stronger content fingerprints in the video registry.
Synthetic rowers with injected faults (shooting the slide, early arms, rushed slide, late body prep,
excess layback, short catch) verify each detector fires and a clean stroke scores ≥ 85.
