from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

from scripts.build_synthetic_dataset import build_dataset


def test_synthetic_dataset_builder_creates_grouped_splits(tmp_path):
    output = tmp_path / "synthetic-data"
    summary = build_dataset(output, per_split=1, seed=7)

    assert summary["sample_count"] == 15
    assert summary["source_receipts"] == 3
    assert summary["split_counts"] == {"train": 5, "validation": 5, "test": 5}
    assert summary["class_counts"] == {"synthetic_unmodified": 6, "synthetic_edited": 9}
    assert summary["synthetic_only"] is True

    with (output / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 15

    source_splits = {}
    for row in rows:
        source_id = row["source_receipt_id"]
        source_splits.setdefault(source_id, set()).add(row["split"])
        assert row["synthetic_only"] == "True"
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
    assert (output / "manifest.jsonl").is_file()
    assert (output / "DATASET_CARD.json").is_file()


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
