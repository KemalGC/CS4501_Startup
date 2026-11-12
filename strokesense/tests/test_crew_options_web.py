"""Real loopback contracts; fake analyzer is not model-accuracy evidence."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_blade_web import BladeWebTests as _Base
from test_crew_model import selection
import unittest


class CrewOptionsWebTests(unittest.TestCase):
    def setUp(self):
        self.base=_Base();self.base.setUp();self.addCleanup(self.base.doCleanups)
    def form(self):
        b=self.base
        return {'clip':b.cid,'csrf':b.server.csrf_token,'seconds':'0',
                'seeds':json.dumps(selection()['seeds']),'analysis':'position','confirm':'yes'}
    def test_library_exposes_crew_options_and_accessible_independent_choices(self):
        b=self.base
        self.assertIn(b'Choose crew analyses',b.request('GET','/library')[2])
        status,_,body=b.request('GET','/crew?clip='+b.cid)
        self.assertEqual(status,200)
        for word in (b'name="analysis"',b'value="position"',b'value="rate"',b'value="timing"',b'crew-canvas'):
            self.assertIn(word,body)
        self.assertEqual(b.jobs.list_recent(),[])
    def test_only_selected_task_is_saved_and_passed_to_worker(self):
        b=self.base
        with patch.dict(os.environ,{'STROKESENSE_CREW_MODEL':'test-local:1'}):
            status,headers,_=b.request('POST','/crew',self.form())
        self.assertEqual(status,303)
        jid=headers['Location'].rsplit('/',1)[-1];b.jobs.wait(jid,timeout=5)
        self.assertEqual(b.seen[0]['analyses'],['position'])
        self.assertEqual(b.jobs.selection(jid)['version'],4)
    def test_invalid_missing_options_confirmation_and_foreign_origin_do_not_enqueue(self):
        b=self.base
        with patch.dict(os.environ,{'STROKESENSE_CREW_MODEL':'test-local:1'}):
            for field,value in [('analysis','hidden'),('analysis',''),('confirm','no'),('seeds','[]'),('csrf','bad')]:
                self.assertGreaterEqual(b.request('POST','/crew',dict(self.form(),**{field:value}))[0],400)
            self.assertEqual(b.request('POST','/crew',self.form(),origin='http://foreign.example')[0],403)
        self.assertEqual(b.jobs.list_recent(),[])
    def test_missing_model_refuses_without_heuristic_fallback(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.base.request('POST','/crew',self.form())[0],503)
        self.assertEqual(self.base.jobs.list_recent(),[])


if __name__=='__main__':unittest.main()
