from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps

from app.analyzer import _extract_amounts, _run_ocr, _tesseract_binary, _tesseract_languages

SPLITS = ("train", "validation", "test")
REQUIRED_COLUMNS = {
    "sample_id", "split", "path", "variant", "visible_amount_idr", "synthetic_only",
}
LIMITATIONS = [
    "This benchmark measures OCR reading on controlled synthetic images only.",
    "It does not measure whether a transfer occurred, whether funds arrived, or whether an image is authentic.",
    "Synthetic layouts and simple field replacements do not represent the diversity of real receipts or sophisticated edits.",
    "Results must not be presented as real-world fraud-detection accuracy.",
]


def load_manifest(manifest_path: Path, split: str = "test") -> list[dict[str, Any]]:
    """Load selected synthetic samples while preventing paths from escaping the dataset."""
    if split not in {*SPLITS, "all"}:
        raise ValueError(f"split must be one of {', '.join((*SPLITS, 'all'))}")

    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    dataset_root = manifest_path.parent.resolve()

    samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Manifest is missing required columns: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            if str(row.get("synthetic_only", "")).strip().lower() != "true":
                raise ValueError(f"Manifest row {line_number} is not marked synthetic_only=true")

            row_split = str(row.get("split", "")).strip()
            if row_split not in SPLITS:
                raise ValueError(f"Manifest row {line_number} has an unsupported split")
            if split != "all" and row_split != split:
                continue

            sample_id = str(row.get("sample_id", "")).strip()
            variant = str(row.get("variant", "")).strip()
            relative_value = str(row.get("path", "")).strip()
            if not sample_id or not variant or not relative_value:
                raise ValueError(f"Manifest row {line_number} is missing sample metadata")
            if sample_id in seen_ids:
                raise ValueError(f"Duplicate sample_id in manifest: {sample_id}")
            seen_ids.add(sample_id)

            try:
                visible_amount = int(row["visible_amount_idr"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Manifest row {line_number} has an invalid visible_amount_idr") from exc
            if visible_amount <= 0:
                raise ValueError(f"Manifest row {line_number} has a non-positive visible_amount_idr")

            relative_path = Path(relative_value)
            image_path = (dataset_root / relative_path).resolve()
            try:
                image_path.relative_to(dataset_root)
            except ValueError as exc:
                raise ValueError(f"Manifest row {line_number} image path escapes the dataset directory") from exc
            if not image_path.is_file():
                raise FileNotFoundError(f"Image listed in manifest does not exist: {relative_path}")

            samples.append({
                "sample_id": sample_id,
                "split": row_split,
                "path": relative_path.as_posix(),
                "image_path": image_path,
                "variant": variant,
                "visible_amount_idr": visible_amount,
            })

    if not samples:
        raise ValueError(f"No synthetic samples found for split '{split}'")
    return sorted(samples, key=lambda item: item["sample_id"])


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize exact visible-amount recognition without treating it as fraud detection."""
    sample_count = len(records)
    detected_count = sum(bool(item["amount_detected"]) for item in records)
    exact_count = sum(bool(item["exact_amount_match"]) for item in records)
    wrong_only_count = sum(
        bool(item["amount_detected"]) and not bool(item["exact_amount_match"])
        for item in records
    )
    no_amount_count = sample_count - detected_count
    unexpected_count = sum(int(item["unexpected_amount_count"]) for item in records)
    confidence_values = [
        float(item["confidence"])
        for item in records
        if item.get("confidence") is not None
        and math.isfinite(float(item["confidence"]))
    ]

    return {
        "sample_count": sample_count,
        "samples_with_amount_detected": detected_count,
        "exact_visible_amount_matches": exact_count,
        "wrong_amount_only_samples": wrong_only_count,
        "samples_with_no_amount_detected": no_amount_count,
        "unexpected_amount_candidates": unexpected_count,
        "exact_amount_match_rate": _rate(exact_count, sample_count),
        "amount_read_coverage_rate": _rate(detected_count, sample_count),
        "exact_match_rate_when_amount_detected": _rate(exact_count, detected_count),
        "mean_ocr_confidence": (
            round(sum(confidence_values) / len(confidence_values), 2)
            if confidence_values else None
        ),
    }


def evaluate_manifest(
    manifest_path: Path,
    split: str,
    output_dir: Path,
    ocr_runner: Callable[[Image.Image], dict[str, Any]] | None = None,
    engine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run OCR on manifest images and write privacy-minimized aggregate/sample reports."""
    samples = load_manifest(manifest_path, split=split)
    runner = ocr_runner or _run_ocr
    records: list[dict[str, Any]] = []

    for sample in samples:
        try:
            with Image.open(sample["image_path"]) as source:
                source.verify()
            with Image.open(sample["image_path"]) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                ocr_result = runner(image)
        except Exception as exc:
            raise RuntimeError(f"Could not evaluate sample {sample['sample_id']}: {exc}") from exc

        extracted = _extract_amounts(str(ocr_result.get("text") or ""))
        expected = int(sample["visible_amount_idr"])
        exact_match = expected in extracted
        confidence = ocr_result.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
            if confidence_value is not None and not math.isfinite(confidence_value):
                confidence_value = None
        except (TypeError, ValueError):
            confidence_value = None

        records.append({
            "sample_id": sample["sample_id"],
            "split": sample["split"],
            "variant": sample["variant"],
            "expected_visible_amount_idr": expected,
            "extracted_amounts_idr": extracted,
            "amount_detected": bool(extracted),
            "exact_amount_match": exact_match,
            "unexpected_amount_count": sum(amount != expected for amount in extracted),
            "ocr_available": bool(ocr_result.get("available")),
            "confidence": confidence_value,
        })

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["variant"]].append(record)

    report = {
        "benchmark": "BuktiScope synthetic OCR amount-reading baseline",
        "scope": "synthetic_only",
        "split": split,
        "engine": engine or {"name": "injected test runner"},
        "metrics": summarize(records),
        "by_variant": {
            variant: summarize(grouped[variant])
            for variant in sorted(grouped)
        },
        "limitations": LIMITATIONS,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sample_fields = [
        "sample_id", "split", "variant", "expected_visible_amount_idr",
        "extracted_amounts_idr", "amount_detected", "exact_amount_match",
        "unexpected_amount_count", "ocr_available", "confidence",
    ]
    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sample_fields)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["extracted_amounts_idr"] = json.dumps(row["extracted_amounts_idr"])
            writer.writerow(row)

    return report


def _tesseract_engine_details() -> dict[str, Any]:
    binary = _tesseract_binary()
    languages = _tesseract_languages()
    if not binary:
        raise RuntimeError("Tesseract OCR is not installed or TESSERACT_CMD is not configured.")
    if not languages:
        raise RuntimeError("Tesseract is available, but no language data could be detected.")
    selected = [language for language in ("ind", "eng") if language in languages]
    if not selected:
        raise RuntimeError("Install at least one supported Tesseract language: ind or eng.")

    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=True, timeout=5,
    )
    version = result.stdout.splitlines()[0].strip() if result.stdout else "unknown"
    return {
        "name": "Tesseract OCR",
        "version": version,
        "languages_available": sorted(languages),
        "languages_selected_by_application": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure BuktiScope OCR amount reading on the synthetic receipt dataset."
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Path to the synthetic dataset manifest.csv")
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="test",
                        help="Dataset split to evaluate (default: test; prefer test for baseline)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/ocr-benchmark"),
                        help="Directory for summary.json and samples.csv")
    args = parser.parse_args()

    try:
        engine = _tesseract_engine_details()
        report = evaluate_manifest(
            manifest_path=args.manifest,
            split=args.split,
            output_dir=args.output_dir,
            engine=engine,
        )
    except (FileNotFoundError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
