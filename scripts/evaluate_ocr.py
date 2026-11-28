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

from app.analyzer import (
    _extract_amounts,
    _locate_amount_regions,
    _run_ocr_with_fallback,
    _tesseract_binary,
    _tesseract_languages,
)

SPLITS = ("train", "validation", "test")
REQUIRED_COLUMNS = {
    "sample_id", "split", "path", "variant", "layout_id", "amount_format_id",
    "typography_profile_id", "visible_amount_idr", "synthetic_only",
}
LIMITATIONS = [
    "This benchmark measures OCR reading on controlled synthetic images only.",
    "It does not measure whether a transfer occurred, whether funds arrived, or whether an image is authentic.",
    "The three fictional receipt layouts are not based on real banks and do not represent the diversity of real receipt templates.",
    "Synthetic quality transforms do not reproduce real cameras, screen glare, moiré, reflections, or messenger-specific processing.",
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
            layout_id = str(row.get("layout_id", "")).strip()
            amount_format_id = str(row.get("amount_format_id", "")).strip()
            typography_profile_id = str(row.get("typography_profile_id", "")).strip()
            relative_value = str(row.get("path", "")).strip()
            if (
                not sample_id or not variant or not layout_id
                or not amount_format_id or not typography_profile_id or not relative_value
            ):
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
                "layout_id": layout_id,
                "amount_format_id": amount_format_id,
                "typography_profile_id": typography_profile_id,
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
    unexpected_sample_count = sum(
        int(item["unexpected_amount_count"]) > 0 for item in records
    )
    total_candidate_count = sum(
        int(item.get("amount_candidate_count", len(item.get("extracted_amounts_idr", []))))
        for item in records
    )
    role_names = (
        "transfer_labeled", "amount_labeled", "fee_labeled",
        "debit_total_labeled", "balance_labeled", "unclassified",
    )
    amount_role_counts = {
        role: sum(int(item.get("amount_role_counts", {}).get(role, 0)) for item in records)
        for role in role_names
    }
    transfer_candidate_count = amount_role_counts["transfer_labeled"]
    expected_transfer_matches = sum(
        bool(item.get("expected_in_transfer_label")) for item in records
    )
    expected_transfer_candidate_count = sum(
        int(item.get("expected_transfer_labeled_candidate_count", 0))
        for item in records
    )
    transfer_labeled_sample_count = sum(
        int(item.get("amount_role_counts", {}).get("transfer_labeled", 0)) > 0
        for item in records
    )
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
        "samples_with_unexpected_amount_candidates": unexpected_sample_count,
        "unexpected_candidate_sample_rate": _rate(unexpected_sample_count, sample_count),
        "total_amount_candidates": total_candidate_count,
        "expected_amount_candidate_precision": _rate(exact_count, total_candidate_count),
        "amount_role_counts": amount_role_counts,
        "samples_with_transfer_labeled_amount": transfer_labeled_sample_count,
        "expected_transfer_labeled_amount_matches": expected_transfer_matches,
        "expected_transfer_labeled_candidate_count": expected_transfer_candidate_count,
        "expected_transfer_label_match_rate_when_labeled": (
            _rate(expected_transfer_matches, transfer_labeled_sample_count)
            if transfer_labeled_sample_count else None
        ),
        "transfer_labeled_candidate_precision": (
            _rate(expected_transfer_candidate_count, transfer_candidate_count)
            if transfer_candidate_count else None
        ),
        "exact_amount_match_rate": _rate(exact_count, sample_count),
        "amount_read_coverage_rate": _rate(detected_count, sample_count),
        "exact_match_rate_when_amount_detected": _rate(exact_count, detected_count),
        "mean_ocr_confidence": (
            round(sum(confidence_values) / len(confidence_values), 2)
            if confidence_values else None
        ),
    }


def summarize_with_strategies(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach OCR fallback usage to a group's reading metrics."""
    summary = summarize(records)
    summary["ocr_strategy_counts"] = {
        strategy: sum(1 for record in records if record["ocr_strategy"] == strategy)
        for strategy in sorted({record["ocr_strategy"] for record in records})
    }
    return summary


def evaluate_manifest(
    manifest_path: Path,
    split: str,
    output_dir: Path,
    ocr_runner: Callable[[Image.Image], dict[str, Any]] | None = None,
    engine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run OCR on manifest images and write privacy-minimized aggregate/sample reports."""
    samples = load_manifest(manifest_path, split=split)
    records: list[dict[str, Any]] = []

    for sample in samples:
        expected = int(sample["visible_amount_idr"])
        try:
            with Image.open(sample["image_path"]) as source:
                source.verify()
            with Image.open(sample["image_path"]) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                ocr_result = (
                    _run_ocr_with_fallback(image, expected_amount=expected)
                    if ocr_runner is None else ocr_runner(image)
                )
        except Exception as exc:
            raise RuntimeError(f"Could not evaluate sample {sample['sample_id']}: {exc}") from exc

        ocr_text = str(ocr_result.get("text") or "")
        extracted = _extract_amounts(ocr_text)
        amount_regions = _locate_amount_regions(ocr_text, ocr_result.get("words", []))
        transfer_labeled_amounts = [
            region["amount_idr"] for region in amount_regions
            if region["amount_role"] == "transfer_labeled"
        ]
        expected_transfer_candidate_count = sum(
            amount == expected for amount in transfer_labeled_amounts
        )
        amount_role_counts = {
            role: sum(1 for region in amount_regions if region["amount_role"] == role)
            for role in (
                "transfer_labeled", "amount_labeled", "fee_labeled",
                "debit_total_labeled", "balance_labeled", "unclassified",
            )
        }
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
            "layout_id": sample["layout_id"],
            "amount_format_id": sample["amount_format_id"],
            "typography_profile_id": sample["typography_profile_id"],
            "expected_visible_amount_idr": expected,
            "extracted_amounts_idr": extracted,
            "amount_detected": bool(extracted),
            "exact_amount_match": exact_match,
            "unexpected_amount_count": sum(amount != expected for amount in extracted),
            "amount_candidate_count": len(extracted),
            "amount_role_counts": amount_role_counts,
            "transfer_labeled_amounts_idr": transfer_labeled_amounts,
            "expected_in_transfer_label": expected in transfer_labeled_amounts,
            "expected_transfer_labeled_candidate_count": expected_transfer_candidate_count,
            "ocr_available": bool(ocr_result.get("available")),
            "ocr_strategy": str(ocr_result.get("ocr_strategy") or "custom"),
            "confidence": confidence_value,
        })

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_layout: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_amount_format: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_typography: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_layout_typography: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["variant"]].append(record)
        by_layout[record["layout_id"]].append(record)
        by_amount_format[record["amount_format_id"]].append(record)
        by_typography[record["typography_profile_id"]].append(record)
        pair = f"{record['layout_id']}|{record['typography_profile_id']}"
        by_layout_typography[pair].append(record)

    report = {
        "benchmark": "BuktiScope synthetic OCR amount-reading baseline",
        "scope": "synthetic_only",
        "split": split,
        "engine": engine or {"name": "injected test runner"},
        "metrics": summarize(records),
        "ocr_strategy_counts": {
            strategy: sum(1 for record in records if record["ocr_strategy"] == strategy)
            for strategy in sorted({record["ocr_strategy"] for record in records})
        },
        "by_variant": {
            variant: summarize_with_strategies(grouped[variant])
            for variant in sorted(grouped)
        },
        "by_layout": {
            layout: summarize_with_strategies(by_layout[layout])
            for layout in sorted(by_layout)
        },
        "by_amount_format": {
            format_id: summarize_with_strategies(by_amount_format[format_id])
            for format_id in sorted(by_amount_format)
        },
        "by_typography_profile": {
            profile: summarize_with_strategies(by_typography[profile])
            for profile in sorted(by_typography)
        },
        "by_layout_typography": {
            pair: summarize_with_strategies(by_layout_typography[pair])
            for pair in sorted(by_layout_typography)
        },
        "limitations": LIMITATIONS,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sample_fields = [
        "sample_id", "split", "variant", "layout_id", "amount_format_id",
        "typography_profile_id", "expected_visible_amount_idr",
        "extracted_amounts_idr", "amount_detected", "exact_amount_match",
        "unexpected_amount_count", "amount_candidate_count", "amount_role_counts",
        "transfer_labeled_amounts_idr", "expected_in_transfer_label",
        "expected_transfer_labeled_candidate_count",
        "ocr_available", "ocr_strategy", "confidence",
    ]
    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sample_fields)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["extracted_amounts_idr"] = json.dumps(row["extracted_amounts_idr"])
            row["amount_role_counts"] = json.dumps(row["amount_role_counts"])
            row["transfer_labeled_amounts_idr"] = json.dumps(row["transfer_labeled_amounts_idr"])
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
