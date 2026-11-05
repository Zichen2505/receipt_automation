"""HTTP admission checks only; receipt extraction and persistence belong to Service."""

import asyncio
from io import BytesIO
import logging

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.config import Settings


# Parser diagnostics can include document contents. Do not forward them to logs.
logging.getLogger("pypdf").addHandler(logging.NullHandler())
logging.getLogger("pypdf").propagate = False
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def reject(status: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def check_pdf(pdf_bytes: bytes, max_pages: int) -> None:
    if not pdf_bytes.startswith(b"%PDF-"):
        reject(415, "unsupported_media_type", "A PDF file is required")
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            reject(422, "encrypted_pdf", "Encrypted PDFs are not supported")
        count = len(reader.pages)
    except HTTPException:
        raise
    except Exception:
        reject(422, "invalid_pdf", "PDF structure could not be validated")
    if count < 1:
        reject(422, "invalid_pdf", "PDF must contain at least one page")
    if count > max_pages:
        reject(413, "too_many_pages", "PDF exceeds the configured page limit")


async def read_pdf(file: UploadFile, settings: Settings) -> bytes:
    try:
        media_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        if media_type not in {"application/pdf", "application/octet-stream"}:
            reject(415, "unsupported_media_type", "A PDF file is required")
        if file.size is not None and file.size > settings.max_upload_bytes:
            reject(413, "file_too_large", "PDF exceeds the configured byte limit")
        content = bytearray()
        while chunk := await file.read(min(64 * 1024, settings.max_upload_bytes - len(content) + 1)):
            content.extend(chunk)
            if len(content) > settings.max_upload_bytes:
                reject(413, "file_too_large", "PDF exceeds the configured byte limit")
        if not content:
            reject(400, "empty_file", "Uploaded file is empty")
        pdf_bytes = bytes(content)
        await asyncio.to_thread(check_pdf, pdf_bytes, settings.max_pdf_pages)
        return pdf_bytes
    finally:
        await file.close()


class BodyLimitExceeded(MultiPartException):
    """Internal ASGI signal before multipart parsing can spool an unlimited body."""


class UploadBodyLimitMiddleware:
    """Bound total multipart input even with absent or misleading Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or scope["path"].rstrip("/") not in {"/api/v1/receipts", "/api/v1/extractions"}):
            await self.app(scope, receive, send)
            return
        settings = scope["app"].state.settings
        limit = settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
        consumed = 0
        exceeded = False

        async def limited_receive():
            nonlocal consumed, exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    exceeded = True
                    # Starlette closes all multipart temporary files on this signal.
                    raise BodyLimitExceeded("Multipart body exceeds the configured limit")
            return message

        async def limited_send(message):
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except BodyLimitExceeded:
            exceeded = True
        if exceeded:
            response = JSONResponse(status_code=413, content={"detail": {
                "code": "request_too_large", "message": "Multipart body exceeds the configured limit"}})
            await response(scope, receive, send)
