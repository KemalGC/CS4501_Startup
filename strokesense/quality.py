"""Unified offline tests and a read-only runtime preflight for StrokeSense.

From anywhere: python /path/to/strokesense/quality.py [--doctor]
The diagnostic never downloads the pose model or opens a video.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MODEL_NAME = "yolo11n-pose.onnx"
REQUIRED_MODULES = ("numpy", "scipy", "cv2", "onnxruntime", "matplotlib")


def inspect_environment(root: Path = ROOT) -> dict:
    """Inspect prerequisites without importing heavy packages or downloading assets."""
    modules = {name: importlib.util.find_spec(name) is not None for name in REQUIRED_MODULES}
    model = Path(root) / "models" / MODEL_NAME
    return {
        "python_ok": sys.version_info >= (3, 10),
        "modules": modules,
        "model_cached": model.is_file() and model.stat().st_size > 0,
        "model_path": str(model),
        "ffmpeg": shutil.which("ffmpeg"),
    }


def show_environment(root: Path = ROOT) -> int:
    state = inspect_environment(root)
    print(f"Python: {sys.version.split()[0]} ({'OK' if state['python_ok'] else 'requires >=3.10'})")
    for module, present in state["modules"].items():
        print(f"{module}: {'installed' if present else 'MISSING'}")
    print(f"Pose model: {'file present (not validated)' if state['model_cached'] else 'not cached (first video run downloads it)'}")
    print(f"Model location: {state['model_path']}")
    print(f"FFmpeg: {state['ffmpeg'] or 'not found (optional for browser MP4 output)'}")
    ready = state["python_ok"] and all(state["modules"].values())
    print(f"Runtime dependencies: {'available' if ready else 'incomplete'}")
    print("Note: this is not a model inference, video decode, or accuracy test.")
    return 0 if ready else 1


def run_tests(root: Path = ROOT) -> int:
    """Run the legacy synthetic functions and the discovered unittest suites."""
    commands = (
        [sys.executable, "tests/test_analysis.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
    )
    with tempfile.TemporaryDirectory(prefix="strokesense-mpl-") as mpl_dir:
        env = os.environ.copy()
        env.setdefault("MPLCONFIGDIR", mpl_dir)
        print("Running StrokeSense offline regression suite ...", flush=True)
        failures = 0
        for cmd in commands:
            print("$ " + " ".join(cmd), flush=True)
            completed = subprocess.run(cmd, cwd=str(root), env=env, check=False)
            failures += completed.returncode != 0
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run StrokeSense tests or inspect runtime prerequisites")
    parser.add_argument("--doctor", action="store_true", help="Check dependencies without downloading or running inference")
    args = parser.parse_args(argv)
    return show_environment() if args.doctor else run_tests()


if __name__ == "__main__":
    raise SystemExit(main())
