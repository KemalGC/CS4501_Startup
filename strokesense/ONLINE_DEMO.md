# StrokeSense: one-click real inference from a website

**Scope:** Optional compute-backed video demo only. Does not modify the existing
seven-clip Alpha feedback study, SQLite feedback, reviewers or owner exports.

**Source clip:** the user's `Video Project 19 (1).mp4` (12.8 seconds, H.264
1920x1080), an eight with the coxswain visible separately. The **private video
is NOT in GitHub**; keep consent and rights permission records with the owner.

## What is implemented

- `strokesense.web_demo_hosted:create_app` serves a real web page at `/demo`.
- An owner uses `/setup` to upload the supplied file once to a private
  persistent disk. File paths/names from the browser are ignored. The owner key
  is not saved in browser storage.
- On the first click of **Analyze now**, `DemoState.begin()` invokes the
  actual existing `python -m strokesense.cli VIDEO --out ... --fps 10
  --dominant-crew --threads 2` subprocess. No synthetic or precomputed
  result is returned. Model download/ONNX CPU inference may take minutes.
- `/api/demo/status` reports observed logs/progress; `/demo/report` and
  `/demo/annotated` appear only after verified output files exist. A failed
  run shows a failure instead of invented rowing scores.
- Original and generated video support HTTP byte-range playback.
- Only one public analysis run is allowed per running server instance, so an
  open site cannot cause unbounded concurrent provider/CPU charges. A restart
  cleans old disposable demo outputs before starting a new run.
- Demo data lives under `/var/data/demo`; participant feedback lives elsewhere.
  The hosted report is sandboxed and has no scripts or access to other files.

## Requirements

A paid compute-capable Linux web service is required. `requirements-hosted.txt`
for the survey deliberately **does not include** ONNX/OpenCV; this new service
uses `requirements-demo-hosted.txt`. The `render-demo.yaml` example selects
the **2c-4g paid** Render plan with one worker and a private persistent disk.
The owner must approve a charge and connect the hosting account before deploy.

Create a service using `render-demo.yaml` with its actual HTTPS origin
provided by Render. The backend derives the exact origin from
`RENDER_EXTERNAL_URL`. Keep `STROKESENSE_DEMO_OWNER_KEY` secret. Confirm
`/healthz` returns `ok=true`.

1. Open `https://<actual-demo-host>/setup`. Enter the Render owner key and
   choose the **12.8s Video Project 19 MP4** from the private setup package.
2. After the upload reports success, open `/demo`. The video is already
   loaded and seekable. Click **Analyze now**.
3. The browser polls actual job status. Review the generated HTML report and
   video overlay when complete. For a fresh demo in class, run in advance to
   verify output speed/quality; keep a recorded report as a separate fallback.
4. Add a **Live analysis demo** link/tab from the existing ChatGPT Sites review
   website once that site's publishing access is available. A separate Render
   service alone **does not update** the existing `.chatgpt.site` page.
   Never claim that site shows this button before observing the live page.

## Safety & verification

- The owner setup API enforces the exact public host and same-origin POST,
  constant-time bearer verification, bounded upload, MP4 MIME and container
  signature, atomic private storage, and a one-time install.
- This MP4 header check cannot guarantee a fully decodable video; the
  analyzer performs decoding and can fail visibly. Do not substitute a fake
  report on failure.
- Test-first coverage: `python -m unittest discover -s hosting_tests
  -p 'test_hosted_oneclick_demo.py' -v`. Synthetic subprocess fixtures in
  tests verify orchestration and isolation only, **not model quality**.
- CPU, memory and duration depend on input and host. The pose model may need to
  download from its source on first run. FFmpeg is optional for report success
  but may affect the encoded overlay. The full website run must be tested on
  the chosen host before calling it a live demo.
- The 7 reviewers filling out forms are not the 8 rowers visible in any video.
