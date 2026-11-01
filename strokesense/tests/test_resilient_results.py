"""Result reliability: synthetic jobs/cadence; no model or external service."""
import http.client
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense import render
from strokesense.jobs import JobQueue
from strokesense.registry import register_clip
from strokesense.web import create_server


def rower(tid, rates):
    return SimpleNamespace(tid=tid, seat=f'Selected {tid+1}',
        strokes=[SimpleNamespace(rate=v) for v in rates],
        summary={'rate': rates[0] if rates else None, 'n_strokes': len(rates)})


class CadenceTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.cadence'),
                             'evidence-qualified crew cadence is missing')
        from strokesense import cadence
        return cadence

    def test_one_noisy_cycle_is_not_a_separate_confident_boat_rate(self):
        c = self.module()
        people = [rower(0,[35,35,35]), rower(1,[33,33,33]), rower(2,[34,34]),
                  rower(3,[45]), rower(4,[]), rower(5,[35,35]),
                  rower(6,[]), rower(7,[34,34,34,34])]
        before = [dict(r.summary) for r in people]
        result = c.estimate(people)
        self.assertEqual(result['rate_spm'],34)
        self.assertEqual(result['supporting_rowers'],5)
        self.assertEqual(result['supporting_cycles'],14)
        self.assertEqual(result['per_rower']['Selected 4']['state'],'insufficient_cycles')
        self.assertEqual(result['per_rower']['Selected 5']['state'],'no_cycles')
        self.assertEqual([r.summary for r in people], before, 'Never rewrite measured summaries')

    def test_repeated_outlier_is_flagged_not_forced_equal(self):
        people=[rower(i,[34,34,34]) for i in range(4)]+[rower(4,[45,45,45])]
        result=self.module().estimate(people)
        self.assertEqual(result['rate_spm'],34)
        self.assertEqual(result['per_rower']['Selected 5']['state'],'inconsistent_with_crew')
        self.assertEqual(result['per_rower']['Selected 5']['raw_spm'],45)

    def test_single_samples_and_split_clusters_do_not_invent_consensus(self):
        for people in ([rower(i,[34]) for i in range(8)],
                       [rower(i,[r,r,r]) for i,r in enumerate([22,22,40,40])]):
            result=self.module().estimate(people)
            self.assertIsNone(result['rate_spm'])
            self.assertEqual(result['state'],'insufficient_agreement')

    def test_nonfinite_estimates_are_excluded_and_json_is_finite(self):
        result=self.module().estimate([rower(0,[float('nan')]),rower(1,[float('inf')])])
        self.assertIsNone(result['rate_spm'])
        json.dumps(result,allow_nan=False)


class EncoderSafetyTests(unittest.TestCase):
    def test_unopened_mp4_writer_never_falls_back_to_unchecked_vp8(self):
        self.assertTrue(hasattr(render,'RenderingUnavailable'),'typed optional-render failure is missing')
        writer=Mock();writer.isOpened.return_value=False
        with tempfile.TemporaryDirectory() as tmp, patch.object(render.cv2,'VideoWriter',return_value=writer) as opening:
            with self.assertRaises(render.RenderingUnavailable):
                render._open_writer(Path(tmp)/'result.mp4',15,(160,120))
        self.assertEqual(opening.call_count,1)
        writer.release.assert_called_once()

    def test_no_browser_encoder_preserves_intermediate_and_old_output(self):
        self.assertTrue(hasattr(render,'RenderingUnavailable'),'typed optional-render failure is missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'intermediate.mp4';source.write_bytes(b'intermediate')
            target=root/'result.mp4';target.write_bytes(b'prior output')
            with patch.object(render,'_ffmpeg',return_value=None), patch.object(render.cv2,'VideoWriter') as opening:
                with self.assertRaises(render.RenderingUnavailable):render._finalise(source,target)
            opening.assert_not_called()
            self.assertEqual(source.read_bytes(),b'intermediate')
            self.assertEqual(target.read_bytes(),b'prior output')

    def test_failed_ffmpeg_does_not_claim_browser_video_or_delete_source(self):
        self.assertTrue(hasattr(render,'RenderingUnavailable'),'typed optional-render failure is missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'intermediate.mp4';source.write_bytes(b'original')
            with patch.object(render,'_ffmpeg',return_value='ffmpeg'), \
                 patch.object(render.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(render.RenderingUnavailable):render._finalise(source,root/'result.mp4')
            self.assertTrue(source.exists())


class IsolatedWorkerTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.analysis_worker'),
                             'isolated production worker is missing')
        from strokesense import analysis_worker
        return analysis_worker

    def test_production_queue_uses_isolated_entrypoint(self):
        worker=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with JobQueue(registry_db=root/'clips.db',job_db=root/'jobs.db',results_root=root/'results') as jobs:
                self.assertIs(jobs._analyze_fn,worker.run_isolated)

    def test_real_child_abrupt_exit_leaves_status_server_alive(self):
        worker=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'fixture.mp4';source.write_bytes(b'synthetic')
            db=root/'clips.db';clip,_=register_clip(source,db,permission='granted',provenance='Synthetic test')
            with JobQueue(registry_db=db,job_db=root/'jobs.db',results_root=root/'results') as jobs:
                with create_server(jobs,registry_db=db,port=0) as server:
                    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                    try:
                        with patch.object(worker,'_command',return_value=[sys.executable,'-c','import os; os._exit(17)']):
                            item=jobs.submit(clip['clip_id']);done=jobs.wait(item['job_id'],timeout=10)
                        self.assertEqual(done['status'],'failed')
                        self.assertEqual(done['error_code'],'analysis_process_failed')
                        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                        conn.request('GET','/jobs/'+item['job_id']);res=conn.getresponse();body=res.read();conn.close()
                        self.assertEqual(res.status,200)
                        self.assertIn(b'analysis_process_failed',body)
                        self.assertNotIn(str(root).encode(),body)
                    finally:server.shutdown();thread.join(3)

    def test_child_timeout_and_missing_receipt_fail_safely(self):
        worker=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for outcome in (subprocess.TimeoutExpired('child',1),SimpleNamespace(returncode=0)):
                with self.subTest(outcome=type(outcome).__name__), \
                     patch.object(worker.subprocess,'run',side_effect=outcome if isinstance(outcome,Exception) else None,
                                  return_value=outcome):
                    with self.assertRaises(worker.AnalysisProcessError):
                        worker.run_isolated(root/'source.mp4',out_dir=root,timeout=1)


if __name__=='__main__':unittest.main()
