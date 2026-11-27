from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 1300
FONT_PATHS = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", True),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
    ("C:/Windows/Fonts/arialbd.ttf", True),
    ("C:/Windows/Fonts/arial.ttf", False),
)
FIELDS = {
    "amount": (125, 565, 875, 700),
    "recipient": (125, 800, 875, 900),
    "date": (125, 945, 875, 1045),
}


def load_font(size: int, bold: bool = False):
    candidates = [
        path for path, is_bold in FONT_PATHS if is_bold == bold
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def money(value: int) -> str:
    return "Rp " + f"{value:,}".replace(",", ".")


def save_jpeg(image: Image.Image, path: Path, quality: int = 94) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=quality, optimize=True)


def make_receipt(index: int, rng: random.Random) -> tuple[Image.Image, dict[str, Any]]:
    background = rng.choice(("#f5f7fb", "#f3f6f8", "#f7f6f2"))
    accent = rng.choice(("#243b5a", "#334968", "#263d4f"))
    amount = 250_000 + index * 12_500
    recipient = f"SAMPLE MERCHANT {index:03d}"
    date = "27 NOVEMBER 2026"
    reference = f"DEMO-{index:06d}"

    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (65, 45, 935, 1255),
        radius=24,
        fill="white",
        outline="#dce3ec",
        width=3,
    )
    draw.rounded_rectangle(
        (65, 45, 935, 235),
        radius=24,
        fill=accent,
    )
    draw.rectangle((65, 185, 935, 235), fill=accent)
    draw.text((120, 95), "BUKTISCOPE SYNTHETIC RECEIPT", font=load_font(31, True), fill="white")
    draw.text((120, 155), "TRAINING FIXTURE - NOT A BANK", font=load_font(18, True), fill="#9fe3d9")
    draw.text((125, 295), "TRANSFER SUMMARY", font=load_font(34, True), fill="#1b2c46")
    draw.text((125, 365), "Status contoh", font=load_font(20), fill="#8290a4")
    draw.text((125, 405), "SUCCESS (SIMULATION)", font=load_font(23, True), fill="#18866c")
    draw.line((125, 475, 875, 475), fill="#e3e9f0", width=2)

    draw.text((140, 525), "TOTAL TRANSFER", font=load_font(18, True), fill="#8996a8")
    amount_box = FIELDS["amount"]
    draw.rounded_rectangle(amount_box, radius=12, fill="#f1f4f8")
    draw.text((155, 600), money(amount), font=load_font(52, True), fill="#172943")

    draw.text((125, 760), "RECIPIENT", font=load_font(18, True), fill="#8996a8")
    recipient_box = FIELDS["recipient"]
    draw.rounded_rectangle(recipient_box, radius=12, fill="#f8f9fb")
    draw.text((155, 830), recipient, font=load_font(29, True), fill="#344761")

    draw.text((125, 905), "TRANSFER DATE", font=load_font(18, True), fill="#8996a8")
    date_box = FIELDS["date"]
    draw.rounded_rectangle(date_box, radius=12, fill="#f8f9fb")
    draw.text((155, 975), date, font=load_font(27, True), fill="#344761")

    draw.text((125, 1090), f"REFERENCE: {reference}", font=load_font(19), fill="#65748a")
    draw.rounded_rectangle((125, 1150, 875, 1220), radius=10, fill="#fff4d9", outline="#ead8ac", width=2)
    draw.text((160, 1173), "SYNTHETIC DATA - NO PAYMENT OCCURRED", font=load_font(19, True), fill="#956b24")

    metadata = {
        "amount": amount,
        "recipient": recipient,
        "date": date,
        "reference": reference,
        "boxes": {
            "amount": list(amount_box),
            "recipient": list(recipient_box),
            "date": list(date_box),
        },
    }
    return image, metadata


def replace_field(
    original: Image.Image,
    field: str,
    replacement: str,
) -> tuple[Image.Image, list[int]]:
    image = original.copy()
    draw = ImageDraw.Draw(image)
    box = FIELDS[field]
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=12, fill="#f1f4f8" if field == "amount" else "#f8f9fb")
    if field == "amount":
        font = load_font(52, True)
        text_y = y0 + 35
    elif field == "recipient":
        font = load_font(29, True)
        text_y = y0 + 30
    else:
        font = load_font(27, True)
        text_y = y0 + 28
    draw.text((x0 + 30, text_y), replacement, font=font, fill="#172943" if field == "amount" else "#344761")
    return image, list(box)


def make_benign_export(original: Image.Image) -> Image.Image:
    smaller = original.resize((850, 1105), Image.Resampling.LANCZOS)
    buffer_path = None
    # An in-memory JPEG round-trip models ordinary sharing/export compression.
    import io

    buffer = io.BytesIO()
    smaller.save(buffer, format="JPEG", quality=68, optimize=True)
    buffer.seek(0)
    with Image.open(buffer) as exported:
        return exported.convert("RGB").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)


def build_dataset(output: Path, per_split: int = 10, seed: int = 20261127) -> dict[str, Any]:
    if per_split < 1:
        raise ValueError("per_split must be at least 1")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")

    rng = random.Random(seed)
    split_names = ("train", "validation", "test")
    source_indices = list(range(1, per_split * len(split_names) + 1))
    rng.shuffle(source_indices)
    split_by_index: dict[int, str] = {}
    cursor = 0
    for split in split_names:
        for index in source_indices[cursor:cursor + per_split]:
            split_by_index[index] = split
        cursor += per_split

    rows: list[dict[str, Any]] = []
    for index in sorted(source_indices):
        split = split_by_index[index]
        source_id = f"receipt_{index:05d}"
        base, metadata = make_receipt(index, rng)
        variants: list[tuple[str, Image.Image, str, str | None, list[int] | None, int]] = [
            ("clean", base, "synthetic_unmodified", "none", None, metadata["amount"]),
            ("benign_export", make_benign_export(base), "synthetic_unmodified", "resize_recompress", None, metadata["amount"]),
        ]

        amount_value = metadata["amount"] + 1_000_000
        edited_amount, amount_box = replace_field(base, "amount", money(amount_value))
        variants.append(("edited_amount", edited_amount, "synthetic_edited", "amount_replacement", amount_box, amount_value))

        recipient_value = f"OTHER PAYEE {index:03d}"
        edited_recipient, recipient_box = replace_field(base, "recipient", recipient_value)
        variants.append(("edited_recipient", edited_recipient, "synthetic_edited", "recipient_replacement", recipient_box, metadata["amount"]))

        date_value = "12 NOVEMBER 2026"
        edited_date, date_box = replace_field(base, "date", date_value)
        variants.append(("edited_date", edited_date, "synthetic_edited", "date_replacement", date_box, metadata["amount"]))

        for variant, image, class_label, manipulation, bbox, visible_amount in variants:
            filename = f"{source_id}_{variant}.jpg"
            relative_path = Path("images") / split / filename
            destination = output / relative_path
            save_jpeg(image, destination, quality=94 if variant != "benign_export" else 88)
            rows.append({
                "sample_id": f"{source_id}_{variant}",
                "source_receipt_id": source_id,
                "split": split,
                "path": relative_path.as_posix(),
                "class_label": class_label,
                "variant": variant,
                "manipulation": manipulation,
                "expected_amount_idr": metadata["amount"],
                "visible_amount_idr": visible_amount,
                "expected_recipient": metadata["recipient"],
                "visible_recipient": recipient_value if variant == "edited_recipient" else metadata["recipient"],
                "expected_date": metadata["date"],
                "visible_date": date_value if variant == "edited_date" else metadata["date"],
                "manipulation_bbox_xyxy": json.dumps(bbox) if bbox else "",
                "image_width": IMAGE_WIDTH,
                "image_height": IMAGE_HEIGHT,
                "synthetic_only": True,
            })

    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.csv"
    fieldnames = list(rows[0].keys())
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    labels_path = output / "manifest.jsonl"
    with labels_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "sample_count": len(rows),
        "source_receipts": len(source_indices),
        "per_split_source_receipts": per_split,
        "split_counts": {
            split: sum(1 for row in rows if row["split"] == split)
            for split in split_names
        },
        "class_counts": {
            label: sum(1 for row in rows if row["class_label"] == label)
            for label in ("synthetic_unmodified", "synthetic_edited")
        },
        "seed": seed,
        "synthetic_only": True,
        "limitations": [
            "This is a controlled synthetic dataset, not real bank evidence.",
            "The synthetic layouts do not represent or certify any bank.",
            "The edited variants are simple field replacements and do not cover sophisticated forgeries.",
            "Do not claim real-world fraud accuracy from this dataset alone.",
        ],
    }
    (output / "DATASET_CARD.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a reproducible synthetic receipt dataset.")
    parser.add_argument("--output", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--per-split", type=int, default=10, help="Number of source receipts per split (default: 10).")
    parser.add_argument("--seed", type=int, default=20261127)
    args = parser.parse_args()
    try:
        summary = build_dataset(args.output, per_split=args.per_split, seed=args.seed)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
