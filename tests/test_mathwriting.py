import json

import pytest

from proofgrade.mathwriting import read_ink, render_strokes, score


def test_render_own_synthetic_strokes_and_reject_entities():
    own_ink = b'<ink xmlns="http://www.w3.org/2003/InkML"><annotation type="normalizedLabel">x</annotation><trace>0 0 0, 10 10 1</trace><trace>10 0 2,0 10 3</trace></ink>'
    labels, strokes = read_ink(own_ink)
    assert labels["normalizedLabel"] == "x"
    image = render_strokes(strokes)
    assert image.width > 0 and image.height > 0
    assert image.getextrema()[0][0] < 100
    with pytest.raises(ValueError):
        read_ink(b'<!DOCTYPE ink [<!ENTITY x "a">]><ink/>')


def test_missing_predictions_count_as_errors(tmp_path):
    manifest, predictions = tmp_path / "manifest.jsonl", tmp_path / "predictions.jsonl"
    manifest.write_text('\n'.join(json.dumps({"sample_id": k, "normalized_label": v}) for k, v in [("a", "x=2"), ("b", "x=3")]))
    predictions.write_text(json.dumps({"sample_id": "a", "prediction": "x=2"}))
    result = score(manifest, predictions)
    assert result["exact_match_rate"] == 0.5
    assert result["character_error_rate"] == 0.5
    assert result["missing_predictions"] == 1
    predictions.write_text(json.dumps({"sample_id": "unknown", "prediction": "x=2"}))
    with pytest.raises(ValueError):
        score(manifest, predictions)
