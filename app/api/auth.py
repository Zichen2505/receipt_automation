import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import Settings
from app.dependencies import get_settings


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), settings.app_api_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Invalid API key"})


def require_extraction_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.extraction_jobs_enabled:
        raise HTTPException(503, detail={"code": "feature_disabled", "message": "Extraction jobs are disabled"})
    if not settings.extraction_api_key or x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), settings.extraction_api_key.encode("utf-8")
    ):
        raise HTTPException(401, detail={"code": "unauthorized", "message": "Invalid API key"})
