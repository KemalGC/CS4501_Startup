"""Real decoding and report pipeline with declared model doubles."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import crew_model as m
from test_crew_model import selection,predicted


class CrewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.video=self.root/'synthetic.avi';w=cv2.VideoWriter(str(self.video),cv2.VideoWriter_fourcc(*'MJPG'),10,(320,160))
        self.assertTrue(w.isOpened())
        for i in range(70):w.write(np.full((160,320,3),80+i%30,np.uint8))
        w.release()
    def provider(self,missing=False):
        class Double:
            calls=0
            def check(self):return {'name':'TEST DOUBLE','digest':'a'*64}
            def predict_crew(self,reference,frames,seeds,tasks):
                self.calls+=1;data=predicted([f['frame_id'] for f in frames],tasks)['observations']
                if missing:
                    for f in data:f['rowers'][7]=m._unknown(f['rowers'][7])
                return data
        return Double()
    def run_pipeline(self,tasks,provider):
        out=m.analyse_video(self.video,out_dir=self.root/'out',selection=selection(tasks),provider=provider,log=lambda _:None)
        data=json.loads((out['report'].parent/'metrics.json').read_text())
        return data,out['report'].read_text()
    def test_position_only_one_request_eight_rows_and_no_rate_work(self):
        provider=self.provider();data,body=self.run_pipeline(['position'],provider)
        self.assertEqual(provider.calls,1);self.assertEqual(len(data['observations']),3)
        self.assertEqual(len(data['crew_review']['rowers']),8)
        self.assertTrue(all('rate' not in r for r in data['crew_review']['rowers']))
        for i in range(1,9):self.assertIn('Selected rower '+str(i),body)
        self.assertNotIn('SPM',body)
    def test_all_eight_rates_stop_only_after_each_has_two_entries(self):
        provider=self.provider();data,body=self.run_pipeline(['rate'],provider)
        self.assertEqual(len(data['crew_review']['rowers']),8)
        self.assertEqual(data['processing']['stop_reason'],'all_eight_two_entries')
        for r in data['crew_review']['rowers']:self.assertAlmostEqual(r['rate']['spm'],30)
        self.assertLess(data['processing']['sampled_frames'],70)
        self.assertNotIn('Torso',body)
    def test_seventh_success_cannot_hide_missing_eighth(self):
        data,body=self.run_pipeline(['rate'],self.provider(missing=True))
        self.assertNotEqual(data['processing']['stop_reason'],'all_eight_two_entries')
        self.assertIsNone(data['crew_review']['rowers'][7]['rate']['spm'])
        self.assertIn('Selected rower 8',body);self.assertIn('Unavailable',body)
    def test_missing_live_model_is_not_a_fake_success(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(m.BladeModelError,'model_not_configured'):
                m.analyse_video(self.video,out_dir=self.root/'out',selection=selection())
    def test_disjoint_catch_groups_do_not_claim_eight_rower_timing(self):
        data=predicted(range(44),['timing'])['observations']
        for f in data:
            f['time']=f['frame_id']/10
            for i in range(1,8):f['rowers'][i]['contact']='unknown';f['rowers'][i]['blade_box']=None
        self.assertEqual(m.summarize_crew(data,['timing'])['timing'],[])


if __name__=='__main__':unittest.main()
