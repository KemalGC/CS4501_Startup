"""Small, strictly validated manifest for private analysis media.

This manifest contains only expected basenames, never user-supplied S3 keys or
URLs. The API derives all S3 keys from an already owner-checked job record.
"""

from __future__ import annotations

import math
import re
from typing import Any


SCHEMA = "strokesense-private-artifacts-v1"
MANIFEST_NAME = "artifacts.json"
VIDEO_NAME = "annotated.mp4"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_VIDEO_BYTES = 120 * 1024 * 1024
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_TOTAL_BYTES = 36 * 1024 * 1024
MAX_PHOTO_COUNT = 128

_SEAT = re.compile(r"R(?:[1-9]|1[0-6])\Z")
_PHOTO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.jpg\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,60}\Z")
_LABELS = frozenset(("Catch reference", "Finish reference", "Before", "Flagged moment", "After"))


class InvalidArtifactManifest(ValueError):
    """Reject metadata that could lead to unexpected media disclosure."""


def _frame(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidArtifactManifest("invalid_frame")
    filename = raw.get("filename")
    label = raw.get("label")
    seconds = raw.get("time_seconds")
    if not isinstance(filename, str) or not _PHOTO.fullmatch(filename):
        raise InvalidArtifactManifest("invalid_frame_filename")
    if label not in _LABELS:
        raise InvalidArtifactManifest("invalid_frame_label")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 <= seconds <= 86400:
        raise InvalidArtifactManifest("invalid_frame_time")
    return {"filename": filename, "label": label, "time_seconds": float(seconds)}


def validate_rowers(raw: Any) -> dict[str, Any]:
    """Accept only the exact bounded photo-gallery structure emitted by CLI."""
    if not isinstance(raw, dict) or len(raw) > 16:
        raise InvalidArtifactManifest("invalid_rower_gallery")
    clean: dict[str, Any] = {}
    for seat, data in raw.items():
        if not isinstance(seat, str) or not _SEAT.fullmatch(seat) or not isinstance(data, dict):
            raise InvalidArtifactManifest("invalid_gallery_seat")
        snapshots = data.get("snapshots", [])
        sequences = data.get("mistake_sequences", [])
        if not isinstance(snapshots, list) or len(snapshots) > 2 or not isinstance(sequences, list) or len(sequences) > 3:
            raise InvalidArtifactManifest("invalid_gallery_bounds")
        clean_snapshots = [_frame(photo) for photo in snapshots]
        clean_sequences = []
        for seq in sequences:
            if not isinstance(seq, dict):
                raise InvalidArtifactManifest("invalid_gallery_sequence")
            code = seq.get("code")
            stroke = seq.get("stroke")
            frames = seq.get("frames")
            if not isinstance(code, str) or not _CODE.fullmatch(code) or type(stroke) is not int or not 0 <= stroke <= 10000:
                raise InvalidArtifactManifest("invalid_gallery_sequence")
            if not isinstance(frames, list) or not 1 <= len(frames) <= 3:
                raise InvalidArtifactManifest("invalid_gallery_frames")
            clean_frames = [_frame(photo) for photo in frames]
            if sum(photo["label"] == "Flagged moment" for photo in clean_frames) != 1:
                raise InvalidArtifactManifest("missing_flagged_moment")
            clean_sequences.append({"code": code, "stroke": stroke, "frames": clean_frames})
        clean[seat] = {"snapshots": clean_snapshots, "mistake_sequences": clean_sequences}
    return clean


def frame_names(rowers: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for rower in rowers.values():
        for frame in rower["snapshots"]:
            names.add(frame["filename"])
        for sequence in rower["mistake_sequences"]:
            for frame in sequence["frames"]:
                names.add(frame["filename"])
    return names


def validate_published(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA or type(raw.get("video_available")) is not bool:
        raise InvalidArtifactManifest("invalid_published_manifest")
    rowers = validate_rowers(raw.get("rowers"))
    if len(frame_names(rowers)) > MAX_PHOTO_COUNT:
        raise InvalidArtifactManifest("too_many_frames")
    return {"schema_version": SCHEMA, "video_available": raw["video_available"], "rowers": rowers}
