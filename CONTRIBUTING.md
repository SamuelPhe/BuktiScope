# Contributing to BuktiScope

Thanks for considering a contribution.

## Principles

- Do not claim that an image alone proves a payment settled.
- Keep every scored signal explainable and document its limitations.
- Do not treat absent metadata, OCR failure, or ELA brightness as proof of fraud.
- Prefer synthetic fixtures or properly consented, de-identified evidence.
- Never commit unredacted customer receipts, account details, tokens, or private keys.

## Development setup

Python 3.11+ is required. Create a virtual environment, install `requirements-dev.txt`, then run `python -m pytest`.

## Pull requests

Include a clear problem statement, implementation notes, test coverage, and known limitations. Add regression tests for changed analyzer behavior. Keep screenshots and sample receipts visibly marked as synthetic.
