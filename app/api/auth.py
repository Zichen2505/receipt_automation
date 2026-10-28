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
