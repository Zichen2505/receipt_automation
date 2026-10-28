"""Short SQLite transactions; no network operations occur in this module."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from app.contracts import ReceiptStorageError
from app.schemas.receipt import (NotificationResult, ProcessingMetadata, ReceiptResponse,
                                 StoredReceipt, SyncResult, ValidationResult)


@contextmanager
def connection(db_path: Path):
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA synchronous=FULL")
        with db:
            yield db
    finally:
        db.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stored(row) -> StoredReceipt | None:
    if row is None:
        return None
    return StoredReceipt(response=ReceiptResponse.model_validate_json(row["response_json"]),
                         pdf_sha256=row["pdf_sha256"], original_pdf_ref=row["original_pdf_ref"],
                         metadata=ProcessingMetadata.model_validate_json(row["metadata_json"]),
                         created_at=row["created_at"], updated_at=row["updated_at"])


def initialize_database(*, db_path: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with connection(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            pdf_sha256 TEXT NOT NULL UNIQUE CHECK(length(pdf_sha256)=64),
            original_pdf_ref TEXT,
            status TEXT NOT NULL CHECK(status IN ('processing','saved','needs_review','failed')),
            response_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        # Startup is coordinated once per DATA_DIR/event loop, before any model work.
        for row in db.execute("SELECT * FROM receipts WHERE status='processing'").fetchall():
            record = stored(row)
            response = record.response.model_copy(deep=True)
            response.status = "failed"
            response.validation = ValidationResult(passed=False, issues=[])
            response.sync = SyncResult(status="skipped")
            metadata = record.metadata.model_copy(deep=True)
            metadata.failure_code = "interrupted_processing"
            metadata.recovery_reason = "Previous processing did not finish; retained ID, no automatic model retry"
            relative = f"originals/{response.receipt_id}.pdf"
            original = data_dir / relative
            ref = None
            if original.is_file() and not original.is_symlink() and original.resolve().is_relative_to(data_dir.resolve()):
                if hashlib.sha256(original.read_bytes()).hexdigest() == record.pdf_sha256:
                    ref = relative
            db.execute("""UPDATE receipts SET status='failed', response_json=?, metadata_json=?,
                          original_pdf_ref=?, updated_at=? WHERE receipt_id=? AND status='processing'""",
                       (response.model_dump_json(), metadata.model_dump_json(), ref, now(), response.receipt_id))
        for row in db.execute("SELECT * FROM receipts WHERE status='saved'").fetchall():
            response = stored(row).response
            if response.sync.status == "pending":
                response.sync = SyncResult(status="unknown")
                db.execute("UPDATE receipts SET response_json=?, updated_at=? WHERE receipt_id=?",
                           (response.model_dump_json(), now(), response.receipt_id))


def claim_receipt(receipt_id: str, pdf_sha256: str, *, db_path: Path) -> tuple[StoredReceipt, bool]:
    if str(UUID(receipt_id)) != receipt_id:
        raise ValueError("Receipt ID must be a canonical server UUID")
    if not re.fullmatch(r"[0-9a-f]{64}", pdf_sha256):
        raise ValueError("Invalid PDF SHA-256")
    response = ReceiptResponse(receipt_id=receipt_id, status="processing", data=None,
                               validation=ValidationResult(passed=False, issues=[]),
                               sync=SyncResult(status="skipped"), notification=NotificationResult(status="not_sent"))
    timestamp = now()
    with connection(db_path) as db:
        cursor = db.execute("""INSERT INTO receipts
            (receipt_id,pdf_sha256,status,response_json,metadata_json,created_at,updated_at)
            VALUES (?,?,'processing',?,?,?,?) ON CONFLICT(pdf_sha256) DO NOTHING""",
            (receipt_id, pdf_sha256, response.model_dump_json(), ProcessingMetadata().model_dump_json(), timestamp, timestamp))
        record = stored(db.execute("SELECT * FROM receipts WHERE pdf_sha256=?", (pdf_sha256,)).fetchone())
        return record, cursor.rowcount == 1


def get_record(receipt_id: str, *, db_path: Path) -> StoredReceipt | None:
    with connection(db_path) as db:
        return stored(db.execute("SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone())


def get_receipt(receipt_id: str, *, db_path: Path) -> ReceiptResponse | None:
    record = get_record(receipt_id, db_path=db_path)
    return record.response if record else None


def attach_original(receipt_id: str, original_pdf_ref: str, *, db_path: Path) -> None:
    with connection(db_path) as db:
        cursor = db.execute("UPDATE receipts SET original_pdf_ref=?, updated_at=? WHERE receipt_id=? AND status='processing'",
                            (original_pdf_ref, now(), receipt_id))
        if cursor.rowcount != 1:
            raise ReceiptStorageError("Receipt is not owned by this processing attempt")


def save_receipt(receipt: ReceiptResponse, *, db_path: Path, original_pdf_ref: str | None,
                 metadata: ProcessingMetadata) -> None:
    if receipt.status == "processing":
        raise ValueError("Final save requires a terminal status")
    if receipt.status == "saved" and (not receipt.validation.passed or receipt.data is None or original_pdf_ref is None):
        raise ValueError("Saved requires valid data and a stored original")
    if receipt.status == "needs_review" and (receipt.validation.passed or receipt.data is None or original_pdf_ref is None):
        raise ValueError("Needs review requires saved data, original, and validation issues")
    with connection(db_path) as db:
        cursor = db.execute("""UPDATE receipts SET status=?,response_json=?,metadata_json=?,
            original_pdf_ref=?,updated_at=? WHERE receipt_id=? AND status='processing'""",
            (receipt.status, receipt.model_dump_json(), metadata.model_dump_json(), original_pdf_ref, now(), receipt.receipt_id))
        if cursor.rowcount != 1:
            raise ReceiptStorageError("Refusing to overwrite an existing terminal receipt")


def update_sync(receipt_id: str, sync: SyncResult, *, db_path: Path) -> ReceiptResponse:
    """Update only synchronization; preserve the committed local outcome and evidence."""
    with connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        record = stored(db.execute("SELECT * FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone())
        if (record is None or record.response.status != "saved" or not record.response.validation.passed
                or record.response.data is None or record.original_pdf_ref is None):
            raise ReceiptStorageError("Synchronization requires a locally saved validated receipt")
        response = record.response
        if response.sync.status == "synced":
            if response.sync != sync:
                raise ReceiptStorageError("Refusing to overwrite confirmed synchronization")
            return response
        if (sync.status == "synced") != (sync.record_id is not None):
            raise ValueError("Only confirmed synchronization has an Airtable record ID")
        response.sync = sync
        db.execute("UPDATE receipts SET response_json=?, updated_at=? WHERE receipt_id=?",
                   (response.model_dump_json(), now(), receipt_id))
        return response
