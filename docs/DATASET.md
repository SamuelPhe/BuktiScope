# Synthetic dataset lab

## Purpose

The synthetic dataset builder creates controlled receipt-like fixtures for experimentation with OCR, image processing, and manipulation-localization methods. It is not intended to certify a payment, represent a bank, or measure production fraud-detection accuracy.

All images:
- Are generated from code and use fictional sample recipients and references.
- Prominently state that they are synthetic and that no payment occurred.
- Contain no bank logos, real account numbers, real customer data, or real transfer records.

## Build

From the repository root:

```bash
python scripts/build_synthetic_dataset.py --output data/synthetic --per-split 10 --seed 20261127
```

The default creates 30 source receipts and 300 image files (ten variants per source). The destination must not already contain files; the builder refuses to overwrite non-empty directories. Choose another output path for another run. The supported range is 1–100 source receipts per split.

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
| `edited_amount` | `synthetic_edited` | Amount field replaced with a different visible amount. |
| `edited_recipient` | `synthetic_edited` | Recipient field replaced. |
| `edited_date` | `synthetic_edited` | Date field replaced. |

The modifications are intentionally simple and controlled. The quality variants test common image degradation and geometric changes, but do not simulate complete camera pipelines, screen glare, moiré, shadows, messenger-specific processing, or all real-world editing methods. They may be easy for a model to learn as synthetic artifacts.

## Split strategy

Train, validation, and test splits are assigned by source receipt ID before generating variants. Every variant from one source receipt stays in the same split. This prevents near-identical source templates from leaking across splits. The default seed is fixed for reproducibility.

## Files

- `manifest.csv`: one row per image, suitable for spreadsheets and common ML tooling.
- `manifest.jsonl`: equivalent JSON Lines records.
- `DATASET_CARD.json`: summary, split/class counts, seed, and explicit limitations.
- `images/<split>/*.jpg`: generated images.

Each edited sample includes `manipulation_bbox_xyxy`, the affected field region in original-image pixels. The box is a coarse field-level label, not a pixel-accurate edit mask. Every row also includes `quality_transform` and `transform_parameters_json`, which record the image-quality/geometric transformation applied. Transformation parameters are reproducible for the same script version, seed, and split size.

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
