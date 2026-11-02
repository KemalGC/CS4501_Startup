"""Documented local-model request contract; fake server data is not model accuracy."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.blade_model import LocalVision, BladeModelError, strict_json


class BladeProviderTests(unittest.TestCase):
    def test_preflight_requires_installed_local_vision_and_stable_digest(self):
        p = LocalVision('qwen3-vl:4b')
        def metadata(route, data=None):
            return {'models': [{'name': p.model, 'digest': 'a'*64, 'size': 100}]} if route == '/api/tags' else {'capabilities': ['vision']}
        with patch.object(p, '_request', side_effect=metadata):
            self.assertEqual(p.check()['digest'], 'a'*64)
            p.digest = 'b'*64
            with self.assertRaisesRegex(BladeModelError, 'model_changed'): p.check()
    def test_cloud_metadata_is_rejected_before_images(self):
        p = LocalVision('qwen3-vl:4b')
        for field in ('remote_host', 'remote_model'):
            with self.subTest(field=field), patch.object(p, '_request', side_effect=[
                {'models': [{'name': p.model, 'digest': 'a'*64, 'size': 100}]},
                {'capabilities': ['vision'], field: 'remote'}]):
                with self.assertRaisesRegex(BladeModelError, 'local_vision'): p.check()
    def test_actual_request_has_reference_images_schema_and_fixed_sampling_times(self):
        p = LocalVision('qwen3-vl:4b'); p.digest = 'a'*64
        response = {'done': True, 'done_reason': 'stop', 'message': {'content':
            '{"observations":[{"frame_id":23,"state":"water","same_blade":true}]}'}}
        with patch.object(p, '_request', return_value=response) as request:
            result = p.predict('reference_bytes', [{'frame_id': 23, 'time': 2.3, 'image': 'image_bytes'}])
        data = request.call_args.args[1]
        self.assertEqual(data['messages'][0]['images'], ['reference_bytes', 'image_bytes'])
        self.assertFalse(data['stream'])
        self.assertEqual(data['format']['additionalProperties'], False)
        self.assertIn('Never infer contact from body pose', data['messages'][0]['content'])
        self.assertEqual(result[0]['time'], 2.3)
    def test_duplicate_fields_truncation_and_unexpected_ids_fail_closed(self):
        with self.assertRaises(BladeModelError): strict_json('{"x":1,"x":2}')
        p = LocalVision('qwen3-vl:4b'); p.digest = 'a'*64
        frame = [{'frame_id': 1, 'time': .1, 'image': 'data'}]
        for response in [{'done': False}, {'done': True, 'done_reason': 'length', 'message': {'content': '{}'}},
                         {'done': True, 'done_reason': 'stop', 'message': {'content':
                         '{"observations":[{"frame_id":99,"state":"water","same_blade":true}]}'}}]:
            with self.subTest(response=response), patch.object(p, '_request', return_value=response):
                with self.assertRaises(BladeModelError): p.predict('ref', frame)


if __name__ == '__main__': unittest.main()
