"""Regressions prompted by the live timeout; these responses are doubles."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_vision_speed import compact,image
from test_crew_model import selection
from strokesense.vision_speed import fast_crew
from strokesense.blade_model import BladeModelError

class LiveSpeedRegressionTests(unittest.TestCase):
    def test_reference_identical_first_sample_is_encoded_once(self):
        im=image()
        class Provider:
            digest='a'*64;model='test';reference_source_image=im
            def _request(self,route,payload):
                self.payload=payload
                return {'done':True,'done_reason':'stop','message':{'content':__import__('json').dumps(compact(tasks=('rate',)))}}
        p=Provider();fast_crew(p,im,[{'frame_id':0,'time':0.,'image':im}],selection()['seeds'],['rate'])
        self.assertEqual(len(p.payload['messages'][0]['images']),1)
        self.assertIn('also sample frame 0',p.payload['messages'][0]['content'])
    def test_transport_timeout_does_not_retry_larger_full_scene(self):
        class Provider:
            digest='a'*64;model='test';calls=0
            def _request(self,*args):self.calls+=1;raise BladeModelError('local_model_unavailable')
        p=Provider();im=image()
        with self.assertRaises(BladeModelError):fast_crew(p,im,[{'frame_id':0,'time':0.,'image':im}],selection()['seeds'],['position'])
        self.assertEqual(p.calls,1)

if __name__=='__main__':unittest.main()
