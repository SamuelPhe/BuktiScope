# BuktiScope — AI Coding Instructions

## Project context
- BuktiScope is a local-first, explainable screening tool for Indonesian transfer-evidence images.
- The current application uses Python and FastAPI, with optional Tesseract OCR and image-processing features.
- Preserve the existing MVP scope, architecture, dependencies, and documented limitations.

## Working principles
- Make the smallest complete change that solves the requested problem.
- Prefer existing functions, modules, standard-library features, and installed dependencies before adding new abstractions or packages.
- Avoid overengineering, speculative features, unnecessary configuration, and duplicated logic.
- Keep code readable rather than minimizing line count at all costs.
- Add concise comments for non-obvious logic, image-processing assumptions, scoring decisions, and important limitations. Do not comment every obvious line.
- Use clear names and explain root causes when fixing bugs.

## Safety, privacy, and product claims
- Never claim that image analysis proves a transfer happened, verifies a bank balance, or establishes that a receipt is genuine or fraudulent.
- A risk score is a heuristic screening signal, not a probability or validated fraud-detection accuracy metric.
- Preserve the human-review workflow and the instruction to confirm payment using an official account transaction history or authorized payment provider.
- Keep uploaded image bytes in memory unless the user explicitly requests a reviewed design change. Do not add persistent evidence storage, telemetry, or external image uploads without explicit approval.
- Do not log raw uploaded images, OCR contents, recipient details, or other sensitive evidence data unnecessarily.
- Treat filenames, EXIF metadata, OCR output, and image contents as untrusted input.

## Image and OCR handling
- Preserve decoded-format validation, upload-size limits, decoded-pixel limits, and safe error handling.
- Do not trust file extensions or client-supplied metadata as proof of actual image format.
- Keep OCR optional and handle missing Tesseract/language data gracefully.
- Clearly distinguish OCR text matching from payment verification.
- Keep ELA and perceptual-hash outputs as visual/informational hints; do not imply they identify tampering with certainty.
- Avoid making heuristic scoring more confident without a documented rationale and representative evaluation.

## Testing and datasets
- Use synthetic fixtures for tests, demos, and benchmarks. Do not use real payment evidence as test data unless explicitly authorized and safely anonymized.
- Add focused tests for parsing, upload limits, malformed images, OCR fallbacks, scoring, and privacy-sensitive behavior when relevant.
- Preserve dataset split isolation and synthetic-only safeguards in benchmark scripts.
- Never describe synthetic OCR benchmark results as fraud-detection accuracy.

## Verification and reporting
- Inspect relevant code, tests, and documentation before editing.
- Run the narrowest relevant tests, then broader checks when the change warrants them.
- Do not claim tests or checks passed unless they were executed and their results observed.
- Report what changed, what was tested, what was skipped, and any remaining limitations.
- Explain technical changes in understandable Indonesian.

## Scope discipline
- Do not add machine-learning classification, bank integrations, transaction verification, persistent history, or other excluded capabilities unless explicitly requested.
- For small tasks, implement directly. For complex tasks, use a short plan and keep it proportional to the risk.
