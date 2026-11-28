from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import ExifTags, Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from .perceptual import hamming_distance, perceptual_hash

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
EDITING_SOFTWARE = (
    "photoshop", "adobe", "gimp", "canva", "picsart", "snapseed",
    "pixlr", "photopea", "affinity", "pixelmator", "lightroom",
)
TRANSFER_TERMS = (
    "transfer", "berhasil", "transaksi", "nominal", "rekening",
    "penerima", "pengirim", "tanggal", "waktu", "referensi", "ref",
    "saldo", "bukti", "success", "successful", "payment",
)


class AnalysisError(ValueError):
    """Raised when an uploaded image cannot safely be analyzed."""


@dataclass
class Analyzer:
    """Analyze transfer-evidence images without retaining their contents."""

    seen_hashes: set[str]
    seen_phashes: dict[str, str]

    @classmethod
    def create(cls) -> "Analyzer":
        return cls(seen_hashes=set(), seen_phashes={})

    def analyze(
        self,
        raw: bytes,
        filename: str,
        expected_amount: int | None = None,
        expected_recipient: str | None = None,
    ) -> dict[str, Any]:
        if not raw:
            raise AnalysisError("File kosong.")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise AnalysisError("Ukuran file melewati batas 10 MB.")

        sha256 = hashlib.sha256(raw).hexdigest()
        try:
            with Image.open(io.BytesIO(raw)) as source:
                source.verify()
            with Image.open(io.BytesIO(raw)) as source:
                image_format = (source.format or "").upper()
                if image_format not in ALLOWED_FORMATS:
                    raise AnalysisError("Format tidak didukung. Gunakan JPG, PNG, atau WEBP.")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise AnalysisError("Dimensi gambar tidak valid atau melebihi 20 megapiksel.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                metadata = _read_metadata(source)
        except AnalysisError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise AnalysisError("File bukan gambar yang valid atau tidak dapat dibaca.") from exc

        findings: list[dict[str, Any]] = []
        score = 0
        image_phash = perceptual_hash(image)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        format_extensions = {"JPEG": {"jpg", "jpeg"}, "PNG": {"png"}, "WEBP": {"webp"}}
        if extension and extension not in format_extensions[image_format]:
            score += 20
            findings.append(_finding(
                "extension_mismatch", "medium", "Ekstensi dan format file tidak cocok",
                f"Nama file memakai .{extension}, tetapi isi file terdeteksi sebagai {image_format}. Ini perlu diperiksa, tetapi dapat terjadi karena file hanya diganti nama.", 20,
            ))

        software = str(metadata.get("software") or "").strip()
        if software:
            software_lower = software.lower()
            if any(marker in software_lower for marker in EDITING_SOFTWARE):
                score += 12
                findings.append(_finding(
                    "editing_software_metadata", "low", "Metadata menyebut perangkat lunak pengolah gambar",
                    f"Metadata perangkat lunak: {software[:120]}. Aplikasi kamera, editor, atau proses ekspor dapat meninggalkan metadata ini; ini bukan bukti pemalsuan.", 12,
                ))
            else:
                findings.append(_finding(
                    "software_metadata_present", "info", "Metadata perangkat lunak tersedia",
                    f"Informasi perangkat lunak: {software[:120]}.", 0,
                ))

        duplicate = sha256 in self.seen_hashes
        nearest_match: dict[str, Any] | None = None
        if image_phash and not duplicate:
            candidates = (
                (hamming_distance(image_phash, previous_hash), previous_sha)
                for previous_sha, previous_hash in self.seen_phashes.items()
                if previous_sha != sha256
            )
            nearest_distance, nearest_sha = min(candidates, default=(65, ""))
            if nearest_distance <= 6:
                nearest_match = {
                    "hamming_distance": nearest_distance,
                    "previous_sha256_prefix": nearest_sha[:16],
                }

        self.seen_hashes.add(sha256)
        if image_phash:
            self.seen_phashes[sha256] = image_phash
        if len(self.seen_hashes) > 5_000:
            self.seen_hashes = {sha256}
            self.seen_phashes = {sha256: image_phash} if image_phash else {}

        if duplicate:
            score += 35
            findings.append(_finding(
                "duplicate_upload", "medium", "File yang identik pernah diperiksa dalam sesi ini",
                "Sidik jari SHA-256 cocok dengan file yang sudah diperiksa sejak aplikasi berjalan. Ini dapat berarti pengiriman ulang yang sah; bukan bukti penipuan.", 35,
            ))
        elif nearest_match:
            findings.append(_finding(
                "near_duplicate_upload", "info", "Gambar sangat mirip dengan file lain dalam sesi ini",
                f"Jarak hash perceptual {nearest_match['hamming_distance']} bit dari file {nearest_match['previous_sha256_prefix']}…. Perubahan ukuran atau kompresi dapat menghasilkan kecocokan; ini bukan bukti penggunaan ulang yang mencurigakan.",
                0,
            ))

        ocr = _run_ocr_with_fallback(image, expected_amount=expected_amount)
        extracted_amounts = _extract_amounts(ocr["text"])
        amount_regions = _locate_amount_regions(ocr["text"], ocr.get("words", []))
        transfer_labeled_amounts = [
            region["amount_idr"] for region in amount_regions
            if region["amount_role"] == "transfer_labeled"
        ]
        amount_role_counts = {
            role: sum(1 for region in amount_regions if region["amount_role"] == role)
            for role in (
                "transfer_labeled", "fee_labeled", "debit_total_labeled",
                "balance_labeled", "unclassified",
            )
        }
        ocr_overlay = _ocr_overlay(image, amount_regions)
        normalized_expected = _normalize_recipient(expected_recipient)
        recipient_match: bool | None = None
        if normalized_expected:
            normalized_ocr = _normalize_recipient(ocr["text"])
            recipient_match = normalized_expected in normalized_ocr
            if recipient_match is False and ocr["text"].strip():
                score += 10
                findings.append(_finding(
                    "recipient_not_found", "low", "Nama penerima yang diharapkan tidak ditemukan oleh OCR",
                    "OCR tidak menemukan teks penerima yang cocok. Kualitas gambar dan kesalahan OCR dapat menyebabkan hasil ini; periksa secara manual.", 10,
                ))
            elif recipient_match:
                findings.append(_finding(
                    "recipient_match", "info", "Nama penerima cocok dengan teks OCR",
                    "Teks yang diberikan ditemukan pada hasil OCR. Ini hanya pencocokan teks, bukan validasi rekening.", 0,
                ))

        amount_match: bool | None = None
        if expected_amount is not None and extracted_amounts and (ocr["confidence"] or 0) >= 40:
            amount_match = int(expected_amount) in extracted_amounts
            if not amount_match:
                score += 25
                findings.append(_finding(
                    "amount_mismatch", "medium", "Nominal yang terbaca tidak cocok dengan pesanan",
                    "Nominal yang disediakan tidak ditemukan pada teks OCR. OCR bisa salah membaca angka; periksa gambar dan data transaksi sebelum mengambil tindakan.", 25,
                ))
            else:
                findings.append(_finding(
                    "amount_match", "info", "Nominal pesanan ditemukan dalam teks OCR",
                    "Nominal yang diharapkan ditemukan oleh OCR. Ini tidak membuktikan transfer berhasil.", 0,
                ))
        elif expected_amount is not None:
            findings.append(_finding(
                "amount_not_read", "info", "Nominal belum dapat dibandingkan",
                "OCR tidak menemukan nominal berformat Rupiah/IDR dengan keyakinan baca yang cukup untuk dibandingkan.", 0,
            ))

        ela = _ela_analysis(image, image_format)
        findings.append(_finding(
            "ela_preview", "info", "Analisis perbedaan kompresi tersedia" if ela else "Analisis ELA tidak tersedia untuk format ini",
            "Peta ELA hanya visualisasi perbedaan antara gambar dan hasil kompresi ulang. Pola terang dapat muncul pada gambar normal; ELA tidak digunakan sendirian untuk menambah skor risiko." if ela else "ELA standar difokuskan pada JPEG. PNG dan WEBP tidak diberi penilaian ELA pada MVP ini.", 0,
        ))

        if not ocr["available"]:
            findings.append(_finding(
                "ocr_unavailable", "info", "OCR tidak tersedia",
                "Pasang Tesseract OCR dan paket bahasa Indonesia (ind) serta Inggris (eng) untuk mengaktifkan ekstraksi teks.", 0,
            ))
        elif not ocr["text"].strip():
            findings.append(_finding(
                "ocr_no_text", "info", "Tidak ada teks yang berhasil dibaca",
                "Gambar mungkin terlalu buram, terlalu kecil, atau tidak berisi teks yang dikenali OCR.", 0,
            ))

        score = min(100, max(0, score))
        if score >= 50:
            status = "high_risk"
            label = "Risiko tinggi — periksa secara manual"
        elif score >= 20:
            status = "review"
            label = "Perlu ditinjau"
        else:
            status = "low_risk"
            label = "Tidak ditemukan indikator kuat pada pemeriksaan ini"

        transfer_term_hits = [term for term in TRANSFER_TERMS if term in ocr["text"].lower()]
        if not findings:
            findings.append(_finding("no_signal", "info", "Tidak ada indikator khusus yang ditemukan", "Pemeriksaan dasar selesai tanpa temuan yang menaikkan skor risiko.", 0))

        return {
            "status": status,
            "status_label": label,
            "risk_score": score,
            "disclaimer": "Hasil ini hanya penyaringan risiko gambar. Skor rendah bukan bukti bahwa transaksi asli atau uang telah masuk. Selalu konfirmasi melalui mutasi rekening atau kanal resmi bank/penyedia pembayaran.",
            "findings": findings,
            "image": {
                "filename": _safe_filename(filename),
                "format": image_format,
                "width": width,
                "height": height,
                "size_bytes": len(raw),
                "sha256": sha256,
                "duplicate_in_session": duplicate,
                "perceptual_hash": image_phash,
                "similar_in_session": nearest_match,
                "metadata": metadata,
            },
            "ocr": {
                "available": ocr["available"],
                "language": ocr["language"],
                "text": ocr["text"][:5_000],
                "confidence": ocr["confidence"],
                "ocr_strategy": ocr.get("ocr_strategy", "grayscale_psm6"),
                "transfer_keywords": transfer_term_hits,
                "amounts_idr": extracted_amounts,
                "amount_regions": amount_regions,
                "transfer_labeled_amounts_idr": transfer_labeled_amounts,
                "amount_role_counts": amount_role_counts,
                "overlay_data_url": ocr_overlay,
            },
            "comparison": {
                "expected_amount_idr": expected_amount,
                "amount_match": amount_match,
                "expected_recipient": expected_recipient,
                "recipient_text_match": recipient_match,
            },
            "ela": ela,
        }


def _finding(code: str, severity: str, title: str, detail: str, points: int) -> dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail, "points": points}


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload")[:100] or "upload"


def _read_metadata(image: Image.Image) -> dict[str, Any]:
    try:
        exif = image.getexif()
    except Exception:
        exif = {}
    tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
    software = tags.get("Software") or image.info.get("Software") or image.info.get("software")
    timestamp = tags.get("DateTimeOriginal") or tags.get("DateTime") or image.info.get("creation_time")
    return {
        "software": str(software)[:200] if software else None,
        "timestamp": str(timestamp)[:80] if timestamp else None,
        "exif_fields_count": len(tags),
        "metadata_present": bool(tags or image.info),
    }


@lru_cache(maxsize=1)
def _tesseract_binary() -> str | None:
    configured_path = os.environ.get("TESSERACT_CMD")
    if configured_path:
        if os.path.isfile(configured_path):
            return configured_path
        return shutil.which(configured_path)
    return shutil.which("tesseract")


@lru_cache(maxsize=1)
def _tesseract_languages() -> tuple[str, ...]:
    binary = _tesseract_binary()
    if not binary:
        return ()
    try:
        result = subprocess.run(
            [binary, "--list-langs"], capture_output=True, text=True,
            check=True, timeout=4,
        )
        return tuple(
            line.strip() for line in result.stdout.splitlines()
            if re.fullmatch(r"[A-Za-z0-9_]+", line.strip())
        )
    except Exception:
        return ()


def _run_ocr(image: Image.Image, psm: int = 6) -> dict[str, Any]:
    binary = _tesseract_binary()
    languages = _tesseract_languages()
    if not binary or not languages:
        return {"available": False, "language": None, "text": "", "confidence": None, "words": []}
    selected = "+".join(lang for lang in ("ind", "eng") if lang in languages) or ("eng" if "eng" in languages else None)
    if not selected:
        return {"available": False, "language": None, "text": "", "confidence": None, "words": []}
    prepared = ImageOps.grayscale(image)
    prepared.thumbnail((1800, 1800))
    scale_x = image.width / prepared.width
    scale_y = image.height / prepared.height
    image_buffer = io.BytesIO()
    prepared.save(image_buffer, format="PNG", optimize=True)
    try:
        result = subprocess.run(
            [binary, "stdin", "stdout", "-l", selected, "--psm", str(psm), "tsv"],
            input=image_buffer.getvalue(), capture_output=True, timeout=8, check=True,
        )
        decoded = result.stdout.decode("utf-8", errors="replace")
        rows = csv.DictReader(io.StringIO(decoded), delimiter="\t")
        pieces: list[str] = []
        confidences: list[float] = []
        words: list[dict[str, Any]] = []
        for row in rows:
            word = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf", "-1"))
            except (TypeError, ValueError):
                confidence = -1
            if word:
                pieces.append(word)
                try:
                    left = max(0, int(float(row.get("left", 0)) * scale_x))
                    top = max(0, int(float(row.get("top", 0)) * scale_y))
                    box_width = max(0, int(float(row.get("width", 0)) * scale_x))
                    box_height = max(0, int(float(row.get("height", 0)) * scale_y))
                    if box_width and box_height:
                        words.append({
                            "text": word,
                            "confidence": round(confidence, 1) if confidence >= 0 else None,
                            "x": left,
                            "y": top,
                            "width": box_width,
                            "height": box_height,
                            "line_key": ":".join(
                                str(row.get(key) or "0")
                                for key in ("block_num", "par_num", "line_num")
                            ),
                        })
                except (TypeError, ValueError, OverflowError):
                    pass
            if confidence >= 0:
                confidences.append(confidence)
        return {
            "available": True,
            "language": selected,
            "text": " ".join(pieces),
            "confidence": round(float(np.mean(confidences)), 1) if confidences else None,
            "words": words[:500],
        }
    except Exception:
        return {"available": True, "language": selected, "text": "", "confidence": None, "words": []}


def _run_ocr_with_fallback(
    image: Image.Image,
    expected_amount: int | None = None,
) -> dict[str, Any]:
    """Retry OCR when the supplied target amount is missing, not just when all amounts are."""
    def target_found(result: dict[str, Any]) -> bool:
        amounts = _extract_amounts(str(result.get("text") or ""))
        if expected_amount is None:
            return bool(amounts)
        if int(expected_amount) not in amounts:
            return False
        try:
            confidence = float(result.get("confidence") or 0)
        except (TypeError, ValueError):
            return False
        return 40 <= confidence <= 100

    primary = _run_ocr(image)
    primary["ocr_strategy"] = "grayscale_psm6"
    if not primary.get("available") or target_found(primary):
        return primary

    # Sharpening is a targeted fallback for mild blur; keep the original image
    # as the first choice so already-readable receipts are not degraded.
    sharpened = ImageOps.grayscale(image).filter(
        ImageFilter.UnsharpMask(radius=2, percent=250, threshold=2)
    )
    sharpened_result = _run_ocr(sharpened)
    if sharpened_result.get("available") and target_found(sharpened_result):
        sharpened_result["ocr_strategy"] = "unsharp_mask_psm6"
        return sharpened_result

    # Sparse-text segmentation can recover amounts missed by PSM 6 on
    # perspective-distorted layouts. Word boxes remain mapped to original pixels.
    sparse_result = _run_ocr(image, psm=11)
    if sparse_result.get("available") and target_found(sparse_result):
        sparse_result["ocr_strategy"] = "grayscale_psm11"
        return sparse_result

    return primary


def _parse_idr_number(raw: str) -> int | None:
    value = re.sub(r"[^0-9,.]", "", raw)
    if not value:
        return None
    if "." in value and "," in value:
        value = value.replace(".", "").split(",", 1)[0]
    elif "." in value:
        groups = value.split(".")
        value = "".join(groups) if all(len(part) == 3 for part in groups[1:]) else groups[0]
    elif "," in value:
        groups = value.split(",")
        value = "".join(groups) if all(len(part) == 3 for part in groups[1:]) else groups[0]
    try:
        return int(value)
    except ValueError:
        return None


def _extract_amounts(text: str) -> list[int]:
    matches = re.findall(r"(?:\bRp\.?|\bIDR\b)\s*[:.]?\s*([0-9][0-9.,]*)", text, flags=re.IGNORECASE)
    results = []
    for item in matches:
        amount = _parse_idr_number(item)
        if amount is not None and amount not in results:
            results.append(amount)
    return results[:20]




def _classify_amount_line(line_text: str) -> tuple[str, str | None]:
    """Classify an amount using explicit words on the same OCR line only."""
    normalized = re.sub(r"[^A-Z0-9]+", " ", line_text.upper()).strip()
    if not normalized:
        return "unclassified", None

    labels = (
        ("fee_labeled", (
            "BIAYA ADMIN", "ADMIN FEE", "SERVICE FEE", "BIAYA LAYANAN",
            "BIAYA TRANSFER", "BIAYA", "FEE", "CHARGE", "PAJAK", "PPN", "TAX",
        )),
        ("debit_total_labeled", (
            "TOTAL DEBIT", "DEBIT TOTAL", "TOTAL PENARIKAN", "JUMLAH DEBIT",
        )),
        ("balance_labeled", ("SALDO", "BALANCE")),
        ("transfer_labeled", (
            "NOMINAL TRANSFER", "JUMLAH TRANSFER", "TRANSFER AMOUNT",
            "AMOUNT TRANSFER", "TOTAL TRANSFER", "TRANSFER", "NOMINAL",
        )),
    )
    padded = f" {normalized} "
    for role, phrases in labels:
        for phrase in phrases:
            if f" {phrase} " in padded:
                return role, phrase
    return "unclassified", None


def _locate_amount_regions(text: str, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map IDR matches to original pixels and classify explicit same-line context."""
    if not text or not words:
        return []

    spans: list[tuple[int, int, dict[str, Any]]] = []
    cursor = 0
    for word in words:
        token = str(word.get("text") or "").strip()
        if not token:
            continue
        start = text.find(token, cursor)
        if start < 0:
            continue
        end = start + len(token)
        spans.append((start, end, word))
        cursor = end

    line_groups: dict[str, list[str]] = {}
    for word in words:
        line_key = word.get("line_key")
        token = str(word.get("text") or "").strip()
        if line_key is not None and token:
            line_groups.setdefault(str(line_key), []).append(token)

    regions: list[dict[str, Any]] = []
    amount_pattern = re.compile(
        r"(?:\bRp\.?|\bIDR\b)\s*[:.]?\s*([0-9][0-9.,]*)",
        flags=re.IGNORECASE,
    )
    for match in amount_pattern.finditer(text):
        matching_words = [
            word for start, end, word in spans
            if start < match.end() and end > match.start()
        ]
        if not matching_words:
            continue
        x0 = min(int(word["x"]) for word in matching_words)
        y0 = min(int(word["y"]) for word in matching_words)
        x1 = max(int(word["x"]) + int(word["width"]) for word in matching_words)
        y1 = max(int(word["y"]) + int(word["height"]) for word in matching_words)
        amount = _parse_idr_number(match.group(1))
        if amount is None:
            continue

        line_keys = {
            str(word["line_key"])
            for word in matching_words
            if word.get("line_key") is not None
        }
        line_key = next(iter(line_keys)) if len(line_keys) == 1 else None
        line_text = " ".join(line_groups.get(line_key, [])) if line_key else ""
        amount_role, context_label = _classify_amount_line(line_text)
        regions.append({
            "amount_idr": amount,
            "text": match.group(0),
            "amount_role": amount_role,
            "context_label": context_label,
            "x": x0,
            "y": y0,
            "width": max(1, x1 - x0),
            "height": max(1, y1 - y0),
        })
    return regions[:20]


def _ocr_overlay(image: Image.Image, regions: list[dict[str, Any]]) -> str | None:
    """Build a bounded preview with OCR-detected amount boxes."""
    if not regions:
        return None
    preview = image.copy()
    preview.thumbnail((900, 900))
    scale_x = preview.width / image.width
    scale_y = preview.height / image.height
    draw = ImageDraw.Draw(preview)
    for index, region in enumerate(regions, start=1):
        x0 = int(region["x"] * scale_x)
        y0 = int(region["y"] * scale_y)
        x1 = int((region["x"] + region["width"]) * scale_x)
        y1 = int((region["y"] + region["height"]) * scale_y)
        draw.rectangle((x0, y0, x1, y1), outline="#13a77b", width=3)
        draw.text((x0 + 3, max(0, y0 - 15)), str(index), fill="#13a77b")
    output = io.BytesIO()
    preview.save(output, format="JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")

def _normalize_recipient(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _ela_analysis(image: Image.Image, image_format: str) -> dict[str, Any] | None:
    if image_format != "JPEG":
        return None

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    buffer.seek(0)
    recompressed = Image.open(buffer).convert("RGB")
    difference = ImageChops.difference(image, recompressed)
    grayscale = ImageOps.grayscale(difference)
    extrema = grayscale.getextrema()
    values = np.asarray(grayscale, dtype=np.float32)
    mean = float(values.mean())
    p95 = float(np.percentile(values, 95))

    # Compare 4x4 tiles against the image's own ELA distribution.
    # These are relative compression-difference hotspots, not manipulation labels.
    tile_rows = 4
    tile_columns = 4
    height, width = values.shape
    tile_scores: list[dict[str, float | int]] = []
    row_edges = np.linspace(0, height, tile_rows + 1, dtype=int)
    col_edges = np.linspace(0, width, tile_columns + 1, dtype=int)
    for row in range(tile_rows):
        for column in range(tile_columns):
            y0, y1 = int(row_edges[row]), int(row_edges[row + 1])
            x0, x1 = int(col_edges[column]), int(col_edges[column + 1])
            tile = values[y0:y1, x0:x1]
            if tile.size == 0:
                continue
            tile_scores.append({
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
                "mean": float(tile.mean()),
                "p95": float(np.percentile(tile, 95)),
            })

    tile_means = np.asarray([item["mean"] for item in tile_scores], dtype=np.float32)
    median = float(np.median(tile_means)) if tile_means.size else 0.0
    mad = float(np.median(np.abs(tile_means - median))) if tile_means.size else 0.0
    threshold = median + max(2.5 * mad, 0.5)
    candidates = [item for item in tile_scores if item["mean"] > threshold]
    candidates.sort(key=lambda item: (item["mean"], item["p95"]), reverse=True)
    hotspots = [
        {
            "x": int(item["x"]),
            "y": int(item["y"]),
            "width": int(item["width"]),
            "height": int(item["height"]),
            "mean_difference": round(float(item["mean"]), 3),
            "p95_difference": round(float(item["p95"]), 3),
        }
        for item in candidates[:3]
    ]

    preview = ImageEnhance.Contrast(grayscale).enhance(4.0).convert("RGB")
    preview.thumbnail((650, 650))
    if hotspots:
        overlay = ImageDraw.Draw(preview)
        scale_x = preview.width / width
        scale_y = preview.height / height
        for index, region in enumerate(hotspots, start=1):
            x0 = int(region["x"] * scale_x)
            y0 = int(region["y"] * scale_y)
            x1 = int((region["x"] + region["width"]) * scale_x)
            y1 = int((region["y"] + region["height"]) * scale_y)
            overlay.rectangle((x0, y0, x1, y1), outline="#ff3b52", width=3)
            overlay.text((x0 + 5, y0 + 5), str(index), fill="#ff3b52")

    output = io.BytesIO()
    preview.save(output, format="PNG", optimize=True)
    return {
        "available": True,
        "mean_difference": round(mean, 3),
        "p95_difference": round(p95, 3),
        "max_difference": int(extrema[1]),
        "hotspot_method": "4x4 relative tile comparison; median + 2.5 MAD and 0.5 floor",
        "hotspots": hotspots,
        "preview_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"),
        "interpretation": (
            "Red boxes mark up to three tiles with the strongest relative JPEG recompression differences. "
            "Normal text, edges, gradients, resizing, and compression can also create hotspots. "
            "This is a navigation aid for human review, not evidence of editing."
        ),
    }
