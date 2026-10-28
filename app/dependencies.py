from fastapi import Request

from app.config import Settings
from app.services.receipt_service import ReceiptService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_receipt_service(request: Request) -> ReceiptService:
    """Available for a later HTTP integration; current business routes remain 501."""
    return request.app.state.receipt_service
