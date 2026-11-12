# Experimental model-only blade-entry rate

This mode follows one operator-confirmed blade and asks a local vision model whether it is in air, in water, or unknown in each sampled source frame. SPM is calculated from repeated entries of that SAME blade, not from all eight blades added together. This is an experimental model adapter and evidence viewer, not a validated high-accuracy rowing model.

## What it replaces in this mode

No pose/body-angle peak finder, manually coded technique-fault rules, posture curves or numerical technique grades run in this path. The model classifies images; independent code checks its schema/frame IDs and computes entry-to-entry time. Mathematical timing and validation remain deterministic. The original pose-based workflow remains separately available and is never an automatic fallback for a model failure.

A run retains the longest continuous supported sequence. Six entries define five cycles: `SPM = 60 * 5 / (last_entry_time - first_entry_time)`. Five cycles meet the short-sample target, not an accuracy guarantee. Unknown/identity-lost frames, inconsistent overlapping-window answers and large sampling gaps break the sequence. Repeated underwater frames do not create new entries. Sampling bounds do NOT account for visual model error. Catch here means model-inferred blade contact, not independently labeled ground truth.

## Local setup (explicit operator installation)

Use an already installed Ollama version supporting the chosen vision model and structured outputs. Install/download models separately through trusted official distribution; StrokeSense never pulls one automatically. A generic local model example is `qwen3-vl:4b`; it is NOT validated here as a good rowing detector, and CPU inference can be slow. Larger models are not automatically more accurate for this task. Do not choose a `-cloud` model.

To disable cloud features, set `OLLAMA_NO_CLOUD=1` in the environment of the OLLAMA SERVER before starting it. Setting this only in StrokeSense's shell does not change an already-running Ollama server. Stop an existing Ollama instance before starting another server on the same port. A separately managed local server can be started in PowerShell with:

```powershell
$env:OLLAMA_NO_CLOUD = "1"
ollama serve
```

In another PowerShell window, explicitly install the chosen model only when you accept its download/storage requirements:

```powershell
ollama pull qwen3-vl:4b
ollama list
```

After updating the development integration branch and stopping the old StrokeSense process, run from the outer project directory:

```powershell
Set-Location "C:\Users\kemal\CS4501_Startup\strokesense"
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766 --blade-model qwen3-vl:4b
```

Open a fresh `http://127.0.0.1:8766/library`, find the saved permitted clip, and click **Model-only blade rate (experimental)**. Choose a frame showing a clear blade, click its blade tip/face (not the handle, rower or splash), confirm that it belongs to your intended boat, and submit. The timestamp selector lets you choose a later reference. Arrow keys or normalized X/Y fields provide alternate point controls. Changing the point clears confirmation.

When `--blade-model` is configured, imports that request selection open the blade confirmation route. Without that option, the older selection/import path remains unchanged; the new library link explains missing configuration. Existing reports are not rewritten and no deletion/re-upload is needed. Keep the server window open. This is a rate-only report; technique coaching remains withheld.

## Limits, provenance and privacy

The local endpoint is `http://127.0.0.1:11434`. The adapter refuses nonnumeric/remote hosts, proxies, redirects, cloud-tag models and remote model metadata. It checks an installed vision-capable model and stable digest before/after processing. These checks assume a trustworthy local server; they are not a sandbox against a malicious local daemon. No paid API, private cloud upload or hidden download was introduced.

At most20 seconds around the reference are sampled at approximately10fps using decoded source timestamps, up to320frames and40MiB of private JPEG evidence. Requests use24-frame windows with4-frame overlaps and a fixed marked reference. Each request has a120-second bound; the existing isolated job has a3600-second upper bound. The model should classify only one reference blade, but may confuse identity/contact despite instructions. Failures never trigger heuristic fallback. Small or occluded blades may be unavailable.

The report includes rate, supported cycles, unknown-frame counts, entry-time brackets and up to8 before/after picture pairs. Private `metrics.json` retains all states, source times, frame hashes, selected point, sampling settings and model digest. Source permission and content hashes are checked. Schema validation does not establish visual correctness, and agreement across windows is not independent truth. Treat the output as a hypothesis to review, not a coaching diagnosis.

## Verification status

Synthetic response tests cover repeated water, initial immersion, six entries/five cycles, unknowns, identity loss, duplicate/extra/wrong frame fields, invalid times, conflicting overlaps, local-only provider checks and no body-rule fallback. HTTP tests cover explicit confirmation, permissions and native controls. A real private video was decoded, but this development environment has no live Ollama model. No real blade-contact accuracy or improvement has been established. The next required evaluation is a permitted, independently labeled same-blade video with precision/recall, event timing and SPM error, plus unavailable-coverage reporting. Keep issues106 and103 open until their respective live quality requirements are satisfied.

## Primary documentation consulted

- USRowing terms (catch/rate): https://usrowing.org/learn-about-rowing/terminology
- Ollama vision images: https://docs.ollama.com/capabilities/vision
- Ollama JSON-schema outputs: https://docs.ollama.com/capabilities/structured-outputs
- Installed model names/digests: https://docs.ollama.com/api/tags
- Local show/chat API: https://github.com/ollama/ollama/blob/main/docs/api.md
- Disable cloud FAQ: https://github.com/ollama/ollama/blob/main/docs/faq.mdx
- Example generic vision family: https://ollama.com/library/qwen3-vl

These documents describe model/API availability, not rowing-specific validation. No live model result or large accuracy gain is implied by their use.
