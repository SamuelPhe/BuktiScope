from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, PngImagePlugin

from app import analyzer as analyzer_module
from app.analyzer import AnalysisError, Analyzer, _extract_amounts, _parse_idr_number
from app.perceptual import hamming_distance, perceptual_hash


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


def jpeg_variant(raw: bytes, quality: int, size: tuple[int, int] | None = None) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    if size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def test_perceptual_hash_survives_recompression_and_resize():
    raw = png_bytes("TRANSFER BERHASIL Rp 250.000")
    first = jpeg_variant(raw, quality=95)
    second = jpeg_variant(raw, quality=55, size=(640, 853))
    first_hash = perceptual_hash(Image.open(io.BytesIO(first)))
    second_hash = perceptual_hash(Image.open(io.BytesIO(second)))

    assert first_hash is not None
    assert second_hash is not None
    assert hamming_distance(first_hash, second_hash) <= 6


def test_near_duplicate_is_informational_and_does_not_increase_risk(monkeypatch):
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image: {
        "available": False, "language": None, "text": "", "confidence": None,
    })
    instance = Analyzer.create()
    raw = png_bytes("TRANSFER BERHASIL Rp 250.000")
    first = jpeg_variant(raw, quality=95)
    second = jpeg_variant(raw, quality=55, size=(640, 853))

    first_result = instance.analyze(first, "first.jpg")
    second_result = instance.analyze(second, "second.jpg")

    assert first_result["image"]["duplicate_in_session"] is False
    assert second_result["image"]["duplicate_in_session"] is False
    assert second_result["image"]["similar_in_session"] is not None
    assert second_result["risk_score"] == 0
    finding = next(item for item in second_result["findings"] if item["code"] == "near_duplicate_upload")
    assert finding["points"] == 0
    assert finding["severity"] == "info"


def test_uniform_images_skip_perceptual_hash():
    image = Image.new("RGB", (64, 64), "white")
    assert perceptual_hash(image) is None


def jpeg_bytes_with_local_texture() -> bytes:
    from PIL import ImageDraw
    import random

    image = Image.new("RGB", (960, 960), "#f7f7f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 910, 910), outline="#b0b0b0", width=3)
    draw.text((100, 120), "BUKTISCOPE DEMO - SAMPLE TRANSFER", fill="#202020")
    draw.text((100, 220), "Rp 250.000", fill="#202020")
    randomizer = random.Random(42)
    noise = Image.new("RGB", (220, 220), "white")
    noise_pixels = noise.load()
    for y in range(noise.height):
        for x in range(noise.width):
            value = randomizer.randrange(80, 176)
            noise_pixels[x, y] = (value, value, value)
    image.paste(noise, (600, 600))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=98)
    return buffer.getvalue()


def test_ela_returns_bounded_regions_and_overlay():
    result = Analyzer.create().analyze(jpeg_bytes_with_local_texture(), "texture.jpg")
    ela = result["ela"]

    assert ela is not None
    assert ela["available"] is True
    assert len(ela["hotspots"]) <= 3
    assert ela["preview_data_url"].startswith("data:image/png;base64,")
    preview_bytes = base64.b64decode(ela["preview_data_url"].split(",", 1)[1])
    preview = Image.open(io.BytesIO(preview_bytes))
    assert preview.mode == "RGB"
    assert max(preview.size) <= 650
    for region in ela["hotspots"]:
        assert 0 <= region["x"] < result["image"]["width"]
        assert 0 <= region["y"] < result["image"]["height"]
        assert region["width"] > 0
        assert region["height"] > 0
        assert region["x"] + region["width"] <= result["image"]["width"]
        assert region["y"] + region["height"] <= result["image"]["height"]


def test_ela_hotspots_are_informational_and_do_not_change_risk():
    result = Analyzer.create().analyze(jpeg_bytes_with_local_texture(), "texture.jpg")
    assert result["risk_score"] == 0
    assert all(item["points"] == 0 for item in result["findings"] if item["code"] == "ela_preview")


def test_png_does_not_claim_to_have_ela_hotspots():
    result = Analyzer.create().analyze(png_bytes(), "receipt.png")
    assert result["ela"] is None
