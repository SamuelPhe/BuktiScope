from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

from scripts.build_synthetic_dataset import build_dataset


def test_synthetic_dataset_builder_creates_grouped_splits(tmp_path):
    output = tmp_path / "synthetic-data"
    summary = build_dataset(output, per_split=1, seed=7)

    assert summary["sample_count"] == 45
    assert summary["source_receipts"] == 3
    assert summary["split_counts"] == {"train": 15, "validation": 15, "test": 15}
    assert summary["class_counts"] == {"synthetic_unmodified": 36, "synthetic_edited": 9}
    assert summary["synthetic_only"] is True

    with (output / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 45

    source_splits = {}
    source_variants = {}
    for row in rows:
        source_id = row["source_receipt_id"]
        source_splits.setdefault(source_id, set()).add(row["split"])
        source_variants.setdefault(source_id, set()).add(row["variant"])
        assert row["synthetic_only"] == "True"
        expected_amount = int(row["expected_amount_idr"])
        visible_amount = int(row["visible_amount_idr"])
        assert visible_amount == (
            expected_amount + 1_000_000
            if row["variant"] == "edited_amount"
            else expected_amount
        )
        image_path = output / row["path"]
        assert image_path.is_file()
        with Image.open(image_path) as image:
            assert image.size == (1000, 1300)
            image.verify()
        if row["class_label"] == "synthetic_edited":
            bbox = json.loads(row["manipulation_bbox_xyxy"])
            assert len(bbox) == 4
            assert 0 <= bbox[0] < bbox[2] <= 1000
            assert 0 <= bbox[1] < bbox[3] <= 1300
        else:
            assert row["manipulation_bbox_xyxy"] == ""

    assert all(len(splits) == 1 for splits in source_splits.values())
    assert len(source_splits) == 3
    assert all(len(variants) == 15 for variants in source_variants.values())
    assert summary["variants_per_source_receipt"] == 15
    assert (output / "manifest.jsonl").is_file()
    assert (output / "DATASET_CARD.json").is_file()

    expected_quality_variants = {
        "blur_light",
        "compression_heavy",
        "crop_resize",
        "rotate_small",
        "perspective_warp",
        "screen_glare",
        "moire_pattern",
        "camera_noise",
        "edge_shadow",
        "messenger_export",
    }
    assert expected_quality_variants.issubset({row["variant"] for row in rows})
    assert summary["variant_counts"]["clean"] == 3
    assert summary["variant_counts"]["perspective_warp"] == 3
    for row in rows:
        parameters = json.loads(row["transform_parameters_json"])
        assert isinstance(parameters, dict)
        if row["variant"] == "blur_light":
            assert 0.8 <= parameters["radius"] <= 1.6
        elif row["variant"] == "compression_heavy":
            assert parameters["jpeg_quality"] == 32
        elif row["variant"] == "crop_resize":
            assert parameters["resized_to"] == [1000, 1300]
        elif row["variant"] == "rotate_small":
            assert abs(parameters["angle_degrees"]) <= 2.2
        elif row["variant"] == "perspective_warp":
            assert set(parameters) == {
                "top_left_x", "top_left_y", "top_right_x", "top_right_y",
                "bottom_right_x", "bottom_right_y", "bottom_left_x", "bottom_left_y",
            }
        elif row["variant"] == "screen_glare":
            assert len(parameters["center_xy"]) == 2
            assert 38 <= parameters["opacity"] <= 62
        elif row["variant"] == "moire_pattern":
            assert parameters["line_spacing_px"] in {9, 11, 13}
            assert 14 <= parameters["line_opacity"] <= 24
        elif row["variant"] == "camera_noise":
            assert parameters["noise_sigma"] in {16, 20, 24}
            assert parameters["speckle_count"] == 24_000
            assert len(parameters["speckle_alpha_range"]) == 2
            assert parameters["speckle_alpha_range"][0] < parameters["speckle_alpha_range"][1]
        elif row["variant"] == "edge_shadow":
            assert parameters["side"] in {"left", "right"}
            assert 42 <= parameters["opacity"] <= 72
        elif row["variant"] == "messenger_export":
            assert parameters["intermediate_size"] == [720, 936]
            assert parameters["jpeg_quality"] == 52


def test_synthetic_dataset_builder_refuses_to_overwrite_nonempty_output(tmp_path):
    output = tmp_path / "already-has-data"
    output.mkdir()
    (output / "keep.txt").write_text("do not delete", encoding="utf-8")
    try:
        build_dataset(output, per_split=1)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected a non-empty output directory to be refused")
    assert (output / "keep.txt").read_text(encoding="utf-8") == "do not delete"


def test_synthetic_dataset_builder_is_reproducible(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_dataset(first, per_split=1, seed=42)
    build_dataset(second, per_split=1, seed=42)
    assert (first / "manifest.csv").read_bytes() == (second / "manifest.csv").read_bytes()

    with (first / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    camera_row = next(row for row in rows if row["variant"] == "camera_noise")
    first_image = first / camera_row["path"]
    second_image = second / camera_row["path"]
    assert first_image.read_bytes() == second_image.read_bytes()


def test_synthetic_dataset_builder_caps_dataset_size(tmp_path):
    try:
        build_dataset(tmp_path / "too-large", per_split=101)
    except ValueError as error:
        assert "between 1 and 100" in str(error)
    else:
        raise AssertionError("Expected excessive dataset size to be rejected")
