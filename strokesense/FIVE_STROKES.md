# Five-stroke assessments and independent stroke windows

## Launch and rerun

Update `dev/strokesense-2026-10-26`, stop the old server, and from the outer strokesense directory run:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

Open a fresh `http://127.0.0.1:8766/library` tab, choose the saved permitted clip, review its reference frame, confirm eight rowers from the same boat and start a NEW analysis. No deletion/re-upload is needed. Existing reports remain unchanged. The launcher banner did not change in this increment.

## Five usable strokes per rower

Five accepted cycles are enough for the application's **Short assessment ready** label. One to four cycles remain available but marked **Preliminary: N of 5 usable strokes**. The app does not manufacture cycles to reach five, and five is a short-assessment policy rather than proof of statistical reliability or coach-approved technique. A single cycle displays **Not enough cycles** for consistency instead of100/100. Technique scores are provisional heuristics; independent coaching-release safeguards remain.

A tiny detector dropout previously split a rower's entire continuous segment. Selected analysis can now join only internal gaps up to0.2seconds, with at least90% observations in each scored cycle and observed catch/finish/next-catch landmarks plus their immediate neighbors. Longer gaps and leading/trailing absence are not bridged. Stored missing keypoints remain missing. Each accepted cycle discloses observed and estimated-gap frame counts.

## Segmentation and parallel work

Detection and identity tracking run sequentially first. Catch-to-catch cycles are then measured independently using up to four threads, with deterministic output order. The one-worker mode provides a serial reference. Model inference, frame decoding and rendering are not parallelized by this change; it is not a promise of faster overall video processing.

Each rower card contains **Stroke-by-stroke windows** with source-video catch, finish and next-catch timestamps and observation counts. Saved JSON also contains a version1 `stroke_windows` manifest. This divides the analysis into logical video intervals; it does NOT export a separate MP4 file for every stroke. Legacy evidence with unknown observation counts uses null rather than invented data.

## Report robustness and detection status

The pending report-stage smoothing bug was repaired: missing/nonfinite tracks are handled in separate finite spans rather than causing SciPy's edge fit to fail. Optional annotated video still needs an already installed local FFmpeg/H.264 encoder; absent encoding can leave report-only results. The exact original Windows crash was not reproduced here.

Duplicate crop detections are merged using shared confident torso landmarks, reducing the chance of suppressing adjacent rowers solely because their boxes overlap. This is not a new hull detector, trained model, or guarantee against identity swaps. Same-boat confirmation and conservative missing-identity handling remain.

Actual YOLO11n-pose CPU inference was tested on two CC BY-SA4.0 Commons development videos: Splash tv's Rowing boat racing 8-man + cox, and Jan Ainali's Rowing in Amsterdam. On a25-frame8-rower sample, observed assignments improved171/200->183/200, but some individual slots declined and no identity ground truth was available. On the longer150-frame segment, BOTH strict and short-gap processing produced onlyONE usable stroke, and no rower reached five. The overall detection/tracking quality task remains open in#103. More boxes/coverage do not establish accuracy; no empirical coaching claim is made.

Synthetic eight-cycle dropout regression improved0->7 usable cycles without changing487/495 actual observed frames. Serial and parallel multiple-cycle results match. The complete local offline suite passed531executions plus four legacy checks. See root llm.md and#102–#104 for exact commands, real-model artifacts and limitations. Human/Windows validation remains pending.

## Reproduce tests

From repository root:

```text
python -m unittest discover -s strokesense/tests -p test_short_strokes.py -v
python -m unittest discover -s strokesense/tests -p test_stroke_windows.py -v
python -m unittest discover -s strokesense/tests -p test_report_gaps.py -v
python strokesense/quality.py
```

Real-video evaluation is explicit and separate from offline CI. It uses pinned CPU dependencies and official upstream model weights, retains attribution/source/model hashes, and never uploads private user recordings. Source pages and complete observed results are in llm.md and the real-video-comparison workflow artifact.
