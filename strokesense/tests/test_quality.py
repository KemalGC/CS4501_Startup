"""Regression tests for the offline test runner and read-only environment doctor."""
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality  # noqa: E402


class QualityCommandTests(unittest.TestCase):
    def test_missing_prerequisites_are_reported_without_downloading(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(quality.importlib.util, "find_spec", return_value=None), \
                patch.object(quality.shutil, "which", return_value=None):
            status = quality.inspect_environment(Path(d))
        self.assertFalse(status["model_cached"])
        self.assertTrue(all(not present for present in status["modules"].values()))
        self.assertIsNone(status["ffmpeg"])

    def test_cached_model_and_installed_prerequisites_are_recognized(self):
        with tempfile.TemporaryDirectory() as d:
            models = Path(d) / "models"
            models.mkdir()
            (models / quality.MODEL_NAME).write_bytes(b"placeholder only")
            with patch.object(quality.importlib.util, "find_spec", return_value=object()), \
                    patch.object(quality.shutil, "which", return_value="/usr/bin/ffmpeg"):
                status = quality.inspect_environment(Path(d))
        self.assertTrue(status["model_cached"])
        self.assertTrue(all(status["modules"].values()))
        self.assertEqual(status["ffmpeg"], "/usr/bin/ffmpeg")

    def test_runner_invokes_full_unittest_discovery_from_project_directory(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(quality.subprocess, "run", side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=7)]) as run, \
                patch("builtins.print"):
            result = quality.run_tests(Path(d))
        self.assertEqual(result, 1)
        args, kwargs = run.call_args
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, "tests/test_analysis.py"])
        self.assertEqual(args[0][:4], [sys.executable, "-m", "unittest", "discover"])
        self.assertEqual(args[0][-2:], ["test_*.py", "-v"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], d)
            self.assertTrue(call.kwargs["env"].get("MPLCONFIGDIR"))
            self.assertFalse(call.kwargs["check"])

    def test_doctor_fails_without_required_module_but_not_without_cached_model(self):
        base = {
            "python_ok": True,
            "modules": {name: True for name in quality.REQUIRED_MODULES},
            "model_cached": False,
            "model_path": "/nonexistent/yolo11n-pose.onnx",
            "ffmpeg": None,
        }
        with patch.object(quality, "inspect_environment", return_value=base), patch("builtins.print"):
            self.assertEqual(quality.show_environment(), 0)
        broken = {**base, "modules": {**base["modules"], "onnxruntime": False}}
        with patch.object(quality, "inspect_environment", return_value=broken), patch("builtins.print"):
            self.assertEqual(quality.show_environment(), 1)

    def test_both_suites_execute_when_legacy_tests_fail(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(quality.subprocess, "run", side_effect=[SimpleNamespace(returncode=4), SimpleNamespace(returncode=0)]) as run, \
                patch("builtins.print"):
            self.assertEqual(quality.run_tests(Path(d)), 1)
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
