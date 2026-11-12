# StrokeSense — deploy the real-analysis demo on Render

This **dedicated deployment branch** contains a single-service Render Blueprint.
It does not deploy the separate seven-clip study, touch `main`, or change survey data.

## 1. Deploy the paid web service

[Deploy this branch to Render](https://render.com/deploy?repo=https://github.com/KemalGC/CS4501_Startup/tree/strokesense-render-live)

Sign in to **your Render account**, connect GitHub if prompted, select the billing-enabled workspace and inspect the Blueprint before clicking **Apply/Deploy**.

The root `render.yaml` defines only:
- `strokesense-real-analysis-demo`: Python web service with ONNX Runtime, OpenCV and the actual StrokeSense CLI.
- **2 CPU / 4 GiB RAM** (`2c-4g`, paid); Virginia region; one instance; 2 GB private persistent disk.
- `STROKESENSE_DEMO_OWNER_KEY` is generated and stored in Render's secret environment settings.
- Automatic redeploys disabled to keep the demo stable.

Render's published compute price for `2c-4g` is **$85/month** plus persistent storage.
You approve billing in Render; this repository cannot charge you.

## 2. Prepare Video Project 19 (1).mp4 privately

When the service shows *Live*, open its actual Render-generated `https://…onrender.com/healthz` URL. It should return `{"ok":true,"demo_video_ready":false}` before preparation.

Open `https://…onrender.com/setup` on the same hostname. Enter the `STROKESENSE_DEMO_OWNER_KEY` value from the Render service's Environment settings and select the 12.8s **Video Project 19 (1).mp4** supplied for the course demonstration. The input is uploaded privately; video bytes must never be committed to the public GitHub repository.

Successful setup returns a prepared status; refreshing `/healthz` reports `demo_video_ready:true`.

## 3. Run the real analysis

Open `https://…onrender.com/demo`, where the clip is preloaded.
Press **Analyze now**. The click starts a genuine isolated process:
`python -m strokesense.cli prepared.mp4 --out /var/data/demo/outputs --fps 10 --dominant-crew --threads 2`.

The page polls `/api/demo/status` and exposes `/demo/report` and
`/demo/annotated` *only* when the subprocess has produced and validated
actual saved report, `metrics.json`, and overlay media. Some clips may be rejected
by the analyzer; fewer than eight observed rower candidates and unavailable
shared cadence are explicitly disclosed.

The first run may have to download the pose model. Keep the service alive
and check its logs if the model cannot download or process the video.
The CPU step may take several minutes.

## 4. Keep the seven-clip survey as the presentation's first step

[Public seven-clip reviewer site](https://strokesense-review.kemalgcortuk.chatgpt.site/)
remains separate. Its existing **Optional demos** tab does not automatically acquire
this new backend. After the Render host is verified, the site owner must connect
the actual deployed `/demo` URL using the ChatGPT Sites publishing/editor capability.
Until then, share the Render demo URL separately or link it in the Slides.

Do not describe the site as freshly analyzing entire eights unless you have
observed a real model job and inspected its saved report for that video.

## Verification

The real subprocess/HTTP endpoint has regression tests; the results are not field
measurements. See PR #131 (hosted one-click demo), PR #132 (crew metrics gate).
Run `python -m unittest discover -s hosting_tests -p test_hosted_oneclick_demo.py -v`
under the `strokesense/` working directory after installing `requirements-demo-hosted.txt`.

**Deployment status:** prepared, not publicly verified until the owner completes
Render's Blueprint approval and the source video upload.
