"""Bounded format-signature preflight for local video imports.

Checks container-family headers only. It DOES NOT decode video, prove that a
video stream exists, detect malware, verify consent, or certify codec support.
Input is already bounded to the browser upload limit by the caller.
"""
from __future__ import annotations

_SUPPORTED_BMFF = frozenset({".mp4", ".mov"})
_SUPPORTED_EBML = frozenset({".mkv", ".webm"})


def plausible_container(data: bytes, extension: str) -> bool:
    """Fail closed for clearly incompatible or truncated container headers."""
    if not isinstance(data, bytes) or not isinstance(extension, str):
        return False
    extension = extension.lower()
    if extension in _SUPPORTED_BMFF:
        if len(data) < 16 or data[4:8] != b"ftyp":
            return False
        first_box_size = int.from_bytes(data[:4], "big")
        return (16 <= first_box_size <= len(data) and
                all(32 <= byte <= 126 for byte in data[8:12]))
    if extension == ".avi":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"AVI ":
            return False
        declared_size = int.from_bytes(data[4:8], "little")
        return 16 <= declared_size <= len(data) - 8
    if extension in _SUPPORTED_EBML:
        if len(data) < 6 or data[:4] != b"\x1a\x45\xdf\xa3":
            return False
        # EBML's header element length is an unsigned variable-length integer.
        # Reject invalid widths, unknown-size sentinels and incomplete headers.
        first = data[4]
        mask, width = 0x80, 1
        while width <= 8 and not (first & mask):
            mask >>= 1
            width += 1
        if width > 8 or len(data) < 4 + width:
            return False
        length = first & (mask - 1)
        for byte in data[5:4 + width]:
            length = (length << 8) | byte
        max_vint = (1 << (7 * width)) - 1
        return (0 < length < max_vint and
                length <= 4096 and 4 + width + length <= len(data))
    return False
