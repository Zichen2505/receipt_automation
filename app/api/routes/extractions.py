"""Server-to-server extraction contract; no identity or reimbursement authority."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.auth import require_extraction_key
from app.api.uploads import read_pdf
from app.config import Settings
from app.contracts import ExtractionCapacityError, ExtractionConflictError, ReceiptStorageError
from app.dependencies import get_extraction_service, get_settings
from app.schemas.receipt import ExtractionJobResponse
from app.services.extraction_jobs import ExtractionJobService

router = APIRouter(prefix="/api/v1/extractions", dependencies=[Depends(require_extraction_key)])
ERRORS = {
    400: {"description": "Invalid canonical UUID key, empty file or malformed multipart"},
    401: {"description": "Missing or incorrect dedicated X-API-Key"},
    409: {"description": "Request ID already reserved for different PDF bytes"},
    413: {"description": "File, page or total multipart body limit exceeded"},
    415: {"description": "Unsupported media or non-PDF content"},
    422: {"description": "Invalid multipart fields, unreadable or encrypted PDF"},
    429: {"description": "Unfinished-job capacity exhausted; identical known keys still resolve"},
    503: {"description": "Feature disabled or storage unavailable; acceptance may be uncertain"},
}


def canonical_id(value: str | None) -> str:
    try:
        if value is not None and str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise HTTPException(400, detail={"code": "invalid_request_id", "message": "A canonical UUID is required"})


def unavailable():
    raise HTTPException(503, detail={"code": "storage_unavailable",
        "message": "Extraction storage is unavailable", "outcome": "unknown"})


@router.post("", response_model=ExtractionJobResponse, status_code=202,
             responses={200: {"model": ExtractionJobResponse, "description": "Existing terminal job"}, **ERRORS})
async def create_extraction(request: Request, file: Annotated[UploadFile, File()],
    service: Annotated[ExtractionJobService, Depends(get_extraction_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header()] = None):
    request_id = canonical_id(idempotency_key)
    form = await request.form()
    if len(form.multi_items()) != 1 or form.multi_items()[0][0] != "file":
        raise HTTPException(422, detail={"code": "invalid_form", "message": "Exactly one file field is required"})
    content = await read_pdf(file, settings)
    try:
        response = await service.submit(request_id, content)
    except ExtractionConflictError:
        raise HTTPException(409, detail={"code": "content_conflict", "message": "Request ID is reserved for different PDF bytes"}) from None
    except ExtractionCapacityError:
        raise HTTPException(429, detail={"code": "capacity_exceeded", "message": "Extraction job capacity is exhausted"},
                            headers={"Retry-After": "5"}) from None
    except ReceiptStorageError:
        unavailable()
    return JSONResponse(status_code=202 if response.status in {"queued", "processing"} else 200,
                        content=response.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("/{request_id}", response_model=ExtractionJobResponse, responses={404: {"description": "Unknown request ID"}, **ERRORS})
async def get_extraction(request_id: str,
    service: Annotated[ExtractionJobService, Depends(get_extraction_service)]):
    canonical_id(request_id)
    try:
        response = await service.get(request_id)
    except ReceiptStorageError:
        unavailable()
    if response is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Extraction job was not found"})
    return JSONResponse(content=response.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
