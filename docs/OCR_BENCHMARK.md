# Synthetic OCR benchmark

## Purpose

This benchmark measures one narrow capability: whether the current Tesseract OCR pipeline can read the **visible Rupiah amount** in BuktiScope's controlled synthetic receipt images.

It is a reproducible engineering diagnostic, not a fraud classifier and not a test of whether money was received. A high OCR score does not prove that an image is genuine; a low OCR score does not imply fraud.

## Run locally

Install Tesseract with Indonesian and English language data, then generate the synthetic dataset and run:

```bash
python scripts/build_synthetic_dataset.py --output data/synthetic --per-split 10 --seed 20261127
python -m scripts.evaluate_ocr --manifest data/synthetic/manifest.csv --split test --output-dir data/ocr-benchmark
```

The default evaluates the held-out `test` split. Use `--split all` only for exploratory checks; do not tune an OCR pipeline against the test split and then present the same result as an independent test.

## OCR fallback strategy

The application first runs the existing grayscale Tesseract pass with page segmentation mode (PSM) 6. When an expected amount is supplied, the pipeline checks whether that specific value appears among the extracted candidates; finding an unrelated fee or debit total does not stop fallback. If the target is missing, it tries an unsharp-mask PSM 6 pass and then one grayscale PSM 11 sparse-text pass, retaining the first result that contains the expected amount with Tesseract confidence of at least 40. If no target amount is supplied, the original behavior remains: fallback runs only when the primary pass finds no Rupiah amount. If no pass finds the target, the primary result is retained for review.

The API reports the selected method as `ocr_strategy`. Benchmark output includes strategy counts in `summary.json` and a strategy value for each sample in `samples.csv`.

## Metrics

- **Exact amount match rate:** samples where the expected visible amount appears among OCR-extracted `Rp`/`IDR` amounts, divided by all evaluated samples.
- **Amount-read coverage rate:** samples where OCR extracts at least one `Rp`/`IDR` amount, divided by all evaluated samples.
- **Exact match rate when amount detected:** exact matches divided by samples where any amount was detected.
- **Wrong-amount-only samples:** samples where OCR found one or more amounts but did not find the expected visible amount.
- **Unexpected amount candidates:** extracted amount values that differ from the expected visible amount.
- **Samples with unexpected candidates:** number and rate of images where OCR returned at least one non-target monetary value.
- **Expected amount candidate precision:** expected target-amount hits divided by all extracted monetary candidates. A sample with the target amount plus two decoy amounts contributes one expected candidate and two unexpected candidates.
- **Mean OCR confidence:** average Tesseract confidence when the engine returned a numeric value. This is not a calibrated probability of correctness.

The report includes aggregate metrics, per-variant and per-layout breakdowns, breakdowns by amount format and typography profile, and all nine layout/typography cross-groups in each default split. Each grouped section also reports how often each OCR strategy was used. The manifest's `visible_amount_idr` is the transfer-amount target because the benchmark asks what OCR can read in the image as it exists, including deliberately edited variants. The dense-context fixture deliberately includes admin-fee and total-debit values; candidate precision shows whether OCR returns these alongside the target.

## Output and privacy

The script writes:
- `summary.json`: engine details, exact-match/coverage/candidate-precision metrics, per-variant, per-layout, per-format, per-typography and layout/typography cross-group metrics, with OCR strategy counts for each group.
- `samples.csv`: sample identifier, layout, amount format, typography profile, variant, expected visible amount, extracted amount candidates, candidate count, match flags, selected OCR strategy, and OCR confidence.

Raw OCR text and image bytes are not copied into the report. The script accepts only manifest rows explicitly marked `synthetic_only=true`, validates the selected split, and prevents image paths from escaping the dataset directory.

## GitHub Actions

The **Benchmark synthetic OCR** workflow runs when relevant benchmark code is pushed to `main`, or manually from the Actions tab. It regenerates synthetic fixtures, installs Tesseract with Indonesian and English language data, evaluates the selected split (default `test`), and uploads a report artifact retained for 14 days.

## Interpretation limits

The synthetic images use a small number of programmatically rendered layouts, simple field replacements, and controlled image degradation/geometric/capture-condition transforms. The OCR may perform unusually well on them because the same fonts and layout patterns are repeated. These metrics do not estimate performance on real photographs of screens, physical glare/reflections, real display moiré, actual camera sensor pipelines, app-specific exports, unknown bank layouts, or sophisticated image edits. Real-world evaluation requires a consented, de-identified dataset with documented provenance and a privacy/security review.

BuktiScope cannot confirm settlement or account balance from an image. Payment should be confirmed through an official account transaction history or authorized payment provider.
