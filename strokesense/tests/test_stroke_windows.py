"""Observed stroke windows and short-assessment display, using synthetic poses."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from synthetic import make_rower
from test_short_strokes import selected_pose
from strokesense import dynamic_crew,report,strokes

class StrokeWindowTests(unittest.TestCase):
    def rower(self):
        kp,fps=make_rower(n_strokes=9,rate=30,noise=0)
        pose=selected_pose(kp,fps)
        r=dynamic_crew.rowers_from_selected(pose)[0]
        return pose,r
    def test_saved_windows_use_source_time_and_observation_counts(self):
        pose,r=self.rower()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'metrics.json';report.build_json([r],{},p,fps=pose.fps,start_seconds=12)
            data=json.loads(p.read_text())
        self.assertIn('stroke_windows',data,'inspectable stroke window manifest is missing')
        windows=data['stroke_windows']['rowers'][0]['windows']
        self.assertEqual(len(windows),len(r.strokes))
        self.assertAlmostEqual(windows[0]['source_start_seconds'],12+r.strokes[0].catch/pose.fps)
        self.assertEqual(windows[0]['missing_frames'],0)
    def test_five_is_ready_single_cycle_is_preliminary_without_fake_consistency(self):
        pose,r=self.rower()
        with tempfile.TemporaryDirectory() as tmp, patch.object(report,'chart_trunk',return_value=''),patch.object(report,'chart_sequencing',return_value=''):
            p=Path(tmp)/'report.html'
            r.strokes=r.strokes[:5];r.summary=strokes.summarise(r.strokes)
            report.build_html('synthetic',pose,[r],{}, {},p)
            self.assertIn('Short assessment ready',p.read_text())
            self.assertIn('Stroke-by-stroke windows',p.read_text())
            r.strokes=r.strokes[:1];r.summary=strokes.summarise(r.strokes)
            report.build_html('synthetic',pose,[r],{}, {},p)
            text=p.read_text()
            self.assertIn('Preliminary: 1 of 5 usable strokes',text)
            self.assertNotIn('100/100',text)
            self.assertNotIn('None/100',text)

if __name__=='__main__':unittest.main()
