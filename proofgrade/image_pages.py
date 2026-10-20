"""Encode bounded browser-decoded RGB pixels as PNG without image-library DLLs.

Never accept an encoded image here: the browser decodes it, while this server
validates dimensions and byte counts and builds a fresh, metadata-free PNG.
"""

import base64
import binascii
import struct
import zlib

from pydantic import Field

from proofgrade.teacher_models import SubmissionInput

MAX_SIDE = 2400
MAX_PIXELS = 3_000_000
MAX_BASE64 = MAX_PIXELS * 4  # Three RGB bytes become four base64 characters.


class BrowserImageInput(SubmissionInput):
    width: int = Field(ge=1, le=MAX_SIDE)
    height: int = Field(ge=1, le=MAX_SIDE)
    pixels_base64: str = Field(min_length=4, max_length=MAX_BASE64)


def rgb_png(width, height, encoded):
    if (type(width) is not int or type(height) is not int
            or not 1 <= width <= MAX_SIDE or not 1 <= height <= MAX_SIDE
            or width * height > MAX_PIXELS):
        raise ValueError("Prepared images must fit 2400 pixels per side and 3 megapixels.")
    expected = width * height * 3
    if not isinstance(encoded, str) or len(encoded) != width * height * 4:
        raise ValueError("The image pixel count does not match its dimensions. Select the photo again.")
    try:
        pixels = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The image contains invalid pixel data. Select the photo again.") from error
    if len(pixels) != expected:
        raise ValueError("The image pixel count does not match its dimensions. Select the photo again.")

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF))

    # RGB, 8 bits/channel, PNG filter 0 on every row. No external decoder runs.
    stride = width * 3
    rows = b"".join(b"\x00" + pixels[start:start + stride] for start in range(0, expected, stride))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
