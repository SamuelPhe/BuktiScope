from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-data"
OUT.mkdir(exist_ok=True)
WIDTH, HEIGHT = 1100, 1450


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main():
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f5f7fb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((90, 70, 1010, 1380), radius=32, fill="white", outline="#dbe2ed", width=3)
    draw.rounded_rectangle((90, 70, 1010, 265), radius=32, fill="#14243c")
    draw.rectangle((90, 210, 1010, 265), fill="#14243c")
    draw.text((150, 120), "BUKTISCOPE DEMO BANK", font=font(44, True), fill="white")
    draw.text((150, 190), "DATA SINTETIS - BUKAN BANK SUNGGUHAN", font=font(22, True), fill="#89dcd3")
    draw.text((150, 330), "BUKTI TRANSFER", font=font(42, True), fill="#1b2c46")
    draw.text((150, 405), "Status contoh", font=font(24), fill="#8491a3")
    draw.text((150, 450), "BERHASIL (SIMULASI)", font=font(29, True), fill="#19886e")
    draw.line((150, 520, 950, 520), fill="#e4e9f0", width=3)
    draw.text((150, 580), "NOMINAL TRANSFER", font=font(24, True), fill="#8491a3")
    amount_box = (140, 630, 960, 775)
    draw.rounded_rectangle(amount_box, radius=18, fill="#f1f5fb")
    draw.text((175, 668), "Rp 250.000", font=font(66, True), fill="#172943")
    draw.text((150, 850), "PENERIMA", font=font(22, True), fill="#8491a3")
    draw.text((150, 895), "SAMPLE MERCHANT", font=font(32, True), fill="#344761")
    draw.text((150, 990), "TANGGAL", font=font(22, True), fill="#8491a3")
    draw.text((150, 1035), "27 NOVEMBER 2026 - 10:15 WIB", font=font(27), fill="#344761")
    draw.text((150, 1130), "REFERENSI DEMO-0001 - REKENING XXXX-1234", font=font(21), fill="#65748a")
    draw.rounded_rectangle((135, 1220, 965, 1325), radius=15, fill="#fff4d9", outline="#ead8ac", width=2)
    draw.text((190, 1245), "SAMPLE ONLY - NOT A REAL TRANSFER", font=font(26, True), fill="#956b24")

    clean = OUT / "synthetic-clean.jpg"
    image.save(clean, format="JPEG", quality=96, optimize=True)

    tampered = image.copy()
    edit = ImageDraw.Draw(tampered)
    edit.rounded_rectangle(amount_box, radius=18, fill="#f1f5fb")
    edit.text((175, 668), "Rp 2.500.000", font=font(66, True), fill="#172943")
    edited = OUT / "synthetic-edited.jpg"
    tampered.save(edited, format="JPEG", quality=92, optimize=True)

    (OUT / "LABELS.txt").write_text(
        "Synthetic demo files; never use as payment evidence.\n"
        "synthetic-clean.jpg: generated reference image with Rp 250.000.\n"
        "synthetic-edited.jpg: generated edit with changed amount Rp 2.500.000.\n"
        "These are illustrative fixtures, not a validated fraud-detection benchmark.\n",
        encoding="utf-8",
    )
    print(f"Generated: {clean}")
    print(f"Generated: {edited}")


if __name__ == "__main__":
    main()
