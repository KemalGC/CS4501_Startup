# StrokeSense — Video-based rowing technique analysis

**StrokeSense** analyzes rowing footage using markerless computer vision, highlights recurring technique patterns, and produces a visual coaching report for individual rowers or a crew. It is a prototype intended to support—not replace—a rowing coach's judgment.

## Report preview

![Illustrative StrokeSense HTML report with technique findings and crew timing](docs/strokesense-report-preview.svg)

*Illustrative preview with synthetic values. This image shows the style and content of the browser-viewable report; it is **not** a screenshot from a real video analysis or a coach-validated score.*

### Example rowing analysis

Imagine filming an eight-person crew from a launch, side-on, for a short piece. For this **synthetic example**, the stroke seat's report contains:

| Example measurement | Illustrative result | Interpretation |
| --- | --- | --- |
| Stroke rate | 22 spm | Estimated strokes per minute |
| Strokes analyzed | 10 | Strokes with usable measurements |
| Early arm bend | 4 of 10 strokes | Rule flags early elbow flexion during the drive |
| Catch offset | +42 ms | Catch was later than the crew median on average |

A coach could review the highlighted frames and sequencing chart, investigate early arm bend, and compare a later clip from the same camera angle. **These numbers are for illustration, not measured results from a particular athlete.**

## What is implemented now

- Processes a local **side-on erg video or launch footage of a crew**.
- Uses pretrained **YOLO11-pose via ONNX Runtime** for markerless person and joint estimation.
- Identifies rowers, segments strokes, and estimates body angles, rate, and drive/recovery sequencing.
- Flags recurring movements using explicit configurable heuristics (for example, early arms, shooting the slide, rushed recovery, too much layback).
- Estimates crew catch timing per seat relative to the crew median.
- Creates an **annotated video**, an **HTML coaching report**, and **JSON metrics**.

The current report can be opened in a browser, but **the application is currently a Python command-line analyzer—not a hosted upload website or an LLM coach**.

## Run locally

For complete details, see the teammate-maintained [StrokeSense setup guide](strokesense/README.md). The root README summarizes the existing interface; it does not replace those technical instructions.

Requirements: Python 3 and the packages listed in the project requirements. FFmpeg is optional but useful for MP4 output.

### Windows PowerShell (from repository root)

~~~powershell
cd strokesense
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# A single indoor rower:
python -m strokesense.cli "C:\path\to\erg.mp4" --single

# A side-on crew clip:
python -m strokesense.cli "C:\path\to\crew.mp4" --start 5 --duration 30
~~~

For macOS/Linux, activate the environment with source .venv/bin/activate and use python3 if needed.

Successful runs write to a results folder named for the input video. Open its report.html in a browser to view technique cards, photos, and charts.

### Deterministic detector tests

~~~powershell
cd strokesense
python tests\test_analysis.py
~~~

These tests inject known technique patterns into **synthetic pose sequences**. They do **not** establish diagnostic accuracy on real rowing videos.

## Proposed generative-AI extension for CS 4501

The current pose pipeline provides measured findings. The planned startup product would add an **LLM coaching layer** that converts supported findings into a concise, tailored explanation and drill using a coach-approved cue library. An **independent validator** would check its cited seat/stroke IDs, measurements, and allowed cue IDs before publication. A failed candidate would return to the LLM for a bounded retry, with unresolved cases withheld.

**These LLM generation, validation, and retry features are planned, not present in the current code.** See the [selected startup proposal](README-startups/readme-startupSelected.md) for the eight project criteria and delivery plan.

## Accuracy and privacy limits

- Single-camera 2D body angles depend on camera alignment, visibility, and occlusion. Full-crew seat tracking can be unreliable with overlapping rowers.
- Coaching thresholds are exploratory heuristics requiring real footage and coach-label validation; an automatically calculated score is not proof of athlete skill or improved speed.
- Use footage with athletes' consent. Do not commit identifiable practice video or private results to a public repository.
- StrokeSense does not diagnose injury or replace professional coaching.
