"""Representative fault context and visible legend, synthetic kinematics only."""
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
import test_analysis as fixture
from strokesense import report, render

class FaultPictureTests(unittest.TestCase):
    def rower(self):
        k,st,summ=fixture.run(faults=('early_arms',),layback=-40)
        return types.SimpleNamespace(tid=2,seat='Selected 3',k=k,strokes=st,summary=summ,sync_ms=None)
    def test_trunk_legend_has_distinct_colors_and_shapes_not_black_text_dots(self):
        rower=self.rower();figs=[]
        with patch.object(report,'_png',side_effect=lambda fig:figs.append(fig) or 'fixture'):
            report.chart_trunk(rower)
        try:
            ax=figs[0].axes[0];handles,labels=ax.get_legend_handles_labels()
            self.assertIn('Catch',labels);self.assertIn('Finish',labels)
            a=handles[labels.index('Catch')];b=handles[labels.index('Finish')]
            self.assertNotEqual(a.get_color(),b.get_color());self.assertNotEqual(a.get_marker(),b.get_marker())
            self.assertNotIn('●',ax.get_title(loc='left'))
        finally:report.plt.close(figs[0])
    def test_fault_requests_use_actual_flagged_stroke_and_source_time(self):
        self.assertTrue(callable(getattr(render,'fault_snapshot_requests',None)))
        rower=self.rower();pose=types.SimpleNamespace(start=9.0,fps=rower.k.fps)
        with tempfile.TemporaryDirectory() as t:
            shots,requests=render.fault_snapshot_requests(rower,pose,Path(t))
            self.assertTrue(shots)
            for code,shot in shots.items():
                st=next(s for s in rower.strokes if s.idx==shot['stroke'])
                self.assertIn(code,st.faults)
                self.assertGreaterEqual(shot['frame'],st.catch)
                self.assertLessEqual(shot['frame'],st.next_catch)
                self.assertAlmostEqual(shot['seconds'],9+shot['frame']/pose.fps)
                self.assertIn((shot['frame'],rower,shot['path']),requests)
            self.assertEqual(shots['excess_layback']['frame'],next(s for s in rower.strokes if s.idx==shots['excess_layback']['stroke']).finish)
    def test_invisible_frames_not_presented_as_fault_photos(self):
        self.assertTrue(callable(getattr(render,'fault_snapshot_requests',None)))
        rower=self.rower();rower.k.visible[:]=False
        shots,requests=render.fault_snapshot_requests(rower,types.SimpleNamespace(start=0,fps=rower.k.fps),Path('.'))
        self.assertEqual(shots,{});self.assertEqual(requests,[])
    def test_html_embeds_each_fault_context_with_rower_and_timestamp(self):
        self.assertTrue(callable(getattr(render,'fault_snapshot_requests',None)))
        rower=self.rower();pose=types.SimpleNamespace(start=9.0,fps=rower.k.fps,n_frames=rower.k.n)
        with tempfile.TemporaryDirectory() as t:
            shots,requests=render.fault_snapshot_requests(rower,pose,Path(t))
            import cv2
            for fi,r,p in requests:cv2.imwrite(str(p),np.full((64,64,3),180,np.uint8))
            with patch.object(report,'chart_sequencing',return_value=''),patch.object(report,'chart_trunk',return_value=''):
                out=Path(t)/'report.html';report.build_html('synthetic',pose,[rower],{}, {rower.tid:{'faults':shots}},out)
            text=out.read_text();self.assertIn('fault-photo',text);self.assertIn('Selected 3',text)
            self.assertIn('context frame',text.lower());self.assertIn('data:image/jpeg;base64,',text)
            for shot in shots.values():self.assertIn(f"{shot['seconds']:.2f} s",text)

if __name__=='__main__':unittest.main()
