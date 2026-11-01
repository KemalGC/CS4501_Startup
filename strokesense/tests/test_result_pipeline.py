"""Integration-era regressions; synthetic analysis inputs, real report serialization."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense import cli, render, report, cadence, kinematics, strokes
from strokesense.crew import Rower
from strokesense.pose import PoseResult
from strokesense.analysis_worker import run_isolated, _command, AnalysisProcessError
from synthetic import make_rower
from test_selected_crew import frame, selection


class ResultPipelineTests(unittest.TestCase):
    def test_optional_video_unavailable_still_builds_report_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); video=root/'synthetic.mp4';video.write_bytes(b'synthetic input')
            model=root/'model.onnx';model.write_bytes(b'fake model')
            dets=[frame() for _ in range(3)]
            meta={'width':100,'height':100,'fps':15,'start':0,'stride':1}
            with patch.object(cli,'PoseDetector'), \
                 patch.object(cli,'run_selected_video',return_value=(dets,meta)), \
                 patch.object(render,'_ffmpeg',return_value=None), \
                 patch.object(render,'snapshots',return_value=set()):
                result=cli.analyse_video(video,out_dir=root/'results',model=model,
                                         selection=selection(),log=lambda _:None)
            self.assertIsNone(result['video'])
            self.assertTrue(result['report'].is_file())
            self.assertIn('Annotated video unavailable',result['report'].read_text())
            metrics=json.loads((result['report'].parent/'metrics.json').read_text())
            self.assertEqual(metrics['sync']['media']['state'],'unavailable')
            self.assertEqual(len(metrics['rowers']),8)
            self.assertIn('evidence',metrics)

    def test_report_labels_raw_outlier_without_modifying_strokes(self):
        kp,fps=make_rower(rate=34,n_strokes=5)
        k=kinematics.build(kp,fps); found,handle=strokes.analyse(k)
        self.assertGreaterEqual(len(found),2)
        rowers=[]
        for i in range(4):
            r=Rower(i,seat=f'Selected {i+1}',k=k,strokes=copy.deepcopy(found),handle=handle)
            if i==3:
                r.strokes=r.strokes[:1];r.strokes[0].rate=45
            r.summary=strokes.summarise(r.strokes);rowers.append(r)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'report.html'
            with patch.object(report,'chart_sequencing',return_value=''),patch.object(report,'chart_trunk',return_value=''):
                report.build_html('Synthetic',PoseResult(fps,len(kp),640,480,{}),rowers,{}, {},out)
            body=out.read_text()
        self.assertIn('Estimated crew cadence',body)
        self.assertIn('45.0 spm',body)
        self.assertIn('Unconfirmed: fewer than 2 cycles',body)
        self.assertEqual(rowers[3].strokes[0].rate,45)
        self.assertEqual(cadence.estimate(rowers)['supporting_rowers'],3)

    def test_real_child_receipt_keeps_only_artifact_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'report.html';out.write_text('synthetic')
            payload=json.dumps({'state':'succeeded','report':str(out),'video':None})
            def command(receipt):
                script='import pathlib; pathlib.Path('+repr(str(receipt))+').write_text('+repr(payload)+')'
                return [sys.executable,'-c',script]
            with patch('strokesense.analysis_worker._command',side_effect=command):
                result=run_isolated(root/'video.mp4',out_dir=root,timeout=5)
            self.assertEqual(result,{'report':out,'video':None})
            self.assertEqual(list(root.glob('.worker-*')),[])
            self.assertEqual(_command('receipt')[0],sys.executable)
            self.assertIn('faulthandler',_command('receipt'))

    def test_real_child_timeout_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('strokesense.analysis_worker._command',return_value=[sys.executable,'-c','import time;time.sleep(5)']):
            with self.assertRaises(AnalysisProcessError) as failure:
                run_isolated(Path(tmp)/'video.mp4',out_dir=Path(tmp),timeout=.1)
            self.assertEqual(failure.exception.code,'analysis_timeout')

    def test_ffmpeg_success_without_output_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source.mp4';source.write_bytes(b'intermediate')
            with patch.object(render,'_ffmpeg',return_value='ffmpeg'), \
                 patch.object(render.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaises(render.RenderingUnavailable):render._finalise(source,root/'result.mp4')
            self.assertTrue(source.exists())

if __name__=='__main__':unittest.main()
