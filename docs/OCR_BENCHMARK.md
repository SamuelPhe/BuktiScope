# Synthetic OCR benchmark

## Purpose

This benchmark measures one narrow capability: whether the current Tesseract OCR pipeline can read the **visible Rupiah amount** in BuktiScope's controlled synthetic receipt images.

It is a reproducible engineering diagnostic, not a fraud classifier and not a test of whether money was received. A high OCR score does not prove that an image is genuine; a low OCR score does not imply fraud.

## Run locally

Install Tesseract with Indonesian and English language data, then generate the synthetic dataset and run:

\`\`\`bash
python scripts/build_synthetic_dataset.py --output data/synthetic --per-split 10 --seed 20261127
python scripts/evaluate_ocr.py --manifest data/synthetic/manifest.csv --split test --output-dir data/ocr-benchmark
\`\`\`

The default evaluates the held-out \`test\` split. Use \`--split all\` only for exploratory checks; do not tune an OCR pipeline against the test split and then present the same result as an independent test.

## Metrics

- **Exact amount match rate:** samples where the expected visible amount appears among OCR-extracted \`Rp\`/\`IDR\` amounts, divided by all evaluated samples.
- **Amount-read coverage rate:** samples where OCR extracts at least one \`Rp\`/\`IDR\` amount, divided by all evaluated samples.
- **Exact match rate when amount detected:** exact matches divided by samples where any amount was detected.
- **Wrong-amount-only samples:** samples where OCR found one or more amounts but did not find the expected visible amount.
- **Unexpected amount candidates:** extracted amount values that differ from the expected visible amount.
- **Mean OCR confidence:** average Tesseract confidence when the engine returned a numeric value. This is not a calibrated probability of correctness.

The report includes aggregate metrics and per-variant breakdowns (\`clean\`, \`benign_export\`, \`edited_amount\`, \`edited_recipient\`, and \`edited_date\`). The manifest's \`visible_amount_idr\` is the target because the benchmark asks what OCR can read in the image as it exists, including deliberately edited variants.

## Output and privacy

The script writes:
- \`summary.json\`: engine details, aggregate metrics, per-variant metrics, and limitations.
- \`samples.csv\`: sample identifier, variant, expected visible amount, extracted amount candidates, match flags, and OCR confidence.

Raw OCR text and image bytes are not copied into the report. The script accepts only manifest rows explicitly marked \`synthetic_only=true\`, validates the selected split, and prevents image paths from escaping the dataset directory.

## GitHub Actions

The **Benchmark synthetic OCR** workflow runs when relevant benchmark code is pushed to \`main\`, or manually from the Actions tab. It regenerates synthetic fixtures, installs Tesseract with Indonesian and English language data, evaluates the selected split (default \`test\`), and uploads a report artifact retained for 14 days.

## Interpretation limits

The synthetic images use a small number of programmatically rendered layouts and simple field replacements. The OCR may perform unusually well on them because the same fonts and layout patterns are repeated. These metrics do not estimate performance on real screenshots, photographs of screens, messaging-app exports, unknown bank layouts, or sophisticated image edits. Real-world evaluation requires a consented, de-identified dataset with documented provenance and a privacy/security review.

BuktiScope cannot confirm settlement or account balance from an image. Payment should be confirmed through an official account transaction history or authorized payment provider.
