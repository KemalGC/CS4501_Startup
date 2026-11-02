"""Pipeline regressions added while integrating observed-only measurements."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import dynamic_crew, kinematics, render, report, strokes
from test_short_strokes import selected_pose
from synthetic import make_rower

class MeasurementPipelineTests(unittest.TestCase):
    def test_missing_optional_joints_do_not_crash_overlay_or_crop(self):
        kp,fps=make_rower(noise=0);kp[:,7:9,2]=0;kp[:,15:17,2]=0
        k=kinematics.build(kp,fps)
        r=SimpleNamespace(k=k,seat='Synthetic',strokes=[])
        image=np.zeros((500,700,3),np.uint8)
        render.draw_rower(image,r,40,(80,100,120))
        self.assertGreater(render._crop_rower(image,r,40).size,0)

    def test_segmented_scoring_uses_saved_canonical_angles(self):
        kp,fps=make_rower(n_strokes=9,rate=30,noise=1)
        keep=np.ones(len(kp),bool);keep[90:110]=False;keep[250]=False
        r=dynamic_crew.rowers_from_selected(selected_pose(kp,fps,keep))[0]
        self.assertGreater(len(r.strokes),0)
        for s in r.strokes:
            self.assertEqual(s.trunk_catch,float(r.k.angles['trunk'][s.catch]))
            self.assertEqual(s.trunk_finish,float(r.k.angles['trunk'][s.finish]))

    def test_metrics_save_finite_provenance_with_missing_optional_angles(self):
        kp,fps=make_rower(noise=0);kp[:,7:9,2]=0;kp[:,15:17,2]=0
        r=dynamic_crew.rowers_from_selected(selected_pose(kp,fps))[0]
        self.assertGreaterEqual(len(r.strokes),5)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'metrics.json'
            report.build_json([r],{},path,analysis_key='synthetic',fps=fps)
            text=path.read_text();self.assertNotIn('NaN',text)
            data=json.loads(text)
        self.assertEqual(data['measurement_policy']['version'],'observed-motion-v1')
        counts=data['rowers'][0]['joint_observation_counts']['elbow']
        self.assertEqual(counts['observed'],0);self.assertEqual(counts['unavailable'],len(kp))
        self.assertEqual(data['rowers'][0]['sequencing']['arms']['count'],0)

    def test_peak_search_never_receives_nan_spans(self):
        from unittest.mock import patch
        kp,fps=make_rower(noise=0)
        kp[100:130,9:11,2]=0
        k=kinematics.build(kp,fps)
        with patch.object(strokes,'find_peaks',wraps=strokes.find_peaks) as peaks:
            strokes.find_strokes(k)
        self.assertTrue(peaks.called)
        self.assertTrue(all(np.isfinite(c.args[0]).all() for c in peaks.call_args_list))

    def test_missing_shin_at_phase_point_is_null_not_nan(self):
        kp,fps=make_rower(noise=0)
        original,_=strokes.analyse(kinematics.build(kp,fps))
        kp[original[0].catch,15:17,2]=0
        k=kinematics.build(kp,fps);found,_=strokes.analyse(k)
        matching=next(s for s in found if s.catch==original[0].catch)
        self.assertIsNone(matching.shin_catch)
        json.dumps([s.to_dict() for s in found],allow_nan=False)

if __name__=='__main__':unittest.main()
