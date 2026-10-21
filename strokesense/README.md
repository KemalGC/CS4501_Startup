# StrokeSense — markerless rowing technique analysis

Drop in ordinary side-on video (erg or launch footage of a full crew). StrokeSense finds every rower,
maps their joints with a pretrained pose model (no markers, no sensors), splits the footage into
strokes, and flags technique faults with coaching cues. For crews it also measures **who is early or
late at the catch**.

Outputs (in `results/<video name>/`):

| File | What it is |
|---|---|
| `<video>_annotated.mp4` | The clip with each rower's skeleton, seat label, live body angle and stroke rate |
| `report.html` | Coaching report: per-seat score, top faults + cues, catch/finish snapshots, sequencing chart, crew timing chart |
| `metrics.json` | Every stroke's numbers, for further analysis |
| `pose.npz` | Cached joint positions (re-runs skip the slow step) |

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

Useful flags: `--tiles 1|2|3` (split wide frames so small, distant rowers are found; `auto` picks),
`--fps 30` (finer catch-timing resolution, ~2× slower), `--fresh` (ignore the cached pose).

Speed: pose detection is the slow step — about 7 minutes for a 37 s 1080p clip of a full eight on a
2-core CPU (faster with more cores). It is cached in `detections.npz`, so re-running the analysis or
re-rendering takes ~2 minutes.

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

## Tests

```powershell
python tests\test_analysis.py
```
Synthetic rowers with injected faults (shooting the slide, early arms, rushed slide, late body prep,
excess layback, short catch) verify each detector fires and a clean stroke scores ≥ 85.
