"""Fail-closed Batch worker placeholder.

Real StrokeSense inference integration is intentionally deferred until the CPU
pipeline is adapted and tested with the S3 input/report contract. An
unimplemented worker must NEVER produce a fake report or claim success.
"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.error(
        "StrokeSense AWS Batch worker is not yet connected to the analysis "
        "pipeline. No report was written; this job must fail and be refunded."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
