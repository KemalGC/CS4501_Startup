"""One-boat selection routing: private synthetic HTTP fixtures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_web as fixture
from test_selected_crew import selection

class SelectionWebTests(unittest.TestCase):
    setUp=fixture.LocalWebTests.setUp
    _stop=fixture.LocalWebTests._stop
    request=fixture.LocalWebTests.request

    def test_selection_preview_has_eight_numbered_targets_and_one_boat_confirmation(self):
        cap=MagicMock();cap.isOpened.return_value=True
        cap.read.return_value=(True,np.zeros((100,160,3),np.uint8))
        with patch('cv2.VideoCapture',return_value=cap):
            code,headers,body=self.request('GET','/select?clip='+self.clip_id)
        self.assertEqual(code,200)
        self.assertIn(b'Choose eight rowers from one boat',body)
        self.assertIn(b'name="same_boat"',body)
        for i in range(8):self.assertIn(f'name="x{i}"'.encode(),body)
        self.assertIn(b'/selection.js',body)
        self.assertNotIn(str(self.video).encode(),body)
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])

    def data(self):
        s=selection();d={'csrf':self.server.csrf_token,'clip_id':self.clip_id,'same_boat':'yes'}
        d.update(dict(zip(('left','top','right','bottom'),[v*100 for v in s['roi']])))
        for i,(x,y) in enumerate(s['seeds']):d.update({f'x{i}':x*100,f'y{i}':y*100})
        return d

    def test_confirmed_selection_is_persisted_before_job_starts(self):
        code,headers,_=self.request('POST','/select',payload=self.data())
        self.assertEqual(code,303)
        job=headers['Location'].split('/')[-1]
        np.testing.assert_allclose(self.worker.selection(job)['seeds'],selection()['seeds'])

    def test_missing_same_boat_confirmation_or_eighth_person_never_submits(self):
        for key in ('same_boat','x7'):
            d=self.data();d.pop(key)
            code,_,_=self.request('POST','/select',payload=d)
            self.assertEqual(code,422)
        self.assertEqual(self.worker.list_recent(),[])

    def test_forged_selection_and_foreign_origin_are_rejected(self):
        d=self.data();d['csrf']='forged'
        self.assertEqual(self.request('POST','/select',payload=d)[0],403)
        self.assertEqual(self.request('GET','/select?clip='+self.clip_id,headers={'Origin':'https://example.invalid'})[0],403)
        self.assertEqual(self.worker.list_recent(),[])

if __name__=='__main__':unittest.main()
