"""Quick-rate contracts: generated media and model doubles, never accuracy labels."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import blade_video, blade_model


def selected():
    return {'version': 3, 'kind': 'blade_reference', 'reference_seconds': 0.,
            'point': [.3, .6], 'confirmed_same_boat': True}


class ModelDouble:
    def __init__(self, unknown=False): self.calls = 0; self.images = 0; self.unknown = unknown
    def check(self): return {'name': 'synthetic-double', 'digest': 'a'*64}
    def predict(self, reference, frames):
        self.calls += 1; self.images += len(frames) + 1
        return [{'frame_id': f['frame_id'], 'time': f['time'], 'same_blade': not self.unknown,
                 'state': 'unknown' if self.unknown else 'air' if f['frame_id'] % 20 < 10 else 'water',
                 'box': None if self.unknown else [.2, .5, .4, .7]} for f in frames]


class QuickBladeTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.blade_quick'),
                             'incremental two-entry processing is missing')
        from strokesense import blade_quick
        return blade_quick
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.video = self.root/'synthetic.avi'
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (128,96))
        self.assertTrue(writer.isOpened())
        for _ in range(200): writer.write(np.full((96,128,3), 100, np.uint8))
        writer.release()
    def test_default_worker_stops_after_two_supported_entries_not_full_clip(self):
        m = self.module(); model = ModelDouble()
        result = m.analyse_video(self.video, out_dir=self.root/'out', selection=selected(), provider=model, log=lambda _:None)
        saved = json.loads((result['report'].parent/'metrics.json').read_text())
        self.assertEqual(saved['blade_rate']['cycles'], 1)
        self.assertAlmostEqual(saved['blade_rate']['spm'], 30.)
        self.assertEqual(saved['blade_rate']['state'], 'provisional')
        self.assertEqual(saved['processing']['stop_reason'], 'target_reached')
        self.assertEqual(model.calls, 2)
        self.assertLess(saved['processing']['sampled_frames'], 60)
        self.assertGreater(saved['processing']['source_frames_available'], 150)
        self.assertEqual(saved['positioning_scope'], 'blade_not_body_posture')
        self.assertIn('Model-predicted blade position', result['report'].read_text())
    def test_worker_routes_to_quick_mode_without_pose_or_old_full_scan(self):
        self.module()
        from strokesense import analysis_worker
        with patch('strokesense.blade_quick.analyse_video', return_value={'report':'quick'}) as run, \
             patch('strokesense.blade_video.analyse_video', side_effect=AssertionError('old fixed scan')), \
             patch('strokesense.cli.analyse_video', side_effect=AssertionError('heuristic fallback')):
            result = analysis_worker.analyze_request('private',out_dir=self.root,selection=selected())
        self.assertEqual(result['report'],'quick');run.assert_called_once()
    def test_single_frame_contact_flicker_is_unknown_not_extra_rate(self):
        m=self.module()
        states=['air']*10+['water']+['air']*10+['water']+['air']*10
        obs=[{'frame_id':i,'time':i/10,'state':s,'same_blade':True,'box':[.2,.5,.4,.7]} for i,s in enumerate(states)]
        clean=m.stable_contacts(obs)
        self.assertIsNone(blade_model.summarize(clean)['spm'])
        self.assertEqual(clean[10]['state'],'unknown')
    def test_localization_is_required_finite_and_not_a_whole_frame_guess(self):
        m=self.module()
        valid={'frame_id':7,'state':'air','same_blade':True,'box':[.2,.5,.4,.7]}
        self.assertEqual(m.validate_positions({'observations':[valid]},[7])[0]['box'],valid['box'])
        for box in (None,[0,0,1,1],[.2,.5,2,.7],[.4,.5,.2,.7],[True,.2,.3,.4],[0,0,float('nan'),.4]):
            with self.subTest(box=box),self.assertRaises(blade_model.BladeModelError):
                m.validate_positions({'observations':[dict(valid,box=box)]},[7])
        with self.assertRaises(blade_model.BladeModelError):
            m.validate_positions({'observations':[dict(valid,frame_id=True)]},[7])
    def test_overlap_position_disagreement_breaks_identity(self):
        m=self.module()
        a={'frame_id':3,'time':.3,'state':'air','same_blade':True,'box':[.1,.1,.2,.2]}
        b=dict(a,box=[.7,.7,.8,.8])
        result=m.merge_positioned([[a],[b]])
        self.assertEqual(result[0]['state'],'unknown');self.assertFalse(result[0]['same_blade'])
    def test_unknown_model_never_falls_back_or_claims_rate(self):
        m=self.module(); model=ModelDouble(unknown=True)
        result=m.analyse_video(self.video,out_dir=self.root/'unknown',selection=selected(),provider=model,log=lambda _:None)
        saved=json.loads((result['report'].parent/'metrics.json').read_text())
        self.assertIsNone(saved['blade_rate']['spm'])
        self.assertEqual(saved['processing']['stop_reason'],'reference_unconfirmed')
        self.assertEqual(model.calls,1)
        self.assertEqual(saved['rowers'],[])
    def test_source_times_positions_and_late_reference_are_preserved(self):
        m=self.module(); target=self.root/'frames';target.mkdir(); info={}
        it=m.iter_samples(self.video,target,4.,info)
        try: frames=[next(it) for _ in range(4)]
        finally:it.close()
        self.assertEqual([f['frame_id'] for f in frames],[40,41,42,43])
        np.testing.assert_allclose([f['time'] for f in frames],[4,4.1,4.2,4.3])
        self.assertEqual(info['sampled_frames'],4)
        self.assertEqual(len(list(target.glob('*.jpg'))),4)
    def test_provider_requests_positions_and_warm_model_with_same_source_times(self):
        m=self.module();provider=m.PositionedVision('qwen3-vl:4b');provider.digest='a'*64
        answer={'done':True,'done_reason':'stop','message':{'content':json.dumps({'observations':[
            {'frame_id':3,'state':'air','same_blade':True,'box':[.1,.2,.2,.3]}]})},
            'total_duration':1000000000,'eval_count':35}
        with patch.object(provider,'_request',return_value=answer) as req:
            result=provider.predict('ref',[{'frame_id':3,'time':1.1,'image':'data'}])
        payload=req.call_args.args[1]
        self.assertEqual(payload['keep_alive'],'10m')
        self.assertIn('box',payload['format']['properties']['observations']['items']['required'])
        self.assertEqual(result[0]['time'],1.1)
        self.assertEqual(provider.timings[0]['total_duration'],1000000000)
    def test_reference_box_must_match_clicked_blade_before_publishing_rate(self):
        m=self.module()
        class WrongBlade(ModelDouble):
            def predict(self, reference, frames):
                return [dict(o, box=[.7,.7,.8,.8]) for o in super().predict(reference,frames)]
        model=WrongBlade()
        result=m.analyse_video(self.video,out_dir=self.root/'wrong',selection=selected(),provider=model,log=lambda _:None)
        data=json.loads((result['report'].parent/'metrics.json').read_text())
        self.assertIsNone(data['blade_rate']['spm'])
        self.assertEqual(data['processing']['stop_reason'],'reference_unconfirmed')
        self.assertEqual(model.calls,1)
    def test_multiple_cycle_option_is_explicit_and_bad_target_rejected(self):
        m=self.module();model=ModelDouble()
        result=m.analyse_video(self.video,out_dir=self.root/'long',selection=selected(),provider=model,target_cycles=5,log=lambda _:None)
        data=json.loads((result['report'].parent/'metrics.json').read_text())
        self.assertGreaterEqual(data['blade_rate']['cycles'],5)
        self.assertGreater(model.calls,2)
        for bad in (True,0,6,'1'):
            with self.subTest(bad=bad),self.assertRaises(blade_model.BladeModelError):
                m.analyse_video(self.video,out_dir=self.root,selection=selected(),provider=model,target_cycles=bad)


if __name__=='__main__':unittest.main()
