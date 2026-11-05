from fastapi import HTTPException, Request

from app.config import Settings
from app.services.receipt_service import ReceiptService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_receipt_service(request: Request) -> ReceiptService:
    """Return the startup-initialized production service; tests may override it."""
    return request.app.state.receipt_service


def get_extraction_service(request: Request):
    service = getattr(request.app.state, "extraction_service", None)
    if service is None:
        raise HTTPException(503, detail={"code": "feature_disabled", "message": "Extraction jobs are disabled"})
    return service
