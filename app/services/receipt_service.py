"""Single-process workflow with optional Airtable synchronization after local commit."""
import asyncio
from collections.abc import Awaitable, Callable
import hashlib
import os
from pathlib import Path
import weakref
from uuid import uuid4

from app.contracts import ReceiptStorageError
from app.integrations import extractor as model_extractor
from app.integrations.airtable import AirtableClient
from app.schemas.receipt import ExtractionMetadata, ProcessingMetadata, ReceiptData, ReceiptResponse, SyncResult
from app.services.validation import validate_receipt
from app.storage import files, repository

# One event loop/process is supported. Instances on that loop share a DATA_DIR gate.
_runtimes = weakref.WeakKeyDictionary()


class ReceiptService:
    def __init__(self, data_dir: Path, *, extractor: Callable[[bytes, str], Awaitable[ReceiptData]] | None = None,
                 airtable: AirtableClient | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "receipts.sqlite3"
        self.extractor = extractor
        self.airtable = airtable

    def _runtime(self) -> dict:
        per_loop = _runtimes.setdefault(asyncio.get_running_loop(), {})
        return per_loop.setdefault(self.data_dir, {"lock": asyncio.Lock(), "ready": False})

    async def _initialize(self, runtime: dict) -> None:
        if not runtime["ready"]:
            try:
                await asyncio.to_thread(repository.initialize_database, db_path=self.db_path, data_dir=self.data_dir)
            except Exception:
                raise ReceiptStorageError("Local storage initialization failed") from None
            runtime["ready"] = True

    async def start(self) -> None:
        runtime = self._runtime()
        async with runtime["lock"]:
            await self._initialize(runtime)

    async def get_receipt(self, receipt_id: str) -> ReceiptResponse | None:
        runtime = self._runtime()
        async with runtime["lock"]:
            await self._initialize(runtime)
            try:
                return await asyncio.to_thread(repository.get_receipt, receipt_id, db_path=self.db_path)
            except Exception:
                raise ReceiptStorageError("Local receipt query failed") from None

    async def process_receipt(self, pdf_bytes: bytes, filename: str) -> ReceiptResponse:
        # Keep ownership until the workflow finishes, even if an awaiting caller cancels.
        task = asyncio.create_task(self._process(pdf_bytes, filename))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _process(self, pdf_bytes: bytes, filename: str) -> ReceiptResponse:
        runtime = self._runtime()
        async with runtime["lock"]:
            await self._initialize(runtime)
            digest = await asyncio.to_thread(lambda: hashlib.sha256(pdf_bytes).hexdigest())
            try:
                record, owner = await asyncio.to_thread(repository.claim_receipt, str(uuid4()), digest, db_path=self.db_path)
            except Exception:
                raise ReceiptStorageError("Local receipt reservation failed") from None
            if not owner:
                if record.response.status == "processing":
                    raise ReceiptStorageError("Unresolved processing ownership; restart required for recovery")
                return await self._sync_saved(record.response)
            response = record.response
            metadata = ProcessingMetadata()
            reference = None
            phase = "original_save_failed"
            try:
                reference = await asyncio.to_thread(files.save_original_pdf, pdf_bytes, response.receipt_id, data_dir=self.data_dir)
                await asyncio.to_thread(repository.attach_original, response.receipt_id, reference, db_path=self.db_path)
                phase = "extraction_failed"
                if self.extractor is None:
                    data, extraction = await model_extractor.extract_with_metadata(pdf_bytes, filename)
                else:
                    raw = await self.extractor(pdf_bytes, filename)
                    data, events = model_extractor.normalize_receipt_data(raw)
                    extraction = ExtractionMetadata(raw_output=raw.model_dump_json(), normalizations=events)
                metadata.extraction = extraction
                response.data = data
                phase = "validation_failed"
                response.validation = await asyncio.to_thread(validate_receipt, data)
                response.status = "saved" if response.validation.passed else "needs_review"
                phase = "result_save_failed"
                await asyncio.to_thread(repository.save_receipt, response, db_path=self.db_path,
                                        original_pdf_ref=reference, metadata=metadata)
            except asyncio.CancelledError:
                runtime["ready"] = False
                raise
            except Exception:
                response.status = "failed"
                response.validation.passed = False
                metadata.failure_code = phase
                try:
                    await asyncio.to_thread(repository.save_receipt, response, db_path=self.db_path,
                                            original_pdf_ref=reference, metadata=metadata)
                except Exception:
                    runtime["ready"] = False
                    raise ReceiptStorageError("Processing failed and failure state could not be committed") from None
                return response
            # The extraction/local-save error handler must never catch sync failures.
            return await self._sync_saved(response)

    async def retry_sync(self, receipt_id: str) -> ReceiptResponse | None:
        task = asyncio.create_task(self._retry_sync(receipt_id))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _retry_sync(self, receipt_id: str) -> ReceiptResponse | None:
        runtime = self._runtime()
        async with runtime["lock"]:
            await self._initialize(runtime)
            try:
                response = await asyncio.to_thread(repository.get_receipt, receipt_id, db_path=self.db_path)
            except Exception:
                raise ReceiptStorageError("Local receipt query failed") from None
            return await self._sync_saved(response) if response else None

    async def _sync_saved(self, response: ReceiptResponse) -> ReceiptResponse:
        if (self.airtable is None or response.status != "saved" or not response.validation.passed
                or response.data is None or response.sync.status == "synced"):
            return response

        async def persist(sync: SyncResult) -> ReceiptResponse:
            try:
                return await asyncio.to_thread(repository.update_sync, response.receipt_id, sync, db_path=self.db_path)
            except Exception:
                raise ReceiptStorageError("Local synchronization state could not be committed; local receipt retained") from None

        uncertain = response.sync.status in {"unknown", "pending"}
        if not self.airtable.configured:
            return response if uncertain else await persist(SyncResult(status="not_configured"))
        await persist(SyncResult(status="unknown" if uncertain else "pending"))

        async def before_create() -> None:
            await persist(SyncResult(status="unknown"))

        result = await self.airtable.sync_receipt(response, allow_create=not uncertain, before_create=before_create)
        return await persist(result)


async def process_receipt(pdf_bytes: bytes, filename: str) -> ReceiptResponse:
    return await ReceiptService(Path(os.getenv("DATA_DIR", "./data"))).process_receipt(pdf_bytes, filename)
