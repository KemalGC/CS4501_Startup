"""CLI argument regression tests; analysis/inference is never invoked.

Test-first checkpoint for issue #24: this branch intentionally keeps the old
argument parser so rejected-parameter assertions demonstrate the original bug.
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if importlib.util.find_spec("cv2") is None:
    sys.modules["cv2"] = types.ModuleType("cv2")
    try:
        from strokesense import cli
    finally:
        del sys.modules["cv2"]
else:
    from strokesense import cli


class CliOptionsTests(unittest.TestCase):
    def test_auto_tiling_is_default(self):
        with patch.object(cli, "analyse_video", return_value=object()) as run:
            self.assertEqual(cli.main(["footage.mp4"]), 0)
        self.assertEqual(run.call_args.args[4], "auto")

    def test_none_explicitly_disables_tiling(self):
        with patch.object(cli, "analyse_video", return_value=object()) as run:
            self.assertEqual(cli.main(["footage.mp4", "--tiles", "none"]), 0)
        self.assertIsNone(run.call_args.args[4])

    def test_misspelled_tiling_mode_fails_before_analysis(self):
        with patch.object(cli, "analyse_video") as run, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                cli.main(["footage.mp4", "--tiles", "auot"])
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()


    def test_nonpositive_or_nonfinite_frame_rates_fail_fast(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=value), patch.object(cli, "analyse_video") as run, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(["footage.mp4", "--fps", value])
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_invalid_start_and_duration_fail_fast(self):
        for flag, value in (
            ("--start", "-0.1"), ("--start", "nan"),
            ("--start", "inf"), ("--duration", "0"),
            ("--duration", "-1"), ("--duration", "nan"),
            ("--duration", "-inf"),
        ):
            with self.subTest(flag=flag, value=value), \
                    patch.object(cli, "analyse_video") as run, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(["footage.mp4", flag, value])
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_valid_fractional_settings_are_forwarded_unchanged(self):
        with patch.object(cli, "analyse_video", return_value=object()) as run:
            self.assertEqual(cli.main([
                "footage.mp4", "--start", "0.75", "--duration", "1.25",
                "--fps", "29.97",
            ]), 0)
        self.assertEqual(run.call_args.args[2:4], (0.75, 1.25))
        self.assertEqual(run.call_args.args[5], 29.97)


if __name__ == "__main__":
    unittest.main()
