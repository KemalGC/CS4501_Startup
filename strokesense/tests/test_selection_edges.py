"""Additional recovery/permission/crossing regressions, synthetic data only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import test_selection_web as webfixture
import test_upload as uploadfixture
from test_selected_crew import selection, frame
from strokesense.selection import locked_tracks, SelectionError
from strokesense.registry import revoke_clip


class SelectedUploadTests(unittest.TestCase):
    setUp=uploadfixture.UploadHTTPTests.setUp
    stop=uploadfixture.UploadHTTPTests.stop
    request=uploadfixture.UploadHTTPTests.request
    upload=uploadfixture.UploadHTTPTests.upload
    def test_import_pauses_before_inference_for_selection(self):
        code, headers, _=self.upload(extras=(('analyze','now'),('select_crew','yes')))
        self.assertEqual(code,303)
        self.assertTrue(headers['Location'].startswith('/select?clip='))
        self.assertEqual(self.worker.list_recent(),[])
    def test_import_only_stays_import_only_with_selection_checkbox(self):
        code, headers, _=self.upload(extras=(('select_crew','yes'),))
        self.assertEqual((code, headers['Location']),(303,'/'))
        self.assertEqual(self.worker.list_recent(),[])


class SelectionPermissionTests(unittest.TestCase):
    setUp=webfixture.SelectionWebTests.setUp
    _stop=webfixture.SelectionWebTests._stop
    request=webfixture.SelectionWebTests.request
    data=webfixture.SelectionWebTests.data
    def test_revoked_clip_cannot_be_previewed_or_selected(self):
        revoke_clip(self.clip_id,self.registry_db)
        self.assertEqual(self.request('GET','/select?clip='+self.clip_id)[0],403)
        self.assertEqual(self.request('POST','/select',payload=self.data())[0],422)
        self.assertEqual(self.worker.list_recent(),[])
    def test_retry_keeps_original_selection(self):
        seen=[]
        def analyzer(*a, **kw):
            seen.append(kw['selection']);raise RuntimeError('synthetic failure')
        with patch.object(self.worker,'_analyze_fn',side_effect=analyzer):
            code,h,_=self.request('POST','/select',payload=self.data());self.assertEqual(code,303)
            original=h['Location'].rsplit('/',1)[-1];self.worker.wait(original,timeout=3)
            code,h,_=self.request('POST','/jobs',payload={
                'csrf':self.server.csrf_token,'clip_id':self.clip_id,'retry_job':original})
            self.assertEqual(code,303);again=h['Location'].rsplit('/',1)[-1]
            self.worker.wait(again,timeout=3)
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[0],seen[1]);self.assertNotEqual(original,again)
    def test_mutated_private_source_has_no_preview(self):
        self.video.write_bytes(b'changed')
        self.assertEqual(self.request('GET','/select?clip='+self.clip_id)[0],409)


class CrossingTests(unittest.TestCase):
    def test_in_region_competing_detection_is_ambiguous_not_reassigned(self):
        a,k=frame();b=a[:1].copy();b[:,[0,2]]+=.1
        with self.assertRaises(SelectionError):
            locked_tracks([(a,k),(np.vstack([a,b]),np.vstack([k,k[:1]]))],
                          {'width':100,'height':100},selection())

if __name__=='__main__':unittest.main()
