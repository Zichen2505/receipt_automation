"""Independent durable job store; short transactions never encompass model work."""
import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

from app.contracts import ExtractionCapacityError, ExtractionConflictError, ReceiptStorageError
from app.schemas.receipt import (ExtractionConfiguration, ExtractionJobError, ExtractionJobResponse,
                                 ProcessingMetadata, StoredExtractionJob)
from app.storage.repository import connection, now


def stored(row) -> StoredExtractionJob | None:
    return StoredExtractionJob.model_validate_json(row["record_json"]) if row else None


def write(db, record: StoredExtractionJob) -> None:
    db.execute("""UPDATE jobs SET phase=?, record_json=? WHERE scope=? AND request_id=?""",
               (record.phase, record.model_dump_json(), record.scope, record.response.request_id))


def mark_unknown(record: StoredExtractionJob, code: str) -> None:
    record.phase = record.response.status = "unknown"
    record.response.updated_at = now()
    record.response.data = record.response.validation = None
    record.response.error = ExtractionJobError(
        code=code, message="Processing is uncertain; controlled operator recovery is required")
    record.metadata.recovery_reason = code


def read_input(record: StoredExtractionJob, *, data_dir: Path) -> bytes:
    expected = f"originals/{record.input_id}.pdf"
    path = data_dir / expected
    if (record.original_pdf_ref != expected or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(data_dir.resolve())):
        raise ReceiptStorageError("Job input is unavailable")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record.pdf_sha256:
        raise ReceiptStorageError("Job input integrity check failed")
    return content


def initialize(*, db_path: Path, data_dir: Path, scope: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    directory = data_dir / "originals"
    directory.mkdir(exist_ok=True)
    if (data_dir.is_symlink() or directory.is_symlink() or db_path.is_symlink()
            or not data_dir.resolve().is_relative_to(data_dir.parent.resolve())):
        raise ReceiptStorageError("Extraction storage must use server-owned directories")
    if os.name != "nt":
        # Persist new directory entries before accepting executable input.
        for path in (data_dir.parent, data_dir, directory):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    with connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1}:
            raise ReceiptStorageError("Unsupported extraction store version")
        db.execute("CREATE TABLE IF NOT EXISTS integration (scope TEXT PRIMARY KEY)")
        existing = db.execute("SELECT scope FROM integration").fetchall()
        if existing and [row[0] for row in existing] != [scope]:
            raise ReceiptStorageError("Extraction store belongs to a different integration scope")
        db.execute("INSERT OR IGNORE INTO integration(scope) VALUES (?)", (scope,))
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            scope TEXT NOT NULL, request_id TEXT NOT NULL,
            phase TEXT NOT NULL CHECK(phase IN
                ('accepting','queued','processing','completed','needs_review','failed','unknown')),
            record_json TEXT NOT NULL, PRIMARY KEY(scope,request_id))""")
        db.execute("CREATE INDEX IF NOT EXISTS jobs_phase ON jobs(scope,phase)")
        db.execute("PRAGMA user_version=1")
        for row in db.execute("SELECT * FROM jobs WHERE phase IN ('accepting','processing','queued')").fetchall():
            record = stored(row)
            if record.phase == "accepting":
                # Keep evidence from a completed rename, but never infer readiness.
                record.original_pdf_ref = f"originals/{record.input_id}.pdf"
                try:
                    read_input(record, data_dir=data_dir)
                except Exception:
                    record.original_pdf_ref = None
                mark_unknown(record, "interrupted_acceptance")
            elif record.phase == "processing":
                mark_unknown(record, "interrupted_processing")
            else:
                try:
                    read_input(record, data_dir=data_dir)
                except Exception:
                    mark_unknown(record, "input_unavailable")
            write(db, record)


def get(request_id: str, *, scope: str, db_path: Path) -> StoredExtractionJob | None:
    with connection(db_path) as db:
        return stored(db.execute("SELECT * FROM jobs WHERE scope=? AND request_id=?", (scope, request_id)).fetchone())


def reserve(request_id: str, digest: str, configuration: ExtractionConfiguration, *,
            scope: str, capacity: int, db_path: Path) -> tuple[StoredExtractionJob, bool]:
    if str(UUID(request_id)) != request_id:
        raise ValueError("A canonical UUID is required")
    timestamp = now()
    record = StoredExtractionJob(
        scope=scope, phase="accepting", pdf_sha256=digest, input_id=str(uuid4()), configuration=configuration,
        response=ExtractionJobResponse(request_id=request_id, status="unknown", created_at=timestamp,
            updated_at=timestamp, extraction_version=configuration.version,
            error=ExtractionJobError(code="acceptance_pending", message="Acceptance is not yet confirmed")))
    with connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        prior = stored(db.execute("SELECT * FROM jobs WHERE scope=? AND request_id=?", (scope, request_id)).fetchone())
        if prior:
            if prior.pdf_sha256 != digest:
                raise ExtractionConflictError()
            return prior, False
        count = db.execute("SELECT count(*) FROM jobs WHERE phase IN ('accepting','queued','processing')").fetchone()[0]
        if count >= capacity:
            raise ExtractionCapacityError()
        db.execute("INSERT INTO jobs(scope,request_id,phase,record_json) VALUES (?,?,'accepting',?)",
                   (scope, request_id, record.model_dump_json()))
    return record, True


def ready(request_id: str, reference: str, *, scope: str, db_path: Path, data_dir: Path) -> StoredExtractionJob:
    with connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        record = stored(db.execute("SELECT * FROM jobs WHERE scope=? AND request_id=?", (scope, request_id)).fetchone())
        if record is None or record.phase != "accepting":
            raise ReceiptStorageError("Job acceptance is no longer owned")
        record.original_pdf_ref = reference
        read_input(record, data_dir=data_dir)
        record.phase = record.response.status = "queued"
        record.response.error = None
        record.response.updated_at = now()
        write(db, record)
    return record


def claim_next(*, scope: str, db_path: Path) -> StoredExtractionJob | None:
    with connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        record = stored(db.execute("SELECT * FROM jobs WHERE scope=? AND phase='queued' ORDER BY rowid LIMIT 1", (scope,)).fetchone())
        if record:
            record.phase = record.response.status = "processing"
            record.response.updated_at = now()
            write(db, record)
        return record


def finish(record: StoredExtractionJob, *, db_path: Path) -> None:
    if record.phase not in {"completed", "needs_review", "failed", "unknown"} or record.phase != record.response.status:
        raise ValueError("A matching terminal outcome is required")
    if record.phase in {"completed", "needs_review"}:
        response = record.response
        if (response.data is None or response.validation is None or record.original_pdf_ref is None
                or response.validation.passed != (record.phase == "completed")):
            raise ValueError("Result and validation must match the terminal outcome")
    record.response.updated_at = now()
    with connection(db_path) as db:
        cursor = db.execute("""UPDATE jobs SET phase=?, record_json=?
            WHERE scope=? AND request_id=? AND phase IN ('accepting','processing')""",
            (record.phase, record.model_dump_json(), record.scope, record.response.request_id))
        if cursor.rowcount != 1:
            raise ReceiptStorageError("Refusing to overwrite a terminal job")
