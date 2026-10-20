"""Prepare Google's licensed excerpt for transcription evaluation, not grade validation."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import tarfile
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

SOURCE = "https://storage.googleapis.com/mathwriting_data/mathwriting-2024-excerpt.tgz"
SHA256 = "cba038def001480a89962b25cb20a60df4c4145e94c86ef9d2af65f192cb82bc"
LICENSE = "CC-BY-NC-SA-4.0"
ATTRIBUTION = (
    "MathWriting dataset by Google LLC. Data: CC BY-NC-SA 4.0. "
    "Rendered PNGs are adaptations of the original InkML strokes. "
    "LaTeX labels derived from Wikipedia retain CC BY-SA obligations. "
    "Source: https://github.com/google-research/google-research/tree/master/mathwriting\n"
    "License: https://creativecommons.org/licenses/by-nc-sa/4.0/\n"
    "Paper: https://arxiv.org/abs/2404.10690\n"
    "For non-commercial research/evaluation. This is expression transcription data, "
    "not teacher-graded homework or proof of grading accuracy.\n"
)


def read_ink(raw):
    if len(raw) > 2_000_000 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("Unsupported InkML document.")
    root = ET.fromstring(raw)
    annotations = {item.attrib.get("type"): item.text or "" for item in root.findall("{*}annotation")}
    strokes, count = [], 0
    for trace in root.findall("{*}trace"):
        points = []
        for point in (trace.text or "").split(","):
            coordinates = point.strip().split()
            if len(coordinates) < 2:
                continue
            x, y = float(coordinates[0]), float(coordinates[1])
            if not all(math.isfinite(v) and abs(v) < 10_000_000 for v in (x, y)):
                raise ValueError("Invalid stroke coordinates.")
            points.append((x, y))
            count += 1
            if count > 50_000:
                raise ValueError("Ink has too many points.")
        if points:
            strokes.append(points)
    if not strokes:
        raise ValueError("Ink has no strokes.")
    return annotations, strokes


def render_strokes(strokes):
    points = [point for stroke in strokes for point in stroke]
    xmin, xmax = min(x for x, y in points), max(x for x, y in points)
    ymin, ymax = min(y for x, y in points), max(y for x, y in points)
    width, height = max(xmax - xmin, 1), max(ymax - ymin, 1)
    scale = min(1500 / width, 600 / height, 3)
    canvas = Image.new("RGB", (math.ceil(width * scale + 48) * 3, math.ceil(height * scale + 48) * 3), "white")
    draw = ImageDraw.Draw(canvas)
    pen = max(5, min(12, round(3 * scale)))
    for stroke in strokes:
        transformed = [((x - xmin) * scale * 3 + 72, (y - ymin) * scale * 3 + 72) for x, y in stroke]
        if len(transformed) > 1:
            draw.line(transformed, fill="black", width=pen, joint="curve")
        for x, y in (transformed[0], transformed[-1]):
            draw.ellipse((x - pen / 2, y - pen / 2, x + pen / 2, y + pen / 2), fill="black")
    return canvas.resize((canvas.width // 3, canvas.height // 3), Image.Resampling.LANCZOS)


def prepare(archive_path, output, split, limit):
    if not 1 <= limit <= 100:
        raise ValueError("Choose 1–100 samples from the official excerpt.")
    archive_path, output = Path(archive_path), Path(output)
    raw = archive_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Archive checksum does not match the verified official excerpt.")
    output.mkdir(parents=True, exist_ok=True)
    images = output / "images"
    images.mkdir(exist_ok=True)
    records = []
    with tarfile.open(archive_path, "r:gz") as archive:
        for entry in sorted(archive.getmembers(), key=lambda e: e.name):
            parts = Path(entry.name).parts
            if len(parts) != 3 or parts[1] != split or not entry.isfile():
                continue
            sample_id = Path(parts[2]).stem
            if not re.fullmatch(r"[a-f0-9]{16}", sample_id) or not parts[2].endswith(".inkml") or entry.size > 2_000_000:
                continue
            metadata, strokes = read_ink(archive.extractfile(entry).read())
            if metadata.get("inkCreationMethod") != "human" or not metadata.get("normalizedLabel"):
                continue
            image_path = f"images/{sample_id}.png"
            render_strokes(strokes).save(output / image_path, format="PNG")
            records.append({"dataset": "MathWriting-2024-excerpt", "sample_id": sample_id,
                            "split": split, "image_path": image_path,
                            "normalized_label": metadata["normalizedLabel"],
                            "source_url": SOURCE, "archive_sha256": SHA256, "license": LICENSE,
                            "task": "expression_transcription"})
            if len(records) == limit:
                break
    if not records:
        raise ValueError("No human-written samples found for this split.")
    (output / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (output / "ATTRIBUTION.txt").write_text(ATTRIBUTION, encoding="utf-8")
    (output / "predictions.example.jsonl").write_text(
        "".join(json.dumps({"sample_id": r["sample_id"], "prediction": ""}) + "\n" for r in records), encoding="utf-8")
    return {"samples": len(records), "split": split, "manifest": str(output / "manifest.jsonl"), "license": LICENSE}


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def score(manifest, predictions):
    expected = {}
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key, label = item["sample_id"], item["normalized_label"]
        if key in expected or not isinstance(label, str) or not 1 <= len(label) <= 2000:
            raise ValueError("Invalid or duplicate manifest record.")
        expected[key] = label
    supplied = {}
    for line in Path(predictions).read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key, prediction = item["sample_id"], item["prediction"]
        if key not in expected or key in supplied or not isinstance(prediction, str) or len(prediction) > 2000:
            raise ValueError("Prediction IDs must be unique and belong to the manifest; text is limited to 2000 characters.")
        supplied[key] = prediction
    if not expected:
        raise ValueError("The manifest is empty.")
    matches = sum(supplied.get(key, "") == label for key, label in expected.items())
    edits = sum(distance(label, supplied.get(key, "")) for key, label in expected.items())
    chars = sum(map(len, expected.values()))
    return {"samples": len(expected), "predictions": len(supplied), "missing_predictions": len(expected) - len(supplied),
            "exact_matches": matches, "exact_match_rate": matches / len(expected),
            "character_error_rate": edits / chars, "metric": "literal normalized-LaTeX transcription; not grading accuracy"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--archive", default="datasets/mathwriting-2024-excerpt.tgz")
    prep.add_argument("--download", action="store_true", help="Download only the official 1.6 MB excerpt.")
    prep.add_argument("--out", default="datasets/mathwriting-valid")
    prep.add_argument("--split", choices=["train", "valid", "test"], default="valid")
    prep.add_argument("--limit", type=int, default=20)
    scoring = commands.add_parser("score")
    scoring.add_argument("--manifest", required=True)
    scoring.add_argument("--predictions", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        archive = Path(args.archive)
        if args.download:
            with urllib.request.urlopen(SOURCE, timeout=30) as response:
                raw = response.read(3_000_001)
            if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != SHA256:
                parser.error("Downloaded excerpt failed size/checksum validation.")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(raw)
        result = prepare(archive, args.out, args.split, args.limit)
    else:
        result = score(args.manifest, args.predictions)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
