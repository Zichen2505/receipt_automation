"""Public, same-origin upload page and its fixed static assets."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/")
async def upload_page():
    return FileResponse(WEB_DIR / "index.html", headers=HEADERS)


@router.get("/web/upload.js")
async def upload_script():
    return FileResponse(WEB_DIR / "upload.js", media_type="text/javascript", headers=HEADERS)


@router.get("/web/style.css")
async def upload_styles():
    return FileResponse(WEB_DIR / "style.css", media_type="text/css", headers=HEADERS)
