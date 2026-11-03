# Crew-vision performance controls

This update targets **Choose crew analyses**. It does not rewrite the legacy pose analyzer or promise fast/accurate Qwen results on every computer.

After safely updating the development integration branch, stop the old server and launch from the outer strokesense folder:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766 --crew-model qwen3-vl:4b
```

Use /library -> Choose crew analyses. The same already-installed local model is required; no new download, cloud service, paid provider or GPU deployment is added. Select only the tasks needed. Old reports are unchanged; rerun saved permitted clips without deleting/re-uploading them.

## Changes

The model returns compact per-frame/per-rower records, then the original strict identity/task validators check the expanded output. Position reviews may crop unused scene margins while preserving each retained pixel's scale. Blade-rate and timing keep the full scene. A crop with uncertain, mismatched or boundary-touching subjects falls back to full-frame review. A network timeout/truncated response fails without wasting another request on a larger image.

An exactly matching marked reference/first sample is sent once, not as two separate encodes. All source frame IDs remain represented. The private cache under the jobs results parent reuses only an identical model digest, inputs, prompt, schema and settings. Cached responses are revalidated, and source permission/content checks still apply. Unknown model observations remain unknown; cache reuse does not make them correct.

The cache is bounded to128 small response files and contains no source images, but it can contain private model-predicted locations. It stays in local result storage, never GitHub. Set the following before launch to force fresh inference:

```powershell
$env:STROKESENSE_VISION_CACHE = "0"
```

For an explicit comparison with the previous verbose crew adapter:

```powershell
$env:STROKESENSE_VISION_SPEED = "0"
```

Unset those variables or set them to1 to restore the defaults. Do not delete the video registry to clear a model request cache.

## Evidence and interpretation

`metrics.json` records actual network-request count, cache hits, request durations and backend token/timing fields when supplied under `processing.vision`. Use `processing.vision.submitted_images` for actual submitted image count; the historical top-level model_images field counts logical reference/sample inputs before deduplication. Do not call pixel count or test-double timing an observed Qwen speedup.

The first real public-video benchmark in this session timed out on both source-frame samples, yielding no SPM or posture result. Its crop did not clearly reduce the runtime's image-token batches. That failure led to two additional test-first fixes: remove the repeated reference encoding and stop retrying transport timeouts. The corrected live test outcome is recorded in issue109 after retrieval. No accuracy improvement is implied by passing software tests. Private videos were decoded locally but not sent to remote inference. Windows timing and independently labeled model accuracy remain unverified.

Official API background: https://docs.ollama.com/api/chat and https://docs.ollama.com/capabilities/structured-outputs . API support is not rowing-model validation.
