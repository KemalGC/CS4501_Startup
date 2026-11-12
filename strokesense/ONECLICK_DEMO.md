STROKESENSE / ONE-CLICK EIGHTS ANALYSIS

The prepared video is IMG_5092_eights_16s.mp4. It is the exact 16-second
window (10-26 seconds) used in the Alpha presentation.

WINDOWS: Double-click START_DEMO_WINDOWS.bat. The first launch sets up
Python dependencies if internet is available. If your browser does not
open automatically, go to http://127.0.0.1:8768/ yourself.

MAC / LINUX: In a terminal, run:
    bash START_DEMO_MAC_LINUX.sh
Then open http://127.0.0.1:8768/ in your browser.

1. The clip is already loaded, so you DO NOT need to select a file.
2. Watch it, then click ANALYZE NOW.
3. The model starts a FRESH pose-analysis process on your computer.
4. The status panel tracks pose frames and report generation.
5. After it finishes, open the generated report and annotated video.

The video is H.264 960x540, 24 fps, exactly 16 seconds. The analysis
uses 10 requested inference FPS, CPU execution, and dominant-crew mode.
There is NO live cloud inference in the ChatGPT review website. This is
a separate localhost demo (private to your computer). It does not add
or change participant feedback in the seven-clip study.

First analysis can take several minutes on CPU and may download the
YOLO11n-pose ONNX model (~10 MB) if not yet cached. An internet
connection is needed for initial dependency/model setup. FFmpeg is
recommended to generate a browser-compatible annotated MP4; missing
video encoding will leave a report without an overlay. Installation:
Windows: winget install Gyan.FFmpeg    macOS: brew install ffmpeg

The report is an unverified model output, NOT coaching ground truth.
If no trustworthy stroke/crew observations exist, analysis may fail
or withhold a shared SPM rather than invent a number. For the Alpha talk,
keep the precomputed 19.1 SPM saved report in the public review website
as a backup when you cannot wait for fresh CPU inference to finish.

Testing: from inside the bundled strokesense/ folder run
    python -m unittest discover -s tests -p test_oneclick_demo.py -v
The eight included tests use an explicitly FAKE analysis subprocess;
they verify one-click HTTP mechanics, not real model accuracy.

Source repo: https://github.com/KemalGC/CS4501_Startup
Public review: https://strokesense-review.kemalgcortuk.chatgpt.site/
