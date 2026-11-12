# Automatically detect people, then confirm one crew

Use the current `dev/strokesense-2026-10-26` branch after integration. Stop the old server before updating. From the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

The library-enabled launcher retains uploads, reports, evidence, and removal. The legacy `strokesense.web` launcher also receives the updated selection screen but does not expose library-management routes. Their startup banners are unchanged by this increment.

Open a fresh `http://127.0.0.1:8766/library` tab. For a permission-granted saved clip, click **Choose rowers**; re-uploading or removing it is unnecessary. A new upload with the existing choose-eight-rowers option checked also opens the selection screen.

## Confirmation flow

The selection page runs the existing local pose detector on the first frame when ONNX Runtime and the cached pose model are available. On a CPU, preparing this preview can take time. It does not run the entire video first.

1. Inspect the numbered **Person** boxes. Nothing starts selected.
2. Click the eight people in your boat, or use the labeled checkbox controls. Exclude the coxswain and people in other boats. Selection order becomes Selected 1 through Selected 8; these labels are not automatically inferred official seat numbers.
3. Check **I confirm these eight rowers are all in the same boat**.
4. Press **Analyze selected crew**. The button remains disabled until eight are selected. Changing the selection clears the same-boat confirmation.

A ninth selection is refused until a person is deselected. **Reset selection** clears the choices. Boxes for which no unambiguous initial point can be found are disabled. Fewer than eight usable detections requires a clearer recording or the existing manual fallback.

## Requirements and limitations

Automatic preview detection requires the existing ONNX Runtime installation and the cached `models/yolo11n-pose.onnx` used by the analyzer. An ordinary missing-model/runtime check returns an explicit fallback message rather than initializing the detector. No new model installer, provider API, cloud processing or dependencies were added. The diagnostic command `python quality.py --doctor` identifies prerequisites; it does not test inference.

**Use manual selection** retains the prior boat-region/touch/numeric controls. A missing model, busy preview, failed detector, no people, or excessive candidates also leaves manual selection available. Preview model work is serialized within the process; one initialized model is reused. There is no cross-request cache of private preview images.

All eight targets must be visible in the first frame. Automatic mode uses the full frame for matching detection geometry; the confirmed eight are the closed selected crew. Manual mode uses its existing fixed region. The detector does not determine which physical boat someone belongs to, and it does not distinguish the coxswain for you.

**This improves initial selection, not every later tracking failure.** Occlusion, overlapping detections, camera movement or ambiguous association can still produce `selected_crew_lost_or_ambiguous`. Existing checks are retained rather than silently filling a missing seat from another boat. Preview inference and full analysis use the same resize/tiling conventions, but no perfect real-world identity guarantee is claimed.

Permission, content integrity, same-origin forms, CSRF, stored-selection validation, retry and cache identity are unchanged. This feature does not grant analysis permission or alter old reports.

## Reproducible engineering checks

From repository root:

```text
python -m unittest discover -s strokesense/tests -p test_auto_selection.py -v
python strokesense/quality.py
python strokesense/quality.py --doctor
python strokesense/tests/browser_auto_selection.py
```

The last command needs the existing test-only Playwright dependency and installed Chrome/Chromium. It uses generated footage, synthetic detection proposals and a fake analyzer, not real rowing inference. The existing browser crew-selection entrypoint now executes both the old manual flow and automatic confirmation. Tests do not establish detection accuracy, coach approval, or Windows usability. See issue #98 and the root manual handoff companion for exact verification results.
