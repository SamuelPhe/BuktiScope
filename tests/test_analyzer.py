from __future__ import annotations

import io

import pytest
from PIL import Image, PngImagePlugin

from app import analyzer as analyzer_module
from app.analyzer import AnalysisError, Analyzer, _extract_amounts, _parse_idr_number


def png_bytes(text: str | None = None) -> bytes:
    image = Image.new("RGB", (720, 960), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 55, 665, 905), outline="#d7dce5", width=3)
    draw.text((90, 110), "BUKTISCOPE DEMO", fill="#17243a")
    draw.text((90, 180), "BUKTI TRANSFER - DATA SINTETIS", fill="#17243a")
    if text:
        draw.text((90, 300), text, fill="#17243a")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_extracts_indonesian_rupiah_amounts():
    assert _extract_amounts("Total transfer Rp 250.000 dan biaya Rp 2.500") == [250000, 2500]
    assert _parse_idr_number("1.250.000") == 1250000
    assert _parse_idr_number("250,000") == 250000


def test_invalid_image_is_rejected():
    with pytest.raises(AnalysisError, match="gambar yang valid"):
        Analyzer.create().analyze(b"not an image", "receipt.png")


def test_unsupported_image_format_is_rejected():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="BMP")
    with pytest.raises(AnalysisError, match="Format tidak didukung"):
        Analyzer.create().analyze(buffer.getvalue(), "receipt.bmp")


def test_extension_mismatch_is_reported():
    result = Analyzer.create().analyze(png_bytes(), "receipt.jpg")
    assert any(item["code"] == "extension_mismatch" for item in result["findings"])
    assert result["risk_score"] == 20
    assert result["status"] == "review"


def test_identical_file_is_reported_as_session_duplicate():
    instance = Analyzer.create()
    raw = png_bytes()
    first = instance.analyze(raw, "first.png")
    second = instance.analyze(raw, "second.png")
    assert first["image"]["duplicate_in_session"] is False
    assert second["image"]["duplicate_in_session"] is True
    assert any(item["code"] == "duplicate_upload" for item in second["findings"])


def test_expected_amount_mismatch_is_explained(monkeypatch):
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image: {
        "available": True, "language": "ind+eng", "text": "TRANSFER BERHASIL Rp 250.000",
        "confidence": 92.0,
    })
    result = Analyzer.create().analyze(png_bytes(), "receipt.png", expected_amount=500000)
    assert result["comparison"]["amount_match"] is False
    finding = next(item for item in result["findings"] if item["code"] == "amount_mismatch")
    assert finding["points"] == 25
    assert "OCR" in finding["detail"]


def test_expected_amount_match_is_not_called_bank_verification(monkeypatch):
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image: {
        "available": True, "language": "ind+eng", "text": "TRANSFER BERHASIL Rp 250.000",
        "confidence": 92.0,
    })
    result = Analyzer.create().analyze(png_bytes(), "receipt.png", expected_amount=250000)
    assert result["comparison"]["amount_match"] is True
    assert result["risk_score"] == 0
    assert "bukan bukti" in result["disclaimer"]


def test_metadata_is_reported_without_assuming_authenticity():
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "Example Editor")
    image = Image.new("RGB", (80, 80), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    result = Analyzer.create().analyze(buffer.getvalue(), "metadata.png")
    assert result["image"]["metadata"]["software"] == "Example Editor"
    assert not any(item["code"] == "editing_software_metadata" for item in result["findings"])


def test_upload_limit_is_enforced():
    with pytest.raises(AnalysisError, match="10 MB"):
        Analyzer.create().analyze(b"x" * (10 * 1024 * 1024 + 1), "large.png")
