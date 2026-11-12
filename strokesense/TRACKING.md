# Moving-crew tracking and later-frame selection

## Launch

After updating `dev/strokesense-2026-10-26`, stop the old server and start the library-enabled application from the outer `strokesense` directory:

```powershell
.\.venv\Scripts\python.exe -u -m strokesense.library --port 8766
```

The banner includes `multi-frame-review-v1`. Keep PowerShell open. Open a fresh `http://127.0.0.1:8766/library` tab and choose **Choose rowers** on a permission-granted saved clip. New uploads with crew selection enabled also open this review. No re-upload/deletion is needed for a permitted saved clip. The legacy `strokesense.web` launcher keeps first-frame selection and does not expose the library review workflow.

## Review a clearer frame, then confirm

The local review samples up to five source-aligned frames across the first20 seconds. Frame buttons show timestamps and detected-person counts. Select a clearer later frame when the beginning misses people. The view initially displays the frame with the most usable candidates, but no rowers are preselected.

Inspect a **Suggested boat** group, or show all people and choose one crew yourself. The groups are geometric proposals based on aligned detected people, not verified hull segmentation. Higher-resolution crops of up to two proposed crews refine the person detections. Widely separated aligned groups are split, but overlapping/nearby boats can still be confused.

Select exactly eight distinct rowers in that reference frame, excluding the coxswain and other crews. Use the labeled checkboxes when boxes overlap. Confirm that the eight belong to one boat, then press **Analyze confirmed crew**. Changing the reference/group or selected people clears the confirmation. The frame timestamp and exact detector-derived seeds are saved with the job; no analysis starts before submission.

## During analysis

Version2 selected analysis searches the moving full scene, including boat-focused refinement on every analyzed frame. It tracks forward and backward from the confirmed reference. The initial region is no longer a permanent boundary that loses the boat when it moves.

Missing or ambiguous later observations are gaps, not fatal errors and not invented poses. Short unique reacquisition is possible within a bounded0.75-second absence; longer loss retires the slot for that run rather than claiming a different person is the same rower. Exactly the eight selected identities remain. Only uninterrupted visible intervals contribute complete strokes. Reports expose observed/total/missing frame counts and insufficient continuous evidence instead of a clean-technique claim when no usable cycle exists.

The initial reference still needs eight unambiguous detections together. Later-frame review does not combine unrelated detections across different frames into proven identities. Motion association cannot guarantee identity through crossings. A permanent exit need not fail the job, but naturally reduces available measurements. Refinement adds model work and is not a promise of faster processing.

## Dependencies, compatibility and evidence

Review needs the already installed ONNX Runtime and cached `models/yolo11n-pose.onnx`. Missing prerequisites show manual-selection guidance; no cloud upload, live LLM or automatic model installer was added. `python quality.py --doctor` is read-only diagnostics, not an inference test. Use **Manual first-frame selection** when review is unavailable.

Existing v1 selections, CLI operation, upload/permission/CSRF checks and library management remain. Selected pose-cache identity changes to `dynamic-refined-full-frame-v3`; older selected extraction is recomputed. Old reports are not rewritten. Tracking coverage is observation coverage, not measured identity accuracy or coaching confidence. Candidate technique faults remain unreviewed and generated coaching remains withheld without independent approval.

Tests from repository root:

```text
python -m unittest discover -s strokesense/tests -p test_temporal_handoff.py -v
python -m unittest discover -s strokesense/tests -p test_dynamic_crew.py -v
python -m unittest discover -s strokesense/tests -p test_multiframe_review.py -v
python -m unittest discover -s strokesense/tests -p test_review_routes.py -v
python strokesense/quality.py
python strokesense/tests/browser_multiframe_review.py
```

The browser command needs installed Chrome/Chromium and test-only Playwright. Its person detections/analyzer are synthetic test doubles. The uploaded MP4 was decoded and sampled locally, but no real-model detection/accuracy evaluation was possible in the implementation environment because the runtime/model were missing. Real Windows/model verification and coach-reviewed measurements remain outstanding.
