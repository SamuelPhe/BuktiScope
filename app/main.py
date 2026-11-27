from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import MAX_UPLOAD_BYTES, AnalysisError, Analyzer

analyzer = Analyzer.create()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    analyzer.seen_hashes.clear()


app = FastAPI(
    title="BuktiScope API",
    description="Local-first image screening for Indonesian transfer evidence. Not bank verification.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "name": "BuktiScope", "version": "0.1.0"}


@app.post(
    "/api/analyze",
    summary="Analyze a transfer-evidence image",
    description=(
        "Send raw JPG, PNG, or WEBP bytes as the request body. Optional headers: "
        "X-File-Name, X-Expected-Amount, and URL-encoded X-Expected-Recipient. "
        "The image body is streamed with a 10 MB limit and is not written to an upload file."
    ),
    openapi_extra={
        "parameters": [
            {"name": "X-File-Name", "in": "header", "required": False, "schema": {"type": "string"}},
            {"name": "X-Expected-Amount", "in": "header", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 10000000000}},
            {"name": "X-Expected-Recipient", "in": "header", "required": False, "schema": {"type": "string", "maxLength": 300}, "description": "URL-encoded recipient text"},
        ],
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in ("image/jpeg", "image/png", "image/webp")
            },
        },
    },
)
async def analyze_receipt(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Ukuran file melewati batas 10 MB.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length tidak valid.") from exc

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Ukuran file melewati batas 10 MB.")
        raw.extend(chunk)

    expected_amount = None
    amount_header = request.headers.get("x-expected-amount")
    if amount_header:
        if not amount_header.isdigit() or not (1 <= int(amount_header) <= 10_000_000_000):
            raise HTTPException(status_code=400, detail="X-Expected-Amount harus berupa nominal Rupiah yang valid.")
        expected_amount = int(amount_header)

    expected_recipient = unquote(request.headers.get("x-expected-recipient", "")).strip() or None
    if expected_recipient and len(expected_recipient) > 100:
        raise HTTPException(status_code=400, detail="Nama penerima maksimal 100 karakter.")

    try:
        result = analyzer.analyze(
            raw=bytes(raw),
            filename=unquote(request.headers.get("x-file-name", "upload")),
            expected_amount=expected_amount,
            expected_recipient=expected_recipient,
        )
        return result
    except AnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
