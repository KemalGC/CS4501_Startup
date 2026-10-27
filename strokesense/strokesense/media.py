"""Bounded format-signature preflight for local video imports.

Checks container-family headers only. It DOES NOT decode video, prove that a
video stream exists, detect malware, verify consent, or certify codec support.
Input is already bounded to the browser upload limit by the caller.
"""
from __future__ import annotations

import math

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


class UndecodableMediaError(ValueError):
    """Expected safe failure when local footage cannot be opened or read."""


def probe_decodable_video(path) -> bool:
    """Try one frame inside the background worker, before expensive pose work.

    This is a fast UX preflight, not proof that all frames decode safely.
    No model download, report write or network request occurs here.
    """
    capture = None
    try:
        import cv2  # Lazy: importing this module itself has no native deps.
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return False
        width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        max_pixels = 3840 * 2160
        if not all(math.isfinite(x) for x in (width, height, fps)):
            return False
        if (width < 64 or height < 64 or width * height > max_pixels
                or not 0 < fps <= 240):
            return False
        decoded, frame = capture.read()
        shape = getattr(frame, "shape", None)
        if (not decoded or not isinstance(shape, tuple)
                or len(shape) < 2):
            return False
        rows, columns = shape[:2]
        return (type(rows) is int and type(columns) is int
                and rows >= 64 and columns >= 64
                and rows * columns <= max_pixels)
    except Exception:
        # Codec error text can reveal local paths; only a safe code escapes.
        return False
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
