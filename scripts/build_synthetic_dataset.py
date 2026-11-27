from __future__ import annotations

import argparse
import csv
import io
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

# All templates are fictional and intentionally bank-neutral.
LAYOUTS = {
    "classic_card": {
        "fields": FIELDS,
        "accent": "#243b5a",
        "card_radius": 24,
        "style": "classic",
    },
    "compact_mobile": {
        "fields": {
            "amount": (130, 520, 870, 650),
            "recipient": (130, 780, 870, 880),
            "date": (130, 935, 870, 1035),
        },
        "accent": "#176b69",
        "card_radius": 38,
        "style": "compact",
    },
    "itemized_slip": {
        "fields": {
            "amount": (115, 630, 885, 765),
            "recipient": (115, 865, 885, 965),
            "date": (115, 985, 885, 1085),
        },
        "accent": "#5d5943",
        "card_radius": 8,
        "style": "slip",
    },
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


def make_receipt(
    index: int, rng: random.Random, layout_id: str
) -> tuple[Image.Image, dict[str, Any]]:
    layout = LAYOUTS[layout_id]
    fields = layout["fields"]
    background = rng.choice(("#f5f7fb", "#f3f6f8", "#f7f6f2"))
    accent = layout["accent"]
    amount = 250_000 + index * 12_500
    recipient = f"SAMPLE MERCHANT {index:03d}"
    date = "27 NOVEMBER 2026"
    reference = f"DEMO-{index:06d}"

    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), background)
    draw = ImageDraw.Draw(image)

    if layout["style"] == "classic":
        draw.rounded_rectangle(
            (65, 45, 935, 1255), radius=layout["card_radius"],
            fill="white", outline="#dce3ec", width=3,
        )
        draw.rounded_rectangle((65, 45, 935, 235), radius=24, fill=accent)
        draw.rectangle((65, 185, 935, 235), fill=accent)
        draw.text((120, 95), "BUKTISCOPE SYNTHETIC RECEIPT", font=load_font(31, True), fill="white")
        draw.text((120, 155), "TRAINING FIXTURE - NOT A BANK", font=load_font(18, True), fill="#9fe3d9")
        summary_title = "TRANSFER SUMMARY"
    elif layout["style"] == "compact":
        draw.rounded_rectangle(
            (75, 35, 925, 1265), radius=layout["card_radius"],
            fill="white", outline="#d5e2e4", width=4,
        )
        draw.rounded_rectangle((75, 35, 925, 225), radius=layout["card_radius"], fill=accent)
        draw.rectangle((75, 175, 925, 225), fill=accent)
        draw.text((125, 82), "PAYMENT RECEIPT", font=load_font(36, True), fill="white")
        draw.text((125, 145), "DIGITAL TRANSFER - SAMPLE ONLY", font=load_font(19, True), fill="#c8f2ec")
        summary_title = "TRANSACTION DETAILS"
    else:
        draw.rectangle((65, 45, 935, 1255), fill="white", outline="#d4d2c8", width=4)
        draw.rectangle((65, 45, 105, 1255), fill=accent)
        draw.rectangle((105, 45, 935, 205), fill="#f0efe8")
        draw.text((145, 82), "TRANSFER RECEIPT", font=load_font(35, True), fill=accent)
        draw.text((145, 140), "FICTIONAL ITEMIZED SLIP", font=load_font(19, True), fill="#777365")
        summary_title = "PAYMENT INFORMATION"

    if layout["style"] == "compact":
        draw.text((125, 265), summary_title, font=load_font(32, True), fill="#1b2c46")
        draw.text((125, 325), "Status contoh", font=load_font(20), fill="#8290a4")
        draw.text((125, 370), "SUCCESS (SIMULATION)", font=load_font(23, True), fill="#18866c")
    else:
        draw.text((125, 295), summary_title, font=load_font(32, True), fill="#1b2c46")
        draw.text((125, 365), "Status contoh", font=load_font(20), fill="#8290a4")
        draw.text((125, 405), "SUCCESS (SIMULATION)", font=load_font(23, True), fill="#18866c")

    amount_box = fields["amount"]
    recipient_box = fields["recipient"]
    date_box = fields["date"]
    divider_y = amount_box[1] - 90
    draw.line((125, divider_y, 875, divider_y), fill="#e3e9f0", width=2)

    draw.text((amount_box[0] + 15, amount_box[1] - 40), "TOTAL TRANSFER", font=load_font(18, True), fill="#8996a8")
    draw.rounded_rectangle(amount_box, radius=12, fill="#f1f4f8")
    draw.text(
        (amount_box[0] + 30, amount_box[1] + 35),
        money(amount),
        font=load_font(52, True),
        fill="#172943",
    )

    draw.text((recipient_box[0], recipient_box[1] - 40), "RECIPIENT", font=load_font(18, True), fill="#8996a8")
    draw.rounded_rectangle(recipient_box, radius=12, fill="#f8f9fb")
    draw.text(
        (recipient_box[0] + 30, recipient_box[1] + 30),
        recipient,
        font=load_font(29, True),
        fill="#344761",
    )

    draw.text((date_box[0], date_box[1] - 40), "TRANSFER DATE", font=load_font(18, True), fill="#8996a8")
    draw.rounded_rectangle(date_box, radius=12, fill="#f8f9fb")
    draw.text(
        (date_box[0] + 30, date_box[1] + 28),
        date,
        font=load_font(27, True),
        fill="#344761",
    )

    draw.text((125, 1090), f"REFERENCE: {reference}", font=load_font(19), fill="#65748a")
    draw.rounded_rectangle((125, 1150, 875, 1220), radius=10, fill="#fff4d9", outline="#ead8ac", width=2)
    draw.text((160, 1173), "SYNTHETIC DATA - NO PAYMENT OCCURRED", font=load_font(19, True), fill="#956b24")

    metadata = {
        "amount": amount,
        "recipient": recipient,
        "date": date,
        "reference": reference,
        "layout_id": layout_id,
        "boxes": {name: list(box) for name, box in fields.items()},
    }
    return image, metadata

def replace_field(
    original: Image.Image,
    field: str,
    replacement: str,
    field_boxes: dict[str, tuple[int, int, int, int]],
) -> tuple[Image.Image, list[int]]:
    image = original.copy()
    draw = ImageDraw.Draw(image)
    box = field_boxes[field]
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
    # An in-memory JPEG round-trip models ordinary sharing/export compression.
    buffer = io.BytesIO()
    smaller.save(buffer, format="JPEG", quality=68, optimize=True)
    buffer.seek(0)
    with Image.open(buffer) as exported:
        return exported.convert("RGB").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)




def make_blurred(original: Image.Image, rng: random.Random) -> tuple[Image.Image, dict[str, Any]]:
    radius = round(rng.choice((0.8, 1.2, 1.6)), 2)
    return original.filter(ImageFilter.GaussianBlur(radius=radius)), {"radius": radius}


def make_heavy_compression(original: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    reduced_size = (650, 845)
    buffer = io.BytesIO()
    original.resize(reduced_size, Image.Resampling.LANCZOS).save(
        buffer, format="JPEG", quality=32, optimize=True
    )
    buffer.seek(0)
    with Image.open(buffer) as compressed:
        restored = compressed.convert("RGB").resize(
            (IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.BICUBIC
        )
    return restored, {"intermediate_size": list(reduced_size), "jpeg_quality": 32}


def make_crop_resize(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    width, height = original.size
    fraction = rng.choice((0.025, 0.035, 0.045))
    horizontal = max(1, round(width * fraction))
    vertical = max(1, round(height * fraction))
    crop_box = (horizontal, vertical, width - horizontal, height - vertical)
    cropped = original.crop(crop_box).resize(
        (width, height), Image.Resampling.LANCZOS
    )
    return cropped, {
        "crop_box_xyxy": list(crop_box),
        "resized_to": [width, height],
    }


def make_small_rotation(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    angle = round(rng.uniform(-2.2, 2.2), 2)
    rotated = original.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor="#f5f7fb",
    )
    return rotated, {"angle_degrees": angle, "expand": False}


def make_screen_glare(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    """Add a soft, translucent reflection across part of the amount field."""
    width, height = original.size
    center_x = rng.randint(360, 650)
    center_y = rng.randint(585, 665)
    radius_x = rng.randint(150, 240)
    radius_y = rng.randint(55, 105)
    opacity = rng.randint(38, 62)
    blur_radius = rng.randint(24, 42)

    overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse(
        (
            center_x - radius_x,
            center_y - radius_y,
            center_x + radius_x,
            center_y + radius_y,
        ),
        fill=(255, 255, 255, opacity),
    )
    draw.ellipse(
        (
            center_x - radius_x // 2,
            center_y - radius_y // 2,
            center_x + radius_x // 2,
            center_y + radius_y // 2,
        ),
        fill=(255, 255, 255, min(85, opacity + 18)),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    reflected = Image.alpha_composite(original.convert("RGBA"), overlay).convert("RGB")
    return reflected, {
        "center_xy": [center_x, center_y],
        "ellipse_radii": [radius_x, radius_y],
        "opacity": opacity,
        "blur_radius": blur_radius,
    }


def make_moire_pattern(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    """Overlay a faint repeating line pattern similar to screen/camera interference."""
    width, height = original.size
    spacing = rng.choice((9, 11, 13))
    opacity = rng.randint(14, 24)
    overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for offset in range(-height, width + height, spacing):
        draw.line(
            (offset, 0, offset + height, height),
            fill=(34, 68, 108, opacity),
            width=1,
        )
    for y in range(0, height, spacing * 3):
        draw.line(
            (0, y, width, y),
            fill=(80, 92, 112, max(8, opacity // 2)),
            width=1,
        )

    patterned = Image.alpha_composite(original.convert("RGBA"), overlay).convert("RGB")
    return patterned, {"line_spacing_px": spacing, "line_opacity": opacity}


def make_camera_noise(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    """Add deterministic, low-amplitude sensor-like speckles and a slight color cast."""
    width, height = original.size
    sigma = rng.choice((16, 20, 24))
    speckle_count = 24_000
    alpha_min = max(6, sigma // 3)
    alpha_max = max(alpha_min + 1, sigma // 2)

    # Draw a sparse high/low pixel-noise layer with the dataset's seeded RNG.
    # Unlike Pillow's effect_noise(), this stays reproducible for a fixed seed.
    noise_overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
    noise_draw = ImageDraw.Draw(noise_overlay)
    for _ in range(speckle_count):
        x = rng.randrange(width)
        y = rng.randrange(height)
        value = rng.choice((0, 255))
        alpha = rng.randint(alpha_min, alpha_max)
        noise_draw.point((x, y), fill=(value, value, value, alpha))
    noisy = Image.alpha_composite(original.convert("RGBA"), noise_overlay).convert("RGB")

    tint_alpha = rng.randint(4, 9)
    tint = Image.new("RGBA", original.size, (255, 238, 220, tint_alpha))
    noisy = Image.alpha_composite(noisy.convert("RGBA"), tint).convert("RGB")
    return noisy, {
        "noise_sigma": sigma,
        "speckle_count": speckle_count,
        "speckle_alpha_range": [alpha_min, alpha_max],
        "warm_tint_alpha": tint_alpha,
    }


def make_edge_shadow(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    """Add a soft directional shadow along one edge of a photographed screen."""
    width, height = original.size
    side = rng.choice(("left", "right"))
    depth = rng.randint(230, 360)
    opacity = rng.randint(42, 72)
    blur_radius = rng.randint(28, 46)

    mask = Image.new("L", original.size, 0)
    draw = ImageDraw.Draw(mask)
    if side == "left":
        polygon = [(0, 0), (depth, 0), (depth + 85, height), (0, height)]
    else:
        polygon = [
            (width - depth, 0),
            (width, 0),
            (width, height),
            (width - depth - 85, height),
        ]
    draw.polygon(polygon, fill=opacity)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
    overlay.putalpha(mask)
    shadowed = Image.alpha_composite(original.convert("RGBA"), overlay).convert("RGB")
    return shadowed, {
        "side": side,
        "depth_px": depth,
        "opacity": opacity,
        "blur_radius": blur_radius,
    }


def make_messenger_export(
    original: Image.Image
) -> tuple[Image.Image, dict[str, Any]]:
    """Model a moderate downscale/JPEG recompression/rescale sharing path."""
    intermediate_size = (720, 936)
    quality = 52
    buffer = io.BytesIO()
    original.resize(intermediate_size, Image.Resampling.LANCZOS).save(
        buffer, format="JPEG", quality=quality, optimize=True
    )
    buffer.seek(0)
    with Image.open(buffer) as shared:
        restored = shared.convert("RGB").resize(
            original.size, Image.Resampling.BICUBIC
        )
    return restored, {
        "intermediate_size": list(intermediate_size),
        "jpeg_quality": quality,
        "restored_size": list(original.size),
    }


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense system with Gaussian elimination and pivoting."""
    size = len(vector)
    augmented = [
        [float(value) for value in row] + [float(vector[index])]
        for index, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("Perspective transform points are degenerate")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    current - factor * pivot_value
                    for current, pivot_value in zip(augmented[row], augmented[column])
                ]
    return [augmented[row][-1] for row in range(size)]


def make_perspective_warp(
    original: Image.Image, rng: random.Random
) -> tuple[Image.Image, dict[str, Any]]:
    """Apply a mild keystone warp while keeping the image canvas size unchanged."""
    width, height = original.size
    inset = {
        "top_left_x": rng.randint(12, 24),
        "top_left_y": rng.randint(6, 16),
        "top_right_x": rng.randint(12, 24),
        "top_right_y": rng.randint(4, 14),
        "bottom_right_x": rng.randint(6, 18),
        "bottom_right_y": rng.randint(12, 24),
        "bottom_left_x": rng.randint(6, 18),
        "bottom_left_y": rng.randint(12, 24),
    }
    destination_to_source = [
        (0.0, 0.0, float(inset["top_left_x"]), float(inset["top_left_y"])),
        (float(width - 1), 0.0, float(width - 1 - inset["top_right_x"]), float(inset["top_right_y"])),
        (
            float(width - 1),
            float(height - 1),
            float(width - 1 - inset["bottom_right_x"]),
            float(height - 1 - inset["bottom_right_y"]),
        ),
        (0.0, float(height - 1), float(inset["bottom_left_x"]), float(height - 1 - inset["bottom_left_y"])),
    ]

    matrix: list[list[float]] = []
    values: list[float] = []
    for x, y, source_x, source_y in destination_to_source:
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -source_x * x, -source_x * y])
        values.append(source_x)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -source_y * x, -source_y * y])
        values.append(source_y)

    coefficients = _solve_linear_system(matrix, values)
    warped = original.transform(
        (width, height),
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor="#f5f7fb",
    )
    return warped, inset


def build_dataset(output: Path, per_split: int = 10, seed: int = 20261127) -> dict[str, Any]:
    if per_split < 1 or per_split > 100:
        raise ValueError("per_split must be between 1 and 100")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")

    rng = random.Random(seed)
    split_names = ("train", "validation", "test")
    source_indices = list(range(1, per_split * len(split_names) + 1))
    rng.shuffle(source_indices)
    split_by_index: dict[int, str] = {}
    layout_by_index: dict[int, str] = {}
    layout_names = tuple(LAYOUTS)
    cursor = 0
    for split in split_names:
        split_indices = source_indices[cursor:cursor + per_split]
        for index in split_indices:
            split_by_index[index] = split
            layout_by_index[index] = layout_names[(index - 1) % len(layout_names)]
        cursor += per_split

    rows: list[dict[str, Any]] = []
    for index in sorted(source_indices):
        split = split_by_index[index]
        source_id = f"receipt_{index:05d}"
        layout_id = layout_by_index[index]
        base, metadata = make_receipt(index, rng, layout_id)
        field_boxes = {
            name: tuple(box)
            for name, box in metadata["boxes"].items()
        }
        variants: list[
            tuple[str, Image.Image, str, str, list[int] | None, int, str, dict[str, Any]]
        ] = [
            ("clean", base, "synthetic_unmodified", "none", None, metadata["amount"], "none", {}),
            (
                "benign_export", make_benign_export(base), "synthetic_unmodified",
                "resize_recompress", None, metadata["amount"], "resize_recompress",
                {"scale": 0.85, "intermediate_jpeg_quality": 68},
            ),
        ]

        amount_value = metadata["amount"] + 1_000_000
        edited_amount, amount_box = replace_field(base, "amount", money(amount_value), field_boxes)
        variants.append((
            "edited_amount", edited_amount, "synthetic_edited",
            "amount_replacement", amount_box, amount_value, "none", {},
        ))

        recipient_value = f"OTHER PAYEE {index:03d}"
        edited_recipient, recipient_box = replace_field(base, "recipient", recipient_value, field_boxes)
        variants.append((
            "edited_recipient", edited_recipient, "synthetic_edited",
            "recipient_replacement", recipient_box, metadata["amount"], "none", {},
        ))

        date_value = "12 NOVEMBER 2026"
        edited_date, date_box = replace_field(base, "date", date_value, field_boxes)
        variants.append((
            "edited_date", edited_date, "synthetic_edited",
            "date_replacement", date_box, metadata["amount"], "none", {},
        ))

        blurred, blur_parameters = make_blurred(base, rng)
        variants.append((
            "blur_light", blurred, "synthetic_unmodified", "none", None,
            metadata["amount"], "gaussian_blur", blur_parameters,
        ))

        compressed, compression_parameters = make_heavy_compression(base)
        variants.append((
            "compression_heavy", compressed, "synthetic_unmodified", "none", None,
            metadata["amount"], "low_quality_jpeg", compression_parameters,
        ))

        cropped, crop_parameters = make_crop_resize(base, rng)
        variants.append((
            "crop_resize", cropped, "synthetic_unmodified", "none", None,
            metadata["amount"], "crop_resize", crop_parameters,
        ))

        rotated, rotation_parameters = make_small_rotation(base, rng)
        variants.append((
            "rotate_small", rotated, "synthetic_unmodified", "none", None,
            metadata["amount"], "small_rotation", rotation_parameters,
        ))

        perspective, perspective_parameters = make_perspective_warp(base, rng)
        variants.append((
            "perspective_warp", perspective, "synthetic_unmodified", "none", None,
            metadata["amount"], "perspective_warp", perspective_parameters,
        ))

        glare, glare_parameters = make_screen_glare(base, rng)
        variants.append((
            "screen_glare", glare, "synthetic_unmodified", "none", None,
            metadata["amount"], "screen_glare", glare_parameters,
        ))

        moire, moire_parameters = make_moire_pattern(base, rng)
        variants.append((
            "moire_pattern", moire, "synthetic_unmodified", "none", None,
            metadata["amount"], "moire_pattern", moire_parameters,
        ))

        camera_noise, camera_parameters = make_camera_noise(base, rng)
        variants.append((
            "camera_noise", camera_noise, "synthetic_unmodified", "none", None,
            metadata["amount"], "camera_noise", camera_parameters,
        ))

        shadow, shadow_parameters = make_edge_shadow(base, rng)
        variants.append((
            "edge_shadow", shadow, "synthetic_unmodified", "none", None,
            metadata["amount"], "edge_shadow", shadow_parameters,
        ))

        messenger, messenger_parameters = make_messenger_export(base)
        variants.append((
            "messenger_export", messenger, "synthetic_unmodified", "none", None,
            metadata["amount"], "messenger_jpeg_export", messenger_parameters,
        ))

        for (
            variant, image, class_label, manipulation, bbox, visible_amount,
            quality_transform, transform_parameters,
        ) in variants:
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
                "layout_id": layout_id,
                "manipulation": manipulation,
                "quality_transform": quality_transform,
                "transform_parameters_json": json.dumps(transform_parameters, sort_keys=True),
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
        "variant_counts": {
            variant: sum(1 for row in rows if row["variant"] == variant)
            for variant in sorted({row["variant"] for row in rows})
        },
        "variants_per_source_receipt": len(variants),
        "layout_counts": {
            layout: sum(1 for row in rows if row["layout_id"] == layout)
            for layout in LAYOUTS
        },
        "layout_counts_by_split": {
            split: {
                layout: sum(
                    1 for row in rows
                    if row["split"] == split and row["layout_id"] == layout
                )
                for layout in LAYOUTS
            }
            for split in split_names
        },
        "seed": seed,
        "synthetic_only": True,
        "limitations": [
            "This is a controlled synthetic dataset, not real bank evidence.",
            "The three fictional layout families do not represent or certify any bank.",
            "The edited variants are simple field replacements and do not cover sophisticated forgeries.",
            "Quality variants are controlled transformations, not complete simulations of real cameras, screens, or messaging apps.",
            "Screen glare, moiré, shadows, and camera noise are synthetic overlays, not complete physical camera/screen simulations.",
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
