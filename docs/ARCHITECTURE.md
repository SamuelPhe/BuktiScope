# Architecture notes

## Request flow

1. FastAPI streams raw image bytes into memory, with a 10 MB cap. It avoids multipart upload parsing and its temporary-file spool.
2. Pillow verifies and decodes the image. The decoded format must be JPG, PNG, or WEBP and the image must not exceed 20 megapixels.
3. The analyzer computes SHA-256 and a 64-bit perceptual hash, inspects basic metadata, and checks exact and visually similar images seen during this process session. Perceptual matches use Hamming distance <= 6 and are informational only; they do not increase risk score.
4. Tesseract OCR (optional) receives a prepared in-memory PNG through stdin and returns TSV through stdout; the app does not create OCR image temp files.
5. Parsed IDR amounts and optional recipient text are compared with user-supplied order values.
6. JPEG images receive an ELA visualization. ELA metrics are informational and do not affect the risk score.
7. A transparent heuristic score and a list of findings are returned as JSON. The browser renders the report.

## Data retention

The uploaded image is streamed into request memory only and is not written to an upload file or database by the application. The OCR subprocess receives image bytes over stdin; it does not receive a temp-file path. The SHA-256 digest and perceptual hash are retained in bounded in-memory collections for exact/near-duplicate checking. They are cleared on process shutdown. Reverse proxies, hosting platforms, or process managers may have their own logging or request-retention behavior and must be configured separately.

## Why no ML classifier in v0.1

A classifier trained on a small or poorly sourced dataset could produce confident-looking but misleading results. The MVP therefore starts with deterministic, inspectable checks. A future model needs documented dataset consent/provenance, a held-out test set, bank/device/channel coverage, and published precision, recall, false-positive, and false-negative rates before it can influence decisions.

## Risk model

Points are accumulated from file extension mismatch, editing-software metadata, exact duplicate uploads in the current session, expected-amount mismatch when OCR confidence is sufficient, and expected-recipient text not found in OCR. OCR/metadata absence is not scored as suspicious. ELA is displayed but has no points.
