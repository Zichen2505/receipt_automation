from fastapi import Request

from app.config import Settings
from app.services.receipt_service import ReceiptService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_receipt_service(request: Request) -> ReceiptService:
    """Return the startup-initialized production service; tests may override it."""
    return request.app.state.receipt_service
