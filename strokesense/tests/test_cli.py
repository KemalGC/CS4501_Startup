"""CLI argument regression tests; analysis/inference is never invoked."""
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


if __name__ == "__main__":
    unittest.main()
