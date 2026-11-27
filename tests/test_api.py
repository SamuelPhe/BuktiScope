from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app, analyzer


def make_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 160), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["name"] == "BuktiScope"


def test_analyze_endpoint_returns_risk_report():
    analyzer.seen_hashes.clear()
    analyzer.seen_phashes.clear()
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            content=make_png(),
            headers={
                "Content-Type": "image/png",
                "X-File-Name": "receipt.png",
                "X-Expected-Amount": "250000",
                "X-Expected-Recipient": "SAMPLE%20MERCHANT",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"low_risk", "review", "high_risk"}
    assert "findings" in payload
    assert "sha256" in payload["image"]
    assert "bukan bukti" in payload["disclaimer"]


def test_analyze_rejects_non_image_upload():
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            content=b"hello",
            headers={"Content-Type": "text/plain", "X-File-Name": "not-image.txt"},
        )
    assert response.status_code == 400


def test_analyze_rejects_oversized_request_body():
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            content=b"x" * (10 * 1024 * 1024 + 1),
            headers={"Content-Type": "image/png"},
        )
    assert response.status_code == 413


def test_invalid_amount_header_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            content=make_png(),
            headers={"Content-Type": "image/png", "X-Expected-Amount": "-1"},
        )
    assert response.status_code == 400
