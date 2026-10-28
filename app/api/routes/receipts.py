from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.auth import require_api_key
from app.schemas.receipt import ReceiptResponse

router = APIRouter(prefix="/api/v1/receipts", dependencies=[Depends(require_api_key)])


def unimplemented() -> None:
    raise HTTPException(status_code=501, detail={
        "code": "not_implemented", "message": "Receipt processing is not implemented in phase 1"
    })


@router.post("", response_model=ReceiptResponse)
async def upload_receipt(file: Annotated[UploadFile, File()]) -> ReceiptResponse:
    unimplemented()


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(receipt_id: str) -> ReceiptResponse:
    unimplemented()


@router.get("/{receipt_id}/export")
async def export_receipt(receipt_id: str, format: Literal["json", "csv"] = "json"):
    unimplemented()
