"""Speed contracts; generated images/model doubles are not accuracy evidence."""
import base64
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_crew_model import predicted, selection


def image():
    return base64.b64encode(cv2.imencode('.jpg',np.full((720,1280,3),70,np.uint8))[1]).decode()


def compact(expected=(0,),tasks=('position',)):
    frames=predicted(expected,list(tasks))['observations'];result=[]
    for f in frames:
        rows=[]
        for o in f['rowers']:
            r={'i':o['rower_id'],'v':o['same_rower'],'b':[round(v*1000) for v in o['box']]}
            if 'position' in tasks:r['p']=[2,1,1]
            if 'rate' in tasks or 'timing' in tasks:r.update(c=1,d=[round(v*1000) for v in o['blade_box']])
            rows.append(r)
        result.append({'f':f['frame_id'],'r':rows})
    return {'o':result}


class VisionSpeedTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.vision_speed'),'speed pipeline missing')
        from strokesense import vision_speed
        return vision_speed
    def test_compact_decodes_all_eight_to_existing_strict_contract(self):
        m=self.module();r=m.decode_compact(compact(),[0],['position'])
        self.assertEqual(len(r[0]['rowers']),8)
        self.assertEqual(r[0]['rowers'][0]['position'],{'torso':'upright','arms':'extended','knees':'compressed'})
        self.assertNotIn('contact',r[0]['rowers'][0])
    def test_wrong_ids_extra_fields_boolean_coordinates_and_duplicate_people_fail(self):
        m=self.module()
        for change in ('id','bool','extra','duplicate','missing'):
            data=compact();r=data['o'][0]['r']
            if change=='id':r[1]['i']=1
            elif change=='bool':r[0]['b'][0]=True
            elif change=='extra':r[0]['advice']='invented'
            elif change=='duplicate':r[1]['b']=r[0]['b'][:]
            else:r.pop()
            with self.subTest(change=change),self.assertRaises(ValueError):m.decode_compact(data,[0],['position'])
    def test_position_crop_preserves_pixel_scale_and_blade_tasks_keep_full_scene(self):
        m=self.module();im=image();frames=[{'frame_id':0,'time':0.,'image':im}];seeds=selection()['seeds']
        p=m.prepare_inputs(im,frames,seeds,['position']);decoded=cv2.imdecode(np.frombuffer(base64.b64decode(p['reference']),np.uint8),1)
        self.assertLess(decoded.shape[0],720);self.assertEqual(decoded.shape[1],1280)
        self.assertLess(p['input_pixels'],1280*720*2)
        for tasks in (['rate'],['position','timing']):
            p=m.prepare_inputs(im,frames,seeds,tasks);self.assertEqual(p['roi'],[0.,0.,1.,1.]);self.assertEqual(p['frames'][0]['image'],im)
    def test_crop_coordinates_return_to_source_frame(self):
        m=self.module();data=compact();roi=[.1,.2,.9,.8]
        r=m.decode_compact(data,[0],['position'],roi)[0]['rowers'][0]
        self.assertAlmostEqual(r['box'][1],.44);self.assertAlmostEqual(r['box'][3],.56)
    def test_unknown_or_boundary_crop_requires_full_frame_retry(self):
        m=self.module();rows=predicted(tasks=['position'])['observations'];seeds=selection()['seeds']
        self.assertTrue(m.crop_supported(rows,seeds,[0,0,1,1]))
        rows[0]['rowers'][7]['same_rower']=False
        self.assertFalse(m.crop_supported(rows,seeds,[0,0,1,1]))
        rows=predicted(tasks=['position'])['observations'];rows[0]['rowers'][0]['box'][1]=.001
        self.assertFalse(m.crop_supported(rows,seeds,[0,0,1,1]))
    def test_exact_cache_revalidates_and_invalidates_model_prompt_and_image(self):
        m=self.module()
        class Provider:
            digest='a'*64
            def __init__(self,root):self.cache_dir=root;self.calls=0
            def _request(self,route,payload):self.calls+=1;return {'value':7}
        def parse(data):
            if data!={'value':7}:raise ValueError('invalid')
            return data['value']
        with tempfile.TemporaryDirectory() as tmp:
            p=Provider(Path(tmp));payload={'model':'test','image':'one','prompt':'a'}
            self.assertEqual(m.cached_call(p,payload,parse),7);self.assertEqual(m.cached_call(p,payload,parse),7);self.assertEqual(p.calls,1)
            for key,value in [('image','two'),('prompt','b')]:m.cached_call(p,dict(payload,**{key:value}),parse)
            p.digest='b'*64;m.cached_call(p,payload,parse);self.assertEqual(p.calls,4)
            for f in Path(tmp).glob('*.json'):f.write_text('{"value":999}')
            m.cached_call(p,payload,parse);self.assertEqual(p.calls,5)
    def test_invalid_results_are_never_cached_and_bypass_always_calls(self):
        m=self.module()
        from unittest.mock import patch
        class Provider:
            digest='a'*64
            def __init__(self,root):self.cache_dir=root;self.calls=0
            def _request(self,*args):self.calls+=1;return {'bad':1}
        with tempfile.TemporaryDirectory() as tmp:
            p=Provider(Path(tmp))
            def reject(data):raise ValueError('bad response')
            with self.assertRaises(ValueError):m.cached_call(p,{},reject)
            self.assertEqual(list(Path(tmp).glob('*.json')),[])
            with patch.dict('os.environ',{'STROKESENSE_VISION_CACHE':'0'}):
                m.cached_call(p,{},lambda x:x);m.cached_call(p,{},lambda x:x)
            self.assertEqual(p.calls,3)

if __name__=='__main__':unittest.main()
