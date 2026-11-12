"""Exercise the browser-to-Render bridge without deploying or running inference."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.hosted_demo_ui import BRIDGE_SCRIPT


BRIDGE_CONTRACT = r"""
const token='test-csrf';
const window={addEventListener(){}};
window.parent=window;
const calls=[];
async function fetch(path,opts={}){
  calls.push({path,opts});
  return {ok:true,json:async()=>({started:true})};
}
""" + BRIDGE_SCRIPT + r"""
function check(ok,message){if(!ok)throw Error(message);}
async function expectError(action,payload,expected){
  try {await ssBridgeRequest(action,payload);} catch(e){
    check(e.message===expected,'wrong error: '+e.message);return;
  }
  throw Error('expected '+expected);
}
(async()=>{
  const session='a'.repeat(32);
  const upload='b'.repeat(48);
  const deleteToken='c'.repeat(40);
  await ssBridgeRequest('status',{clipId:null,sessionId:session});
  check(calls[0].path==='/api/demo/sessions/'+session+'/status',
        'prepared status must use its isolated session');
  await ssBridgeRequest('analyze',{clipId:null,sessionId:session});
  check(calls[1].path==='/api/demo/sessions/'+session+'/analyze',
        'prepared analyze must use the session route');
  check(!('x-demo-delete-token' in calls[1].opts.headers),
        'prepared analysis must not require an upload deletion token');
  await expectError('analyze',{clipId:upload},'invalid_delete_token');
  check(calls.length===2,'unauthorized upload analysis must never reach fetch');
  await ssBridgeRequest('analyze',{clipId:upload,deleteToken});
  check(calls[2].path==='/api/demo/videos/'+upload+'/analyze',
        'uploaded analysis must use the video route');
  check(calls[2].opts.headers['x-demo-delete-token']===deleteToken,
        'uploaded analysis must carry its deletion capability');
  await expectError('analyze',{clipId:null,sessionId:'bad'},'invalid_session_id');
  check(calls.length===3,'invalid session must not reach fetch');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


class HostedBridgeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required to evaluate browser bridge JavaScript")
    def test_prepared_analysis_does_not_need_upload_delete_token(self):
        run = subprocess.run(["node", "-"], input=BRIDGE_CONTRACT,
                             text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
