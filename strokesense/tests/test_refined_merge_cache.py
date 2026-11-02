"""The refined detector revision is part of persisted selected-pose identity."""
import json
from pathlib import Path
import tempfile
import unittest
from test_selected_crew import selection
from strokesense import cli


class RefinedMergeCacheTests(unittest.TestCase):
    def test_new_merge_is_part_of_selected_v2_cache_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'clip.mov';video.write_bytes(b'synthetic')
            selected=dict(selection(),version=2,reference_seconds=0.)
            identity=json.loads(cli._cache_identity(video,0,None,'auto',15,None,selection=selected))
            legacy=json.loads(cli._cache_identity(video,0,None,'auto',15,None))
        self.assertEqual(identity['settings'].get('refined_merge'),'torso-landmarks-v1')
        self.assertNotIn('refined_merge',legacy['settings'])


if __name__=='__main__':unittest.main()
