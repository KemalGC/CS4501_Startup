"""Integration-era regressions; synthetic analysis inputs, real report serialization."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
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
        for i in range(8):
            r=Rower(i,seat=f'Selected {i+1}',k=k,strokes=copy.deepcopy(found),handle=handle)
            if i==7:
                r.strokes=r.strokes[:1];r.strokes[0].rate=45
            r.summary=strokes.summarise(r.strokes);rowers.append(r)
        before=[copy.deepcopy(r.summary) for r in rowers]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'report.html'
            with patch.object(report,'chart_sequencing',return_value=''),patch.object(report,'chart_trunk',return_value=''):
                report.build_html('Synthetic',PoseResult(fps,len(kp),640,480,{}),rowers,{}, {},out)
            body=out.read_text()
            report.build_json(rowers,{},Path(tmp)/'metrics.json')
            metrics=json.loads((Path(tmp)/'metrics.json').read_text())
        shared=cadence.estimate(rowers)
        primary=re.findall(r'<span>Shared boat stroke rate</span><b>([^<]+)</b>',body)
        self.assertEqual(primary,[f"{shared['rate_spm']:.1f} spm"]*9)
        self.assertIn('45.0 spm',body)
        diagnostics=body.split('<details class="rate-diagnostics">',1)[1].split('</details>',1)[0]
        self.assertIn('45.0 spm',diagnostics)
        self.assertNotIn('45.0 spm',body.replace(diagnostics,''))
        self.assertEqual(rowers[7].strokes[0].rate,45)
        self.assertEqual([r.summary for r in rowers],before)
        self.assertEqual(metrics['rowers'][7]['summary']['rate'],45)
        self.assertEqual(shared['supporting_rowers'],7)

    def test_report_withholds_same_primary_rate_for_every_rower_without_boat_support(self):
        kp,fps=make_rower(rate=34,n_strokes=5)
        k=kinematics.build(kp,fps);found,handle=strokes.analyse(k)
        rowers=[]
        for i in range(8):
            r=Rower(i,seat=f'Selected {i+1}',k=k,strokes=copy.deepcopy(found[:1]),handle=handle)
            r.summary=strokes.summarise(r.strokes);rowers.append(r)
        self.assertIsNone(cadence.estimate(rowers)['rate_spm'])
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'report.html'
            with patch.object(report,'chart_sequencing',return_value=''),patch.object(report,'chart_trunk',return_value=''):
                report.build_html('Synthetic',PoseResult(fps,len(kp),640,480,{}),rowers,{}, {},out)
            primary=re.findall(r'<span>Shared boat stroke rate</span><b>([^<]+)</b>',out.read_text())
        self.assertEqual(primary,['Unavailable']*9)

    def test_overlay_uses_current_shared_rate_or_unavailable_and_retains_timing(self):
        rowers=[SimpleNamespace(tid=i,seat=f'Selected {i+1}',strokes=[
            SimpleNamespace(catch=0,finish=2,next_catch=4,rate=45+i,faults=[])]) for i in range(8)]
        pose=PoseResult(15,1,640,480,{})
        for estimate,label in ((34.2,'shared boat ~34.2 spm'),(None,'boat rate unavailable')):
            with self.subTest(estimate=estimate),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'overlay.mp4';writer=Mock()
                with patch.object(render,'_ffmpeg',return_value='ffmpeg'), \
                     patch.object(render,'_open_writer',return_value=(writer,out)), \
                     patch.object(render,'_finalise',return_value=out), \
                     patch.object(render,'iter_frames',return_value=iter([(0,np.zeros((480,640,3),dtype=np.uint8))])), \
                     patch.object(render,'draw_rower'),patch.object(render,'_txt') as labels, \
                     patch.object(render.cadence,'estimate',return_value={'rate_spm':estimate}):
                    render.render_video('synthetic.mp4',pose,rowers,out,
                        sync={'cadence':{'rate_spm':99.},'per_seat':{'Selected 1':{'mean_ms':15.}}})
                captions=[call.args[1] for call in labels.call_args_list]
                self.assertEqual(captions[0],'StrokeSense   '+label)
                self.assertIn('catch  15 ms late',captions[1])
                self.assertNotIn('99.0 spm',' '.join(captions))
                self.assertNotIn('45.0 spm',' '.join(captions))
                writer.write.assert_called_once();writer.release.assert_called_once()

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
