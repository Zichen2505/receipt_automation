"""Canonical models. Decimal amounts serialize as JSON strings, including nulls."""
from datetime import date as Date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReceiptItem(Schema):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


class ReceiptData(Schema):
    merchant: str | None = None
    date: Date | None = None
    receipt_number: str | None = None
    currency: str | None = None
    total: Decimal | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    discount: Decimal | None = None
    items: list[ReceiptItem] | None = None


class ValidationIssue(Schema):
    code: str
    field: str
    message: str


class ValidationResult(Schema):
    passed: bool
    issues: list[ValidationIssue]


class SyncResult(Schema):
    status: Literal["not_configured", "pending", "synced", "failed", "skipped", "unknown"]
    record_id: str | None = None


class NotificationResult(Schema):
    status: Literal["not_sent", "recorded", "failed"]
    event_id: str | None = None


class ReceiptResponse(Schema):
    receipt_id: str
    status: Literal["processing", "saved", "needs_review", "failed"]
    data: ReceiptData | None
    validation: ValidationResult
    sync: SyncResult
    notification: NotificationResult


class NormalizationEvent(Schema):
    field: Literal["discount"] = "discount"
    original_value: Decimal | None
    normalized_value: Decimal | None
    reason: str


class ExtractionMetadata(Schema):
    raw_output: str | None = None
    normalizations: list[NormalizationEvent] = Field(default_factory=list)
    model: str | None = None
    response_id: str | None = None
    usage: dict[str, Any] | None = None
    elapsed_seconds: float | None = None


class ProcessingMetadata(Schema):
    extraction: ExtractionMetadata | None = None
    failure_code: str | None = None
    recovery_reason: str | None = None


class StoredReceipt(Schema):
    response: ReceiptResponse
    pdf_sha256: str
    original_pdf_ref: str | None
    metadata: ProcessingMetadata
    created_at: str
    updated_at: str


class ExtractionVersion(Schema):
    pipeline_version: str
    pipeline_sha256: str
    model: str
    prompt_sha256: str
    schema_sha256: str
    request_timeout_seconds: float = 120.0
    max_output_tokens: int = 4096


class ExtractionConfiguration(Schema):
    version: ExtractionVersion
    prompt: str
    output_schema: dict[str, Any]


class ExtractionJobError(Schema):
    code: str
    message: str


class ExtractionJobResponse(Schema):
    request_id: str
    status: Literal["queued", "processing", "completed", "needs_review", "failed", "unknown"]
    created_at: str
    updated_at: str
    data: ReceiptData | None = None
    validation: ValidationResult | None = None
    error: ExtractionJobError | None = None
    extraction_version: ExtractionVersion


class StoredExtractionJob(Schema):
    response: ExtractionJobResponse
    scope: str
    phase: Literal["accepting", "queued", "processing", "completed", "needs_review", "failed", "unknown"]
    pdf_sha256: str
    input_id: str
    original_pdf_ref: str | None = None
    configuration: ExtractionConfiguration
    metadata: ProcessingMetadata = Field(default_factory=ProcessingMetadata)
