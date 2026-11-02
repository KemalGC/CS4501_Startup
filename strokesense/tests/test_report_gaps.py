"""Reports must tolerate genuine tracking gaps; synthetic poses, real artifacts."""
from contextlib import redirect_stderr
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from scipy.signal import savgol_filter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import analysis_worker, cli, evidence, jobs, kinematics, render
from synthetic import make_rower
from test_selected_crew import selection


class GapSmoothingTests(unittest.TestCase):
    def test_finite_input_matches_existing_filter_exactly(self):
        rng = np.random.default_rng(19)
        for shape in ((60,), (60, 2), (60, 2, 3)):
            with self.subTest(shape=shape):
                values = rng.normal(size=shape)
                before = values.copy()
                np.testing.assert_array_equal(
                    kinematics.smooth(values, 15),
                    savgol_filter(values, 5, 2, axis=0))
                np.testing.assert_array_equal(values, before)

    def test_missing_prefix_suffix_and_internal_gap_are_not_filtered_or_bridged(self):
        left = np.sin(np.linspace(0, 3, 20))
        right = 100 + np.cos(np.linspace(0, 4, 23))
        values = np.r_[np.full(7, np.nan), left, np.full(4, np.nan), right, np.full(6, np.nan)]
        before = values.copy()
        filtered = kinematics.smooth(values, 15)
        np.testing.assert_array_equal(np.isnan(filtered), np.isnan(values))
        np.testing.assert_allclose(filtered[7:27], savgol_filter(left, 5, 2))
        np.testing.assert_allclose(filtered[31:54], savgol_filter(right, 5, 2))
        np.testing.assert_array_equal(values, before)

    def test_coordinate_channels_preserve_independent_finite_spans(self):
        values = np.c_[np.linspace(0, 1, 40), np.sin(np.arange(40))]
        values[:6, 0] = np.nan
        values[17:20, 0] = np.nan
        values[-9:, 1] = np.nan
        filtered = kinematics.smooth(values, 15)
        self.assertEqual(filtered.shape, values.shape)
        np.testing.assert_array_equal(np.isfinite(filtered), np.isfinite(values))
        for column, spans in ((0, ((6, 17), (20, 40))), (1, ((0, 31),))):
            for start, end in spans:
                np.testing.assert_allclose(filtered[start:end, column],
                    savgol_filter(values[start:end, column], 5, 2))

    def test_empty_all_missing_and_short_spans_do_not_invent_observations(self):
        for values in (np.empty((0, 2)), np.full(20, np.nan),
                       np.array([np.nan, 1., 2., np.nan, 3., 4., np.nan])):
            with self.subTest(shape=values.shape):
                filtered = kinematics.smooth(values, 15)
                np.testing.assert_array_equal(filtered, values)

    def test_infinities_are_unavailable_not_spread_into_finite_spans(self):
        values = np.r_[np.inf, np.arange(15, dtype=float), -np.inf, np.arange(15, dtype=float)]
        filtered = kinematics.smooth(values, 15)
        np.testing.assert_array_equal(np.isfinite(filtered), np.isfinite(values))
        self.assertTrue(np.isnan(filtered[[0, 16]]).all())
        np.testing.assert_allclose(filtered[1:16], savgol_filter(values[1:16], 5, 2))
        np.testing.assert_allclose(filtered[17:], savgol_filter(values[17:], 5, 2))


class ReportGapPipelineTests(unittest.TestCase):
    def test_partial_crew_with_real_strokes_completes_photos_charts_json_without_video_encoder(self):
        keypoints, fps = make_rower(rate=34, n_strokes=7, fps=15, catch_angle=8)
        count = len(keypoints)
        tracks = {}
        for tid in range(8):
            observed = np.ones(count, dtype=bool)
            observed[:8 + tid] = False
            observed[-(10 + tid * 4):] = False
            observed[70 + tid:76 + tid] = False
            if tid in (4, 5):
                observed[20:] = False  # Same closed identity, insufficient evidence.
            frames = np.flatnonzero(observed)
            tracks[tid] = {'frames': frames, 'boxes': np.tile([220., 150., 500., 400.], (len(frames), 1)),
                           'kpts': keypoints[frames].copy()}
        before = copy.deepcopy(tracks)
        meta = {'width': 640, 'height': 480, 'fps': fps, 'start': 0., 'stride': 1}
        detections = [(np.empty((0, 4)), np.empty((0, 17, 3))) for _ in range(count)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'synthetic.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), fps, (640, 480))
            self.assertTrue(writer.isOpened())
            try:
                for _ in range(count):
                    writer.write(np.full((480, 640, 3), 90, np.uint8))
            finally:
                writer.release()
            model = root / 'fixture.onnx'
            model.write_bytes(b'synthetic unused model')
            messages = []
            # Only inference/association and optional encoder availability are doubles.
            # Do not mock snapshots, smoothing, charts, report/evidence or JSON serialization.
            with patch.object(cli, 'PoseDetector'), \
                 patch.object(cli, 'run_selected_video', return_value=(detections, meta)), \
                 patch.object(cli, 'locked_tracks', return_value=tracks), \
                 patch.object(render, '_ffmpeg', return_value=None):
                result = cli.analyse_video(video, out_dir=root/'results', model=model,
                    selection=selection(), log=messages.append)
            self.assertIsNone(result['video'])
            self.assertTrue(any('Done in' in message for message in messages))
            body = result['report'].read_text(encoding='utf-8')
            self.assertIn('Annotated video unavailable', body)
            self.assertIn('Tracking coverage', body)
            self.assertIn('Insufficient continuous evidence', body)
            self.assertIn('fault-photo', body)
            self.assertIn('data:image/jpeg;base64,', body)
            self.assertIn('data:image/png;base64,', body)
            metrics = json.loads((result['report'].parent/'metrics.json').read_text())
            self.assertEqual(len(metrics['rowers']), 8)
            self.assertTrue(evidence.validate_reference_graph(metrics['evidence']))
            self.assertGreater(len(metrics['evidence']['strokes']), 0)
            self.assertTrue(all(not f['coaching_eligible'] for f in metrics['evidence']['findings']))
            self.assertGreater(len(list(result['report'].parent.glob('fault_*.jpg'))), 0)
            for rower in result['rowers']:
                keep = np.zeros(count, dtype=bool)
                keep[tracks[rower.tid]['frames']] = True
                self.assertEqual(rower.summary['tracking']['observed_frames'], int(keep.sum()))
                self.assertTrue(np.isnan(rower.k.angles['trunk'][~keep]).all())
                for stroke in rower.strokes:
                    self.assertTrue(keep[stroke.catch:stroke.next_catch+1].all())
                for name in tracks[rower.tid]:
                    np.testing.assert_array_equal(tracks[rower.tid][name], before[rower.tid][name])


class WorkerFailureDiagnosticTests(unittest.TestCase):
    def test_caught_error_reports_fixed_category_without_private_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp)/'receipt.json'
            request = {'video': 'private-video.mov', 'out_dir': tmp, 'selection': None}
            err = io.StringIO()
            with patch.object(analysis_worker.sys, 'stdin', io.StringIO(json.dumps(request))), \
                 patch.object(jobs, '_default_analyze', side_effect=ValueError('SECRET /private/source.mov')), \
                 redirect_stderr(err):
                self.assertEqual(analysis_worker.main([str(receipt)]), 0)
            self.assertIn('(ValueError)', err.getvalue())
            self.assertNotIn('SECRET', err.getvalue())
            self.assertNotIn('/private/', err.getvalue())
            self.assertNotIn(tmp, err.getvalue())
            self.assertEqual(json.loads(receipt.read_text()), {'state':'failed', 'code':'analysis_failed'})

    def test_arbitrary_exception_type_name_is_not_disclosed(self):
        PrivateType = type('PRIVATE_CUSTOM_EXCEPTION_NAME', (Exception,), {})
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp)/'receipt.json'
            request = {'video': 'private-video.mov', 'out_dir': tmp, 'selection': None}
            err = io.StringIO()
            with patch.object(analysis_worker.sys, 'stdin', io.StringIO(json.dumps(request))), \
                 patch.object(jobs, '_default_analyze', side_effect=PrivateType('SECRET')), \
                 redirect_stderr(err):
                analysis_worker.main([str(receipt)])
            self.assertIn('(Exception)', err.getvalue())
            self.assertNotIn('PRIVATE', err.getvalue())
            self.assertNotIn('SECRET', err.getvalue())


if __name__ == '__main__':
    unittest.main()
