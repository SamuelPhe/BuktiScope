from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, PngImagePlugin

from app import analyzer as analyzer_module
from app.analyzer import AnalysisError, Analyzer, _extract_amounts, _parse_idr_number, _run_ocr_with_fallback
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


@pytest.mark.parametrize(
    "text",
    [
        "Total Rp 250.000",
        "Total Rp250.000",
        "Total Rp 250.000,00",
        "Total IDR 250,000",
        "Total Rp 250000",
    ],
)
def test_extracts_supported_rupiah_format_variants(text):
    assert _extract_amounts(text) == [250000]


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
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image, psm=6: {
        "available": True, "language": "ind+eng", "text": "TRANSFER BERHASIL Rp 250.000",
        "confidence": 92.0,
    })
    result = Analyzer.create().analyze(png_bytes(), "receipt.png", expected_amount=500000)
    assert result["comparison"]["amount_match"] is False
    assert result["comparison"]["amount_match_basis"] == "ocr_candidates"
    finding = next(item for item in result["findings"] if item["code"] == "amount_mismatch")
    assert finding["points"] == 25
    assert "OCR" in finding["detail"]


def test_analyzer_uses_expected_amount_to_retry_past_decoy_values(monkeypatch):
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        if psm == 11:
            text = "TRANSFER AMOUNT Rp 250.000 BIAYA ADMIN Rp 2.500"
        else:
            text = "BIAYA ADMIN Rp 2.500 TOTAL DEBIT Rp 252.500"
        return {
            "available": True,
            "language": "ind+eng",
            "text": text,
            "confidence": 92.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = Analyzer.create().analyze(
        png_bytes(), "receipt.png", expected_amount=250000
    )

    assert calls == [6, 6, 11]
    assert result["comparison"]["amount_match"] is True
    assert result["ocr"]["ocr_strategy"] == "grayscale_psm11"
    assert result["ocr"]["amounts_idr"] == [250000, 2500]


def test_admin_fee_does_not_match_order_when_transfer_label_exists(monkeypatch):
    text = (
        "NOMINAL TRANSFER Rp 250.000 "
        "BIAYA ADMIN Rp 2.500 "
        "TOTAL DEBIT Rp 252.500"
    )
    tokens = [
        ("NOMINAL", "line-1"), ("TRANSFER", "line-1"),
        ("Rp", "line-1"), ("250.000", "line-1"),
        ("BIAYA", "line-2"), ("ADMIN", "line-2"),
        ("Rp", "line-2"), ("2.500", "line-2"),
        ("TOTAL", "line-3"), ("DEBIT", "line-3"),
        ("Rp", "line-3"), ("252.500", "line-3"),
    ]
    words = [
        {
            "text": token,
            "x": index * 40,
            "y": 100 + (int(line[-1]) - 1) * 30,
            "width": 35,
            "height": 18,
            "line_key": line,
        }
        for index, (token, line) in enumerate(tokens)
    ]
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image, psm=6: {
        "available": True, "language": "ind+eng", "text": text,
        "confidence": 94.0, "words": words,
    })

    result = Analyzer.create().analyze(
        png_bytes(), "receipt.png", expected_amount=2500
    )

    assert result["comparison"]["amount_match"] is False
    assert result["comparison"]["amount_match_basis"] == "transfer_labeled"
    assert result["risk_score"] == 25
    mismatch = next(item for item in result["findings"] if item["code"] == "amount_mismatch")
    assert "berlabel biaya" in mismatch["detail"]


def test_fee_only_expected_amount_is_not_treated_as_transfer(monkeypatch):
    text = "BIAYA ADMIN Rp 2.500"
    words = [
        {"text": "BIAYA", "x": 10, "y": 10, "width": 40, "height": 16, "line_key": "fee"},
        {"text": "ADMIN", "x": 55, "y": 10, "width": 42, "height": 16, "line_key": "fee"},
        {"text": "Rp", "x": 105, "y": 10, "width": 18, "height": 16, "line_key": "fee"},
        {"text": "2.500", "x": 130, "y": 10, "width": 45, "height": 16, "line_key": "fee"},
    ]
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image, psm=6: {
        "available": True, "language": "ind+eng", "text": text,
        "confidence": 92.0, "words": words,
    })

    result = Analyzer.create().analyze(
        png_bytes(), "receipt.png", expected_amount=2500
    )

    assert result["comparison"]["amount_match"] is False
    assert result["comparison"]["amount_match_basis"] == "non_transfer_labeled"
    assert result["risk_score"] == 25


def test_expected_amount_match_is_not_called_bank_verification(monkeypatch):
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image: {
        "available": True, "language": "ind+eng", "text": "TRANSFER BERHASIL Rp 250.000",
        "confidence": 92.0,
    })
    result = Analyzer.create().analyze(png_bytes(), "receipt.png", expected_amount=250000)
    assert result["comparison"]["amount_match"] is True
    assert result["comparison"]["amount_match_basis"] == "unlabeled_or_generic_candidate"
    assert result["risk_score"] == 0
    assert "bukan bukti" in result["disclaimer"]


def test_ocr_fallback_uses_unsharp_only_when_primary_has_no_amount(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append((image, psm))
        if len(calls) == 1:
            return {
                "available": True,
                "language": "ind+eng",
                "text": "TRANSFER SUCCESS SAMPLE",
                "confidence": 92.0,
                "words": [],
            }
        return {
            "available": True,
            "language": "ind+eng",
            "text": "TOTAL TRANSFER Rp 250.000",
            "confidence": 90.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source)

    assert len(calls) == 2
    assert calls[0] == (source, 6)
    assert calls[1][0] is not source
    assert calls[1][1] == 6
    assert result["ocr_strategy"] == "unsharp_mask_psm6"
    assert _extract_amounts(result["text"]) == [250000]


def test_ocr_fallback_retries_when_only_decoy_amount_is_found(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        if psm == 11:
            text = "TRANSFER AMOUNT Rp 250.000 BIAYA ADMIN Rp 2.500"
        else:
            text = "BIAYA ADMIN Rp 2.500 TOTAL DEBIT Rp 252.500"
        return {
            "available": True,
            "language": "ind+eng",
            "text": text,
            "confidence": 92.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source, expected_amount=250000)

    assert calls == [6, 6, 11]
    assert result["ocr_strategy"] == "grayscale_psm11"
    assert 250000 in _extract_amounts(result["text"])


def test_ocr_fallback_retries_when_expected_amount_confidence_is_too_low(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        return {
            "available": True,
            "language": "ind+eng",
            "text": "TRANSFER AMOUNT Rp 250.000",
            "confidence": 25.0 if len(calls) == 1 else 90.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source, expected_amount=250000)

    assert calls == [6, 6]
    assert result["ocr_strategy"] == "unsharp_mask_psm6"
    assert _extract_amounts(result["text"]) == [250000]


def test_ocr_fallback_uses_autocontrast_for_faint_expected_amount(monkeypatch):
    source = Image.new("RGB", (320, 420), "#f1f4f8")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append((image, psm))
        if len(calls) == 4:
            text = "TOTAL TRANSFER Rp 250.000"
            confidence = 88.0
        else:
            text = ""
            confidence = None
        return {
            "available": True,
            "language": "ind+eng",
            "text": text,
            "confidence": confidence,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source, expected_amount=250000)

    assert [psm for _, psm in calls] == [6, 6, 11, 6]
    assert calls[0][0] is source
    assert calls[3][0] is not source
    assert result["ocr_strategy"] == "autocontrast_psm6"
    assert _extract_amounts(result["text"]) == [250000]


def test_ocr_fallback_keeps_legacy_behavior_without_expected_amount(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        return {
            "available": True,
            "language": "ind+eng",
            "text": "BIAYA ADMIN Rp 2.500",
            "confidence": 92.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source)

    assert calls == [6]
    assert result["ocr_strategy"] == "grayscale_psm6"
    assert _extract_amounts(result["text"]) == [2500]


def test_ocr_fallback_uses_sparse_text_mode_after_unsharp_fails(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        if psm == 11:
            return {
                "available": True,
                "language": "ind+eng",
                "text": "TOTAL TRANSFER Rp 325.000",
                "confidence": 91.0,
                "words": [],
            }
        return {
            "available": True,
            "language": "ind+eng",
            "text": "TRANSFER SUCCESS SAMPLE",
            "confidence": 92.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source)

    assert calls == [6, 6, 11]
    assert result["ocr_strategy"] == "grayscale_psm11"
    assert _extract_amounts(result["text"]) == [325000]


def test_ocr_fallback_does_not_rerun_when_primary_reads_amount(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        return {
            "available": True,
            "language": "ind+eng",
            "text": "TOTAL TRANSFER Rp 500.000",
            "confidence": 95.0,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source, expected_amount=500000)

    assert calls == [6]
    assert result["ocr_strategy"] == "grayscale_psm6"
    assert _extract_amounts(result["text"]) == [500000]


def test_ocr_fallback_does_not_retry_when_tesseract_is_unavailable(monkeypatch):
    source = Image.new("RGB", (320, 420), "white")
    calls = []

    def fake_ocr(image, psm=6):
        calls.append(psm)
        return {
            "available": False,
            "language": None,
            "text": "",
            "confidence": None,
            "words": [],
        }

    monkeypatch.setattr(analyzer_module, "_run_ocr", fake_ocr)
    result = _run_ocr_with_fallback(source)

    assert calls == [6]
    assert result["available"] is False
    assert result["ocr_strategy"] == "grayscale_psm6"


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


def test_locate_amount_regions_from_ocr_word_boxes(monkeypatch):
    from app.analyzer import _locate_amount_regions

    text = "TRANSFER BERHASIL Rp 250.000"
    words = [
        {"text": "TRANSFER", "x": 20, "y": 20, "width": 90, "height": 18},
        {"text": "BERHASIL", "x": 120, "y": 20, "width": 95, "height": 18},
        {"text": "Rp", "x": 40, "y": 200, "width": 24, "height": 22},
        {"text": "250.000", "x": 70, "y": 200, "width": 92, "height": 22},
    ]
    regions = _locate_amount_regions(text, words)

    assert len(regions) == 1
    assert regions[0]["amount_idr"] == 250000
    assert regions[0]["x"] == 40
    assert regions[0]["y"] == 200
    assert regions[0]["width"] == 122
    assert regions[0]["height"] == 22


def test_amount_regions_classify_transfer_fee_and_debit_total_labels():
    from app.analyzer import _locate_amount_regions

    text = (
        "NOMINAL TRANSFER Rp 250.000 "
        "BIAYA ADMIN Rp 2.500 "
        "TOTAL DEBIT Rp 252.500"
    )
    tokens = [
        ("NOMINAL", "line-1"), ("TRANSFER", "line-1"),
        ("Rp", "line-1"), ("250.000", "line-1"),
        ("BIAYA", "line-2"), ("ADMIN", "line-2"),
        ("Rp", "line-2"), ("2.500", "line-2"),
        ("TOTAL", "line-3"), ("DEBIT", "line-3"),
        ("Rp", "line-3"), ("252.500", "line-3"),
    ]
    words = [
        {
            "text": token,
            "x": index * 40,
            "y": 100 + (int(line[-1]) - 1) * 30,
            "width": 35,
            "height": 18,
            "line_key": line,
        }
        for index, (token, line) in enumerate(tokens)
    ]

    regions = _locate_amount_regions(text, words)

    assert [item["amount_idr"] for item in regions] == [250000, 2500, 252500]
    assert [item["amount_role"] for item in regions] == [
        "transfer_labeled", "fee_labeled", "debit_total_labeled",
    ]
    assert [item["context_label"] for item in regions] == [
        "NOMINAL TRANSFER", "BIAYA ADMIN", "TOTAL DEBIT",
    ]


def test_amount_region_uses_nearby_label_above_the_amount_box():
    from app.analyzer import _locate_amount_regions

    text = "TOTAL TRANSFER Rp 250.000 BIAYA ADMIN Rp 2.500"
    words = [
        {"text": "TOTAL", "x": 100, "y": 100, "width": 50, "height": 18, "line_key": "label"},
        {"text": "TRANSFER", "x": 155, "y": 100, "width": 70, "height": 18, "line_key": "label"},
        {"text": "Rp", "x": 105, "y": 145, "width": 20, "height": 18, "line_key": "amount"},
        {"text": "250.000", "x": 130, "y": 145, "width": 75, "height": 18, "line_key": "amount"},
        {"text": "BIAYA", "x": 100, "y": 220, "width": 45, "height": 18, "line_key": "fee"},
        {"text": "ADMIN", "x": 150, "y": 220, "width": 45, "height": 18, "line_key": "fee"},
        {"text": "Rp", "x": 205, "y": 220, "width": 20, "height": 18, "line_key": "fee"},
        {"text": "2.500", "x": 230, "y": 220, "width": 45, "height": 18, "line_key": "fee"},
    ]

    regions = _locate_amount_regions(text, words)

    assert [region["amount_role"] for region in regions] == [
        "transfer_labeled", "fee_labeled",
    ]
    assert regions[0]["context_label"] == "TOTAL TRANSFER"
    assert regions[0]["context_position"] == "adjacent_label_above"
    assert regions[1]["context_position"] == "same_line"


def test_generic_transfer_heading_is_not_an_amount_label():
    from app.analyzer import _classify_amount_line

    assert _classify_amount_line("TRANSFER RECEIPT") == (
        "unclassified", None
    )


def test_distant_amount_heading_is_not_associated_with_candidate():
    from app.analyzer import _locate_amount_regions

    regions = _locate_amount_regions(
        "TOTAL TRANSFER Rp 250.000",
        [
            {"text": "TOTAL", "x": 100, "y": 10, "width": 50, "height": 18, "line_key": "label"},
            {"text": "TRANSFER", "x": 155, "y": 10, "width": 70, "height": 18, "line_key": "label"},
            {"text": "Rp", "x": 100, "y": 250, "width": 20, "height": 18, "line_key": "amount"},
            {"text": "250.000", "x": 125, "y": 250, "width": 75, "height": 18, "line_key": "amount"},
        ],
    )

    assert regions[0]["amount_role"] == "unclassified"
    assert regions[0]["context_position"] is None


def test_amount_regions_stay_unclassified_without_same_line_label():
    from app.analyzer import _locate_amount_regions

    regions = _locate_amount_regions(
        "Rp 250.000",
        [
            {"text": "Rp", "x": 10, "y": 10, "width": 20, "height": 18},
            {"text": "250.000", "x": 35, "y": 10, "width": 70, "height": 18},
        ],
    )

    assert regions[0]["amount_role"] == "unclassified"
    assert regions[0]["context_label"] is None


def test_generic_nominal_label_is_not_assumed_to_mean_transfer():
    from app.analyzer import _classify_amount_line

    assert _classify_amount_line("NOMINAL Rp 250.000") == (
        "amount_labeled", "NOMINAL"
    )


def test_fee_label_takes_priority_over_transfer_word():
    from app.analyzer import _classify_amount_line

    assert _classify_amount_line("BIAYA TRANSFER Rp 2.500") == (
        "fee_labeled", "BIAYA TRANSFER"
    )


def test_analyzer_exposes_label_aware_amount_roles(monkeypatch):
    text = (
        "NOMINAL TRANSFER Rp 250.000 "
        "BIAYA ADMIN Rp 2.500 "
        "TOTAL DEBIT Rp 252.500"
    )
    tokens = [
        ("NOMINAL", "line-1"), ("TRANSFER", "line-1"),
        ("Rp", "line-1"), ("250.000", "line-1"),
        ("BIAYA", "line-2"), ("ADMIN", "line-2"),
        ("Rp", "line-2"), ("2.500", "line-2"),
        ("TOTAL", "line-3"), ("DEBIT", "line-3"),
        ("Rp", "line-3"), ("252.500", "line-3"),
    ]
    words = [
        {
            "text": token,
            "x": index * 40,
            "y": 100 + (int(line[-1]) - 1) * 30,
            "width": 35,
            "height": 18,
            "line_key": line,
        }
        for index, (token, line) in enumerate(tokens)
    ]

    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image, psm=6: {
        "available": True,
        "language": "ind+eng",
        "text": text,
        "confidence": 94.0,
        "words": words,
    })
    result = Analyzer.create().analyze(
        png_bytes(), "receipt.png", expected_amount=250000
    )

    assert result["comparison"]["amount_match"] is True
    assert result["comparison"]["amount_match_basis"] == "transfer_labeled"
    assert result["ocr"]["amounts_idr"] == [250000, 2500, 252500]
    assert result["ocr"]["transfer_labeled_amounts_idr"] == [250000]
    assert [region["amount_role"] for region in result["ocr"]["amount_regions"]] == [
        "transfer_labeled", "fee_labeled", "debit_total_labeled",
    ]
    assert result["ocr"]["amount_role_counts"] == {
        "transfer_labeled": 1,
        "amount_labeled": 0,
        "fee_labeled": 1,
        "debit_total_labeled": 1,
        "balance_labeled": 0,
        "unclassified": 0,
    }


def test_analyzer_returns_ocr_overlay_for_detected_amount(monkeypatch):
    monkeypatch.setattr(analyzer_module, "_run_ocr", lambda image: {
        "available": True,
        "language": "ind+eng",
        "text": "TRANSFER BERHASIL Rp 250.000",
        "confidence": 92.0,
        "words": [
            {"text": "TRANSFER", "x": 15, "y": 20, "width": 90, "height": 18},
            {"text": "BERHASIL", "x": 110, "y": 20, "width": 100, "height": 18},
            {"text": "Rp", "x": 30, "y": 100, "width": 20, "height": 20},
            {"text": "250.000", "x": 55, "y": 100, "width": 90, "height": 20},
        ],
    })
    result = Analyzer.create().analyze(png_bytes(), "receipt.png", expected_amount=250000)

    assert result["ocr"]["amount_regions"][0]["amount_idr"] == 250000
    assert result["ocr"]["overlay_data_url"].startswith("data:image/jpeg;base64,")


def test_tesseract_word_coordinates_scale_back_to_original_image(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(analyzer_module, "_tesseract_binary", lambda: "tesseract")
    monkeypatch.setattr(analyzer_module, "_tesseract_languages", lambda: ("eng",))
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t30\t20\t100\t25\t91.0\tRp\n"
        "5\t1\t1\t1\t1\t2\t140\t20\t120\t25\t88.0\t250.000\n"
    )
    monkeypatch.setattr(
        analyzer_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=tsv.encode("utf-8")),
    )

    result = analyzer_module._run_ocr(Image.new("RGB", (2400, 1200), "white"))

    assert result["text"] == "Rp 250.000"
    assert result["words"][0]["x"] == 40
    assert result["words"][0]["y"] == 26
    assert result["words"][0]["width"] == 133
    assert result["words"][0]["height"] == 33
    assert result["words"][0]["line_key"] == "1:1:1"
    assert result["words"][1]["line_key"] == "1:1:1"
