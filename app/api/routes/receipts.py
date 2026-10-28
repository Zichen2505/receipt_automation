from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.auth import require_api_key
from app.api.operations import wait_for_operation
from app.api.uploads import read_pdf
from app.config import Settings
from app.dependencies import get_receipt_service, get_settings
from app.schemas.receipt import ReceiptResponse
from app.services.receipt_service import ReceiptService

router = APIRouter(prefix="/api/v1/receipts", dependencies=[Depends(require_api_key)])


def unimplemented() -> None:
    raise HTTPException(status_code=501, detail={
        "code": "not_implemented", "message": "Receipt export is not implemented"
    })


@router.post("", response_model=ReceiptResponse, responses={
    400: {"description": "Empty file or malformed multipart body"},
    401: {"description": "Missing or invalid X-API-Key"},
    413: {"description": "File, page or multipart body limit exceeded"},
    415: {"description": "Unsupported file media type or missing PDF header"},
    422: {"description": "Invalid parameters, encrypted or unreadable PDF"},
    500: {"description": "Sanitized internal error; outcome unknown"},
    502: {"model": ReceiptResponse, "description": "Durably stored technical failure"},
    503: {"description": "Storage unavailable; outcome unknown"},
    504: {"description": "HTTP waiting timed out; processing continues and outcome is unknown"},
})
async def upload_receipt(
    request: Request,
    file: Annotated[UploadFile, File()],
    service: Annotated[ReceiptService, Depends(get_receipt_service)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    pdf_bytes = await read_pdf(file, settings)
    response = await wait_for_operation(
        request, service.process_receipt(pdf_bytes, file.filename or "upload.pdf"),
        timeout_code="processing_timeout")
    if response.status == "failed":
        return JSONResponse(status_code=502, content=response.model_dump(mode="json"))
    return response


@router.get("/{receipt_id}", response_model=ReceiptResponse, responses={
    401: {"description": "Missing or invalid X-API-Key"},
    404: {"description": "Receipt not found"},
    500: {"description": "Sanitized internal error"},
    503: {"description": "Storage unavailable"},
    504: {"description": "Query waiting timed out; no receipt outcome is inferred"},
})
async def get_receipt(
    receipt_id: str, request: Request,
    service: Annotated[ReceiptService, Depends(get_receipt_service)],
) -> ReceiptResponse:
    response = await wait_for_operation(request, service.get_receipt(receipt_id), timeout_code="query_timeout")
    if response is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Receipt was not found"})
    return response


@router.get("/{receipt_id}/export")
async def export_receipt(receipt_id: str, format: Literal["json", "csv"] = "json"):
    unimplemented()


@router.post("/{receipt_id}/sync", response_model=ReceiptResponse, responses={
    401: {"description": "Missing or invalid X-API-Key"},
    404: {"description": "Receipt not found"},
    503: {"description": "Synchronization state storage unavailable; local receipt retained"},
    504: {"description": "Sync waiting timed out; operation continues and outcome is unknown"},
})
async def retry_receipt_sync(
    receipt_id: str, request: Request,
    service: Annotated[ReceiptService, Depends(get_receipt_service)],
) -> ReceiptResponse:
    response = await wait_for_operation(request, service.retry_sync(receipt_id), timeout_code="sync_timeout")
    if response is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Receipt was not found"})
    return response
