"""Shared GPU preflight error type.

Keep this class in a separately imported module: when preflight runs as
`python -m aws_app.gpu_preflight`, its globals live in __main__, whereas
`aws_app.gpu_preflight` can also be imported by sibling modules.
A class defined in gpu_preflight.py would be two distinct Python types.
"""
from __future__ import annotations

from typing import Any


class GpuPreflightError(RuntimeError):
    """Fixed category and structured diagnostics, never raw sensitive data."""

    def __init__(self, category: str, *, stage: str | None = None,
                 diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(category)
        self.stage = stage
        self.diagnostics = diagnostics or {}
