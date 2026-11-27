# BuktiScope

**Local-first, explainable screening for Indonesian transfer-evidence images.**

BuktiScope inspects a JPG, PNG, or WEBP image and reports signals that may deserve human review. The MVP combines optional Tesseract OCR, image metadata inspection, exact-file duplicate detection within the running process, optional order-field matching, and a JPEG Error Level Analysis (ELA) visualization.

> **Important:** BuktiScope does not verify that money was received. A low score is not proof that a receipt is genuine, and a high score is not proof of fraud. Confirm payment through the account's official transaction history or an authorized payment provider.

## Why this project exists

Edited transfer screenshots are a real operational problem, but image-only detection has hard limits. A screenshot can be edited and re-encoded to hide obvious traces; a genuine screenshot can also be resized, compressed by a messaging app, or exported by an editor. BuktiScope therefore favors **explainable signals and human review** over a black-box real/fake prediction.

This project does not claim to be the first tool of its kind. Its intended contribution is a privacy-aware, Indonesian-friendly, auditable starting point with clear limitations, synthetic examples, tests, and a small local API.

## MVP capabilities

- Accepts JPG, PNG, and WEBP; checks the decoded image format rather than trusting the filename.
- Limits image requests to 10 MB and decoded images to 20 megapixels.
- Reads visible text with Tesseract OCR when installed, preferring Indonesian (`ind`) and English (`eng`) language data.
- When the default OCR pass finds no Rupiah amount, retries with an unsharp-mask pass and then Tesseract sparse-text mode (PSM 11). These fallbacks run only when needed; the selected OCR strategy is reported.
- Extracts visible `Rp`/`IDR` amounts from OCR output and maps detected amount words to their original-image pixel coordinates when OCR word boxes are available. The UI can show a marked preview; it is only an OCR location hint.
- Optionally compares OCR text with an expected order amount and recipient name. This is text matching, not account verification.
- Inspects available EXIF/basic metadata and treats editing-software metadata as a weak signal only.
- Identifies byte-identical images already analyzed during the current process using SHA-256, and can flag visually similar exports using a perceptual hash (pHash). Similarity is informational and does not add risk points. It does not retain image contents.
- Displays an ELA heatmap for JPEG files with up to three relative high-difference tiles as a navigation aid. The hotspot overlay does not add points to the risk score and does not identify tampered regions with certainty.
- Shows a transparent, rule-based risk score and a reason for each scored signal.
- Processes request image bytes in memory; it does not save uploaded evidence to an upload directory or database.

## Not included yet

- No trained fraud-classification model and no validated accuracy claim.
- No bank-specific template certification or claim that all Indonesian banks are supported.
- No connection to bank accounts, BI-SNAP, payment gateways, or transaction ledgers.
- No proof that a payment settled, account ownership verification, or guarantee against sophisticated edits.
- No persistent history; duplicate detection resets when the app process restarts.

## Requirements

- Python 3.11 or newer.
- Tesseract OCR is optional. Install Tesseract with Indonesian (`ind`) and English (`eng`) language data for OCR support.
- Without Tesseract, image format checks, metadata inspection, duplicate detection, and JPEG ELA remain available.

## Run on Windows

The easiest option is to double-click `start-windows.bat`. It creates a virtual environment, installs runtime packages, starts the local server, and opens the browser. An internet connection is needed on first run to install Python packages.

Manual PowerShell setup:

```powershell
git clone https://github.com/SamuelPhe/BuktiScope.git
cd BuktiScope
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

If PowerShell blocks environment activation, run this once in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If Tesseract is installed but not on `PATH`, set `TESSERACT_CMD` to the full executable path before starting the app:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
python -m uvicorn app.main:app --reload
```

## Run on macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Run tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

GitHub Actions runs the test suite on Python 3.11 and 3.12 for pushes and pull requests.

## Build a labeled synthetic dataset

Generate grouped train/validation/test fixtures (default: 300 images):

```bash
python scripts/build_synthetic_dataset.py --output data/synthetic --per-split 10 --seed 20261127
```

The builder creates clean and benign-export images, five additional quality/geometric variants (blur, heavy compression, crop/resize, small rotation, and perspective warp), and simple edited amount/recipient/date variants. Source receipt groups never cross splits. Every fixture says synthetic/no payment occurred; the data card documents limitations. Generated files under `data/synthetic/` are git-ignored. You can also generate and download the dataset from GitHub Actions → Build synthetic dataset. The workflow caps each split at 100 source receipts. See [docs/DATASET.md](docs/DATASET.md).

## Evaluate OCR on synthetic data

A reproducible benchmark measures whether Tesseract reads the visible Rupiah amount in each synthetic image. It defaults to the held-out test split:

```bash
python -m scripts.evaluate_ocr --manifest data/synthetic/manifest.csv --split test --output-dir data/ocr-benchmark
```

The report contains exact visible-amount match rate, amount-read coverage, confidence summaries, and per-variant breakdowns. It does not measure fraud-detection accuracy or payment authenticity. The benchmark accepts only rows marked `synthetic_only=true`, and it does not include raw OCR text in its output. See [docs/OCR_BENCHMARK.md](docs/OCR_BENCHMARK.md). A GitHub Actions workflow can generate the dataset, run the benchmark, and upload the report artifact.


## Generate synthetic demo images

```bash
python scripts/generate_demo_data.py
```

This creates `demo-data/synthetic-clean.jpg` and `demo-data/synthetic-edited.jpg`. Both carry prominent synthetic/demo markings and do not represent a real bank or payment. The second has a visibly changed amount for a simple demonstration. These fixtures are illustrative and are **not** a validated fraud-detection benchmark.

## Risk score (MVP heuristic)

| Signal | Points | Interpretation |
|---|---:|---|
| File extension does not match decoded format | +20 | The file may have been renamed or exported unusually. |
| Editing-software name in metadata | +12 | Weak context only; editing software can be used legitimately. |
| Exact same bytes already analyzed in this process | +35 | May be a harmless resend or attempted duplicate. |
| Expected amount not found in sufficiently confident OCR output | +25 | OCR can misread numbers; verify manually. |
| Expected recipient text not found by OCR | +10 | OCR can miss or misread the recipient's name. |

Visually similar exports are reported as an informational finding using a 64-bit pHash with a Hamming-distance threshold of 6; they do not affect the score. Similar-looking bank templates can produce false matches, so treat this as a review hint only. Risk bands: `0–19` low image-screening risk, `20–49` review, and `50–100` high image-screening risk. These are heuristic labels, not calibrated probabilities. Missing metadata, absent ELA patterns, or successful OCR matching do not make an image authentic.

## API

`POST /api/analyze` accepts raw image bytes as the request body (not multipart form data), with `Content-Type: image/jpeg`, `image/png`, or `image/webp`. Optional headers:

- `X-File-Name`: display name for the file.
- `X-Expected-Amount`: integer IDR amount, such as `250000`.
- `X-Expected-Recipient`: URL-encoded recipient text.

The request body is streamed with a 10 MB limit to avoid multipart temporary-file spooling. `GET /api/health` returns a health response.

## Privacy and safe use

- Uploaded images and OCR text are not stored by the application.
- The SHA-256 digest is kept in a bounded in-memory set for duplicate checks and cleared when the app stops.
- Run this on a trusted machine. Do not expose the development server to a public network without authentication, rate limiting, deployment hardening, and a privacy review.
- Do not upload unredacted customer evidence to public issues, pull requests, test fixtures, or public datasets.
- Synthetic data is preferred for contributions and automated tests.

## Development principles

1. Never label a receipt genuine solely from an image.
2. Do not turn OCR failure into a fraud finding.
3. Explain every scored signal and keep its limitations visible.
4. Keep image processing local by default and avoid unnecessary retention.
5. Evaluate false positives and false negatives before adding model-based decisions.

## Roadmap

- [x] Local upload and file validation.
- [x] Indonesian/English OCR integration when installed locally, including amount-region coordinate mapping and a marked preview.
- [x] EXIF metadata review and JPEG ELA visualization.
- [x] Exact and perceptual near-duplicate screening within the current process session.
- [x] Relative JPEG ELA hotspot regions for human review (informational only).
- [x] Order amount/recipient text comparison.
- [x] Explainable scoring, API, tests, and synthetic example generator.
- [x] Reproducible synthetic dataset builder with grouped train/validation/test splits and field-level edit labels.
- [ ] Curated, consented, de-identified real-world evaluation dataset with documented provenance.
- [ ] Bank-template parsing with explicit coverage tests and versioned examples.
- [ ] Localization of suspicious regions and human-review annotations.
- [ ] Calibrated model evaluation with per-class precision/recall and false-positive analysis.
- [ ] Optional official transaction verification through an authorized provider integration.

## License

MIT. See [LICENSE](LICENSE).

## Disclaimer

BuktiScope is experimental software, not a bank service, payment processor, fraud guarantee, or legal/financial determination. Use it as one aid in a broader payment-verification process.
