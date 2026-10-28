"""Explicit local coaching verification runner.

Offline candidate files are test doubles. A successful validator result is NOT
written to a saved job, published to the browser, or proof of coach approval.
Provider requests require an explicit --live flag and configured credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .correction import run_correction
from .evidence import validate_reference_graph
from .provider import OpenAIChatGenerator, ProviderError


MAX_METRICS_BYTES = 16 * 1024 * 1024
MAX_CUES_BYTES = 256 * 1024
MAX_CANDIDATES_BYTES = 256 * 1024


class _InvalidInput(ValueError):
    """Never surface file paths, payloads or parser internals to the caller."""


def _bounded_json(path: str, limit: int):
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise _InvalidInput()
        return json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise _InvalidInput() from None


def _withheld(mode: str, error: str) -> dict:
    return {
        "mode": mode,
        "status": "withheld",
        "attempts": 0,
        "released": None,
        "errors": [error],
        "warnings": [],
        "published": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate structured coaching against saved evidence (no job publication)"
    )
    parser.add_argument("--metrics", required=True, help="Saved metrics.json from analysis")
    parser.add_argument("--cues", required=True, help="Separately supplied reviewed-cue JSON map")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--candidates", help="Offline JSON array of 1–3 synthetic candidate objects"
    )
    mode_group.add_argument(
        "--live", action="store_true",
        help="Explicitly authorize configured HTTPS LLM requests (may incur costs)"
    )
    args = parser.parse_args(argv)
    mode = "live_provider" if args.live else "offline_fixture"

    try:
        metrics = _bounded_json(args.metrics, MAX_METRICS_BYTES)
        cues = _bounded_json(args.cues, MAX_CUES_BYTES)
        if not isinstance(metrics, dict) or not isinstance(cues, dict):
            raise _InvalidInput()
        snapshot = metrics.get("evidence")
        if not validate_reference_graph(snapshot):
            raise _InvalidInput()
        if args.live:
            try:
                generator = OpenAIChatGenerator.from_env(snapshot, cues)
            except (ProviderError, ValueError):
                result = _withheld(mode, "missing_configuration")
                print(json.dumps(result, sort_keys=True))
                return 2
            max_attempts = 3
        else:
            candidates = _bounded_json(args.candidates, MAX_CANDIDATES_BYTES)
            if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 3
                    or any(not isinstance(item, dict) for item in candidates)):
                raise _InvalidInput()
            # Exact recorded responses: no network and no fabricated retries.
            generator = lambda attempt, _errors: candidates[attempt - 1]
            max_attempts = len(candidates)
    except _InvalidInput:
        print(json.dumps(_withheld(mode, "invalid_input"), sort_keys=True))
        return 2

    result = run_correction(
        generator, evidence_snapshot=snapshot, reviewed_cues=cues,
        max_attempts=max_attempts,
    )
    # "released" means locally validated, never approved for job/UI release.
    result = {"mode": mode, "published": False, **result}
    if result["status"] == "released":
        result["warnings"] = list(result["warnings"]) + [
            "cue_review_provenance_not_verified",
            "validation_demo_only",
        ]
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "released" else 1


if __name__ == "__main__":
    sys.exit(main())
