from __future__ import annotations

import csv
import json

from PIL import Image

from scripts.evaluate_ocr import evaluate_manifest, load_manifest, summarize


def test_summarize_reports_coverage_and_exact_amount_recognition():
    records = [
        {"amount_detected": True, "exact_amount_match": True, "unexpected_amount_count": 0, "confidence": 90},
        {"amount_detected": True, "exact_amount_match": False, "unexpected_amount_count": 1, "confidence": 80},
        {"amount_detected": False, "exact_amount_match": False, "unexpected_amount_count": 0, "confidence": None},
    ]

    metrics = summarize(records)

    assert metrics["sample_count"] == 3
    assert metrics["samples_with_amount_detected"] == 2
    assert metrics["exact_visible_amount_matches"] == 1
    assert metrics["wrong_amount_only_samples"] == 1
    assert metrics["samples_with_no_amount_detected"] == 1
    assert metrics["unexpected_amount_candidates"] == 1
    assert metrics["exact_amount_match_rate"] == 0.3333
    assert metrics["amount_read_coverage_rate"] == 0.6667
    assert metrics["exact_match_rate_when_amount_detected"] == 0.5
    assert metrics["mean_ocr_confidence"] == 85


def _make_manifest(tmp_path, *, image_relative_path="images/test/sample.jpg", synthetic_only="True"):
    image_path = tmp_path / image_relative_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 160), "white").save(image_path, format="JPEG")

    manifest = tmp_path / "manifest.csv"
    fields = [
        "sample_id", "split", "path", "variant", "layout_id",
        "amount_format_id", "typography_profile_id", "visible_amount_idr", "synthetic_only",
    ]
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "sample_id": "sample_001_clean",
            "split": "test",
            "path": image_relative_path,
            "variant": "clean",
            "layout_id": "classic_card",
            "amount_format_id": "rp_dot_space",
            "typography_profile_id": "standard_bold",
            "visible_amount_idr": "250000",
            "synthetic_only": synthetic_only,
        })
    return manifest


def test_evaluate_manifest_writes_minimized_reports(tmp_path):
    manifest = _make_manifest(tmp_path)
    output_dir = tmp_path / "reports"

    def fake_ocr(_image):
        return {"available": True, "text": "TRANSFER SIMULATION Rp 250.000", "confidence": 94.5}

    report = evaluate_manifest(
        manifest, split="test", output_dir=output_dir, ocr_runner=fake_ocr,
    )

    assert report["scope"] == "synthetic_only"
    assert report["metrics"]["sample_count"] == 1
    assert report["metrics"]["exact_visible_amount_matches"] == 1
    assert report["metrics"]["exact_amount_match_rate"] == 1.0
    assert report["by_variant"]["clean"]["amount_read_coverage_rate"] == 1.0
    assert report["by_layout"]["classic_card"]["sample_count"] == 1
    assert report["by_layout"]["classic_card"]["exact_visible_amount_matches"] == 1
    assert report["by_amount_format"]["rp_dot_space"]["sample_count"] == 1
    assert report["by_typography_profile"]["standard_bold"]["sample_count"] == 1
    assert report["by_layout_typography"]["classic_card|standard_bold"]["sample_count"] == 1
    assert report["by_layout"]["classic_card"]["ocr_strategy_counts"] == {"custom": 1}
    assert report["by_amount_format"]["rp_dot_space"]["ocr_strategy_counts"] == {"custom": 1}
    assert report["by_typography_profile"]["standard_bold"]["ocr_strategy_counts"] == {"custom": 1}
    assert report["by_layout_typography"]["classic_card|standard_bold"]["ocr_strategy_counts"] == {"custom": 1}
    assert report["ocr_strategy_counts"] == {"custom": 1}
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "samples.csv").is_file()

    saved = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert "raw_ocr_text" not in saved
    with (output_dir / "samples.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["extracted_amounts_idr"] == "[250000]"
    assert rows[0]["ocr_strategy"] == "custom"
    assert rows[0]["layout_id"] == "classic_card"
    assert rows[0]["amount_format_id"] == "rp_dot_space"
    assert rows[0]["typography_profile_id"] == "standard_bold"


def test_manifest_rejects_non_synthetic_rows(tmp_path):
    manifest = _make_manifest(tmp_path, synthetic_only="False")
    try:
        load_manifest(manifest, split="test")
    except ValueError as error:
        assert "synthetic_only=true" in str(error)
    else:
        raise AssertionError("Expected non-synthetic rows to be rejected")


def test_manifest_rejects_paths_outside_dataset_root(tmp_path):
    manifest = _make_manifest(tmp_path, image_relative_path="../outside.jpg")
    try:
        load_manifest(manifest, split="test")
    except ValueError as error:
        assert "escapes the dataset directory" in str(error)
    else:
        raise AssertionError("Expected escaping paths to be rejected")


def test_manifest_rejects_missing_selected_split(tmp_path):
    manifest = _make_manifest(tmp_path)
    try:
        load_manifest(manifest, split="train")
    except ValueError as error:
        assert "No synthetic samples" in str(error)
    else:
        raise AssertionError("Expected an empty selected split to be rejected")
