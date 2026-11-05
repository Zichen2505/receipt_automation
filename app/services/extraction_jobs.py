"""Lifespan-owned execution with durable admission and conservative interruption recovery."""
import asyncio
from collections.abc import Awaitable, Callable
import hashlib
import logging
from pathlib import Path

from app.config import Settings
from app.contracts import (ExtractionCapacityError, ExtractionConflictError, ExtractionExecutionError,
                           ReceiptStorageError)
from app.integrations import extractor as model_extractor
from app.schemas.receipt import ExtractionJobError, ExtractionMetadata, ReceiptData
from app.services.validation import validate_receipt
from app.storage import extraction_jobs as store, files

logger = logging.getLogger(__name__)


async def io(function, *args, **kwargs):
    """Finish a filesystem/transaction operation before propagating cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class ExtractionJobService:
    def __init__(self, settings: Settings, *, extractor: Callable[[bytes, str], Awaitable[ReceiptData]] | None = None):
        self.settings = settings
        self.data_dir = Path(settings.data_dir).resolve() / "extraction_jobs"
        self.db_path = self.data_dir / "jobs.sqlite3"
        self.scope = settings.extraction_integration_scope
        self.extractor = extractor
        self._accept_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._workers = []
        self._admissions = set()
        self._stopping = False
        self.configuration = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            raise ReceiptStorageError("Extraction execution already started")
        try:
            self.configuration = await io(model_extractor.configuration_snapshot, self.settings.model_name)
            await io(store.initialize, db_path=self.db_path, data_dir=self.data_dir, scope=self.scope)
        except Exception:
            raise ReceiptStorageError("Extraction job initialization failed") from None
        self._started = True
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self.settings.extraction_concurrency)]

    async def close(self) -> None:
        self._stopping = True
        self._wake.set()
        # Accepted inputs finish their durability barrier; no new model work is claimed.
        await asyncio.gather(*tuple(self._admissions), return_exceptions=True)
        if self._workers:
            _, pending = await asyncio.wait(self._workers, timeout=self.settings.extraction_shutdown_grace_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
        try:
            # Also cover cancellation just after the claim transaction committed.
            await io(store.initialize, db_path=self.db_path, data_dir=self.data_dir, scope=self.scope)
        except Exception:
            logger.error("Extraction shutdown recovery requires a later successful startup")

    async def submit(self, request_id: str, pdf_bytes: bytes):
        if self._stopping:
            raise ReceiptStorageError("Extraction service is stopping")
        task = asyncio.create_task(self._accept(request_id, pdf_bytes))
        self._admissions.add(task)

        def finished(done):
            self._admissions.discard(done)
            if not done.cancelled():
                done.exception()  # Consume errors if the HTTP caller disconnected.

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _accept(self, request_id: str, pdf_bytes: bytes):
        digest = await io(lambda: hashlib.sha256(pdf_bytes).hexdigest())
        async with self._accept_lock:
            record = None
            owner = False
            try:
                record, owner = await io(store.reserve, request_id, digest, self.configuration,
                    scope=self.scope, capacity=self.settings.extraction_max_active_jobs, db_path=self.db_path)
                if owner:
                    reference = await io(files.save_original_pdf, pdf_bytes, record.input_id, data_dir=self.data_dir)
                    record = await io(store.ready, request_id, reference, scope=self.scope,
                                      db_path=self.db_path, data_dir=self.data_dir)
                    self._wake.set()
                elif record.phase == "accepting":
                    # Only possible after an earlier failed acceptance in this process.
                    store.mark_unknown(record, "interrupted_acceptance")
                    await io(store.finish, record, db_path=self.db_path)
                return record.response
            except (ExtractionCapacityError, ExtractionConflictError):
                raise
            except Exception:
                if record is not None and owner:
                    try:
                        store.mark_unknown(record, "acceptance_storage_failure")
                        await io(store.finish, record, db_path=self.db_path)
                    except Exception:
                        pass  # The original accepting/queued row remains for restart recovery.
                raise ReceiptStorageError("Job acceptance storage failed; outcome is uncertain") from None

    async def get(self, request_id: str):
        try:
            record = await io(store.get, request_id, scope=self.scope, db_path=self.db_path)
            # A reservation is not an accepted job until the readiness commit.
            return record.response if record and record.phase != "accepting" else None
        except Exception:
            raise ReceiptStorageError("Extraction job query failed") from None

    async def _uncertain(self, record, code):
        store.mark_unknown(record, code)
        try:
            await io(store.finish, record, db_path=self.db_path)
        except Exception:
            # The processing reservation remains durable; startup will mark it unknown.
            logger.error("Extraction job uncertainty could not be committed; restart recovery required")

    async def _worker(self):
        while not self._stopping:
            record = None
            try:
                self._wake.clear()
                record = await io(store.claim_next, scope=self.scope, db_path=self.db_path)
                if record is not None:
                    await self._execute(record)
                    continue
            except asyncio.CancelledError:
                if record is not None:
                    await self._uncertain(record, "shutdown_interrupted")
                raise
            except Exception:
                if record is not None:
                    await self._uncertain(record, "worker_interrupted")
                logger.error("Extraction execution loop encountered a recoverable failure")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.25)
            except TimeoutError:
                pass

    async def _execute(self, record):
        version = record.configuration.version
        if (version.pipeline_version != self.configuration.version.pipeline_version
                or version.pipeline_sha256 != self.configuration.version.pipeline_sha256):
            await self._uncertain(record, "pipeline_version_unavailable")
            return
        try:
            content = await io(store.read_input, record, data_dir=self.data_dir)
        except Exception:
            await self._uncertain(record, "input_unavailable")
            return
        phase = "extraction_failed"
        try:
            if self.extractor is None:
                data, metadata = await model_extractor.extract_configured(content, record.configuration)
            else:
                raw = await self.extractor(content, "receipt.pdf")
                data, events = model_extractor.normalize_receipt_data(raw)
                metadata = ExtractionMetadata(raw_output=raw.model_dump_json(), normalizations=events)
            record.metadata.extraction = metadata
            phase = "validation_failed"
            validation = await io(validate_receipt, data)
            record.response.data, record.response.validation = data, validation
            record.phase = record.response.status = "completed" if validation.passed else "needs_review"
        except Exception as error:
            if isinstance(error, ExtractionExecutionError):
                record.metadata.extraction = error.metadata
            record.phase = record.response.status = "failed"
            record.response.data = record.response.validation = None
            record.response.error = ExtractionJobError(code=phase, message="Extraction could not be completed")
            record.metadata.failure_code = phase
        try:
            await io(store.finish, record, db_path=self.db_path)
        except Exception:
            await self._uncertain(record, "result_storage_failure")
