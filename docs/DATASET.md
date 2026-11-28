# Synthetic dataset lab

## Purpose

The synthetic dataset builder creates controlled receipt-like fixtures for experimentation with OCR, image processing, and manipulation-localization methods. It is not intended to certify a payment, represent a bank, or measure production fraud-detection accuracy.

All images:
- Are generated from code and use fictional sample recipients and references.
- Prominently state that they are synthetic and that no payment occurred.
- Contain no bank logos, real account numbers, real customer data, or real transfer records.

Each source receipt is assigned to one of three fictional layout families. All variants from that source keep the same layout and stay in the same split. The layout IDs are generic design labels; they are not based on, and do not claim compatibility with, any real bank.

## Layout families

| Layout ID | Characteristics |
|---|---|
| `classic_card` | Dark header, rounded card, left-aligned summary and field blocks. |
| `compact_mobile` | Taller rounded mobile-style card, teal header, compact amount placement. |
| `itemized_slip` | Rectangular slip with a side accent strip and lower amount/field placement. |

The builder balances source receipts across layout families within each train, validation, and test split. The manifest records `layout_id` so OCR performance can be compared by layout.

The builder also varies five amount formats (`Rp 250.000`, `Rp250.000`, `Rp 250.000,00`, `IDR 250,000`, and `Rp 250000`) and three typography profiles (standard bold, compact bold, and large regular). Each source receipt keeps one amount format and typography profile across its 18 image variants. In the default ten-source-per-split dataset, every split contains all nine layout × typography combinations. Every amount format appears twice per split, with the two source receipts assigned to different layouts and typography profiles. The dataset card records the cross-counts.

## Build

From the repository root:

```bash
python scripts/build_synthetic_dataset.py --output data/synthetic --per-split 10 --seed 20261127
```

The default creates 30 source receipts and 540 image files (18 variants per source), balanced across three fictional layout families, five amount formats, and three typography profiles. The destination must not already contain files; the builder refuses to overwrite non-empty directories. Choose another output path for another run. The supported range is 1–100 source receipts per split.

## Variants

| Variant | Label | Description |
|---|---|---|
| `clean` | `synthetic_unmodified` | Base synthetic receipt. |
| `benign_export` | `synthetic_unmodified` | Same content resized and JPEG-recompressed to represent a benign export. |
| `blur_light` | `synthetic_unmodified` | Mild Gaussian blur with a deterministic radius. |
| `compression_heavy` | `synthetic_unmodified` | Downscaled, low-quality JPEG recompression, then resized to the source canvas. |
| `crop_resize` | `synthetic_unmodified` | Small, deterministic border crop followed by resizing to the source canvas. |
| `rotate_small` | `synthetic_unmodified` | Small rotation (at most 2.2 degrees) with a neutral fill background. |
| `perspective_warp` | `synthetic_unmodified` | Mild perspective/keystone warp with an unchanged output canvas. |
| `screen_glare` | `synthetic_unmodified` | Soft translucent reflection over part of the amount field. |
| `moire_pattern` | `synthetic_unmodified` | Low-opacity repeating line interference pattern. |
| `camera_noise` | `synthetic_unmodified` | Low-amplitude grain mixed with a slight warm color cast. |
| `edge_shadow` | `synthetic_unmodified` | Soft directional shadow along one image edge. |
| `messenger_export` | `synthetic_unmodified` | Downscale and moderate JPEG recompression followed by rescaling. |
| `amount_small_font` | `synthetic_unmodified` | Amount is redrawn with a small regular 20 px font. |
| `amount_low_contrast` | `synthetic_unmodified` | Amount uses a muted foreground against the light field background. |
| `dense_amount_context` | `synthetic_unmodified` | Small-print admin-fee and total-debit amounts appear below the transfer amount. |
| `edited_amount` | `synthetic_edited` | Amount field replaced with a different visible amount. |
| `edited_recipient` | `synthetic_edited` | Recipient field replaced. |
| `edited_date` | `synthetic_edited` | Date field replaced. |

The modifications are intentionally simple and controlled. Small-font, low-contrast, and dense-context variants are OCR stress fixtures, not image-tampering labels. Dense context intentionally includes other legitimate monetary values so that OCR candidate extraction can be distinguished from identifying the transfer amount. The newer screen/camera variants use overlays and compression approximations; they do not reproduce physical optics, sensor pipelines, display subpixels, real moiré, complex reflections, or app-specific processing exactly. All transformations may be easy for a model to learn as synthetic artifacts.

## Split strategy

Train, validation, and test splits are assigned by source receipt ID before generating variants. Every variant from one source receipt stays in the same split. This prevents near-identical source templates from leaking across splits. The default seed is fixed for reproducibility.

## Files

- `manifest.csv`: one row per image, suitable for spreadsheets and common ML tooling.
- `manifest.jsonl`: equivalent JSON Lines records.
- `DATASET_CARD.json`: summary, split/class counts, seed, and explicit limitations.
- `images/<split>/*.jpg`: generated images.

Each edited sample includes `manipulation_bbox_xyxy`, the affected field region in original-image pixels. The box is a coarse field-level label, not a pixel-accurate edit mask. Every row also includes `layout_id`, `amount_format_id`, `typography_profile_id`, `quality_transform`, and `transform_parameters_json`, which record its display formatting and transformations. Transformation parameters are reproducible for the same script version, seed, and split size.

## Evaluation guidance

1. Keep source receipt groups separated when making any additional split.
2. Report per-class precision, recall, F1, confusion matrix, and false-positive/false-negative counts.
3. Do not use synthetic-only metrics as claims about real bank receipts.
4. For external validation, obtain explicit consent, remove personal data, document provenance, and retain evidence only under an approved privacy/security policy.
5. Do not use this data to label a real person's payment as fraudulent.

## Reproducibility

The generator uses a deterministic random seed. The CSV manifest should be byte-for-byte reproducible for the same script version, seed, and `--per-split` value. Image file bytes can vary if the Pillow/JPEG encoder version changes.


## Generate an artifact on GitHub

Open the repository's **Actions** tab and choose **Build synthetic dataset**, then select **Run workflow**. Enter the source-receipt count per split (1–100) and a seed. The workflow runs the generator and uploads a ZIP artifact retained for seven days. It does not commit generated images to the repository.
