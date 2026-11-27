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
from PIL import ExifTags, Image, ImageChops, ImageEnhance, ImageOps, UnidentifiedImageError

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

    @classmethod
    def create(cls) -> "Analyzer":
        return cls(seen_hashes=set())

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
        self.seen_hashes.add(sha256)
        if len(self.seen_hashes) > 5_000:
            self.seen_hashes = {sha256}
        if duplicate:
            score += 35
            findings.append(_finding(
                "duplicate_upload", "medium", "File yang identik pernah diperiksa dalam sesi ini",
                "Sidik jari SHA-256 cocok dengan file yang sudah diperiksa sejak aplikasi berjalan. Ini dapat berarti pengiriman ulang yang sah; bukan bukti penipuan.", 35,
            ))

        ocr = _run_ocr(image)
        extracted_amounts = _extract_amounts(ocr["text"])
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
                "metadata": metadata,
            },
            "ocr": {
                "available": ocr["available"],
                "language": ocr["language"],
                "text": ocr["text"][:5_000],
                "confidence": ocr["confidence"],
                "transfer_keywords": transfer_term_hits,
                "amounts_idr": extracted_amounts,
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


def _run_ocr(image: Image.Image) -> dict[str, Any]:
    binary = _tesseract_binary()
    languages = _tesseract_languages()
    if not binary or not languages:
        return {"available": False, "language": None, "text": "", "confidence": None}
    selected = "+".join(lang for lang in ("ind", "eng") if lang in languages) or ("eng" if "eng" in languages else None)
    if not selected:
        return {"available": False, "language": None, "text": "", "confidence": None}
    prepared = ImageOps.grayscale(image)
    prepared.thumbnail((1800, 1800))
    image_buffer = io.BytesIO()
    prepared.save(image_buffer, format="PNG", optimize=True)
    try:
        result = subprocess.run(
            [binary, "stdin", "stdout", "-l", selected, "--psm", "6", "tsv"],
            input=image_buffer.getvalue(), capture_output=True, timeout=8, check=True,
        )
        decoded = result.stdout.decode("utf-8", errors="replace")
        rows = csv.DictReader(io.StringIO(decoded), delimiter="\t")
        pieces: list[str] = []
        confidences: list[float] = []
        for row in rows:
            word = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf", "-1"))
            except (TypeError, ValueError):
                confidence = -1
            if word:
                pieces.append(word)
            if confidence >= 0:
                confidences.append(confidence)
        return {
            "available": True,
            "language": selected,
            "text": " ".join(pieces),
            "confidence": round(float(np.mean(confidences)), 1) if confidences else None,
        }
    except Exception:
        return {"available": True, "language": selected, "text": "", "confidence": None}


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
    preview = ImageEnhance.Contrast(grayscale).enhance(4.0)
    preview.thumbnail((650, 650))
    output = io.BytesIO()
    preview.save(output, format="PNG", optimize=True)
    return {
        "available": True,
        "mean_difference": round(mean, 3),
        "p95_difference": round(p95, 3),
        "max_difference": int(extrema[1]),
        "preview_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"),
        "interpretation": "Visual aid only; compression, resizing, and normal image content can also produce bright regions.",
    }
