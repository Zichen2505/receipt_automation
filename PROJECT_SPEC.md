# PDF receipt processing specification

Current phase: authenticated upload/query API integration on the accepted phase 3 local workflow. Discount normalization, deterministic validation, atomic local PDF storage, SQLite records/query/recovery, and service orchestration are reused. HTTP uploads use the production service path; verification injects substitute extractors and never calls real models. Airtable, notifications, UI, exports, and deployment remain outside this assignment; exports return 501.

## Architecture and ownership

Single instance, single process, single asyncio event loop. API owns HTTP/authentication/parameters; Service orchestrates; Integration adapts model/external data; Storage owns SQLite and files. No microservices, task queues, or multi-Agent orchestration.

Final product flow remains upload → extraction → validation → local save → eligible Airtable synchronization → notification event → response. The current HTTP integration reaches the local workflow only. saved means locally committed and validation passed, never reimbursement/payment approval or synchronization.

Shared data structures are defined only in app/schemas/receipt.py. AIRTABLE_SCHEMA.md remains the unchanged sole authority for Airtable mappings.

## Data and normalization

ReceiptData and ReceiptItem retain the existing fields and JSON contract: unknown values are null, money and quantity are Decimal internally and strings in JSON, dates are YYYY-MM-DD, and no invented zeros. Backend receipt_id is distinct from merchant receipt_number and Airtable record IDs.

discount represents a positive reduction magnitude:
total = subtotal - discount + tax + tip.
At the model-to-ReceiptData adapter boundary, only a non-null explicit discount is converted with Decimal.copy_abs(); null stays null. All other amounts are unchanged. The operation is idempotent and does not mutate caller data. NormalizationEvent records the original value, normalized value, and reason, including already-positive/zero and unknown cases.

parse_extraction_with_metadata keeps the exact raw model text in ExtractionMetadata and returns normalized ReceiptData. Existing parse_extraction/extract signatures remain compatible. Metadata includes normalization events, model/response ID/usage when available, and elapsed time. The production path never reads historical experiment output or expected answers. An explicitly injected test extractor can return raw ReceiptData; Service applies the same boundary normalization and records its pre-normalization JSON.

Additional shared models:
- ExtractionMetadata: raw_output, normalizations, model, response_id, usage, elapsed_seconds.
- ProcessingMetadata: extraction, failure_code, recovery_reason.
- StoredReceipt: response, pdf_sha256, original_pdf_ref, metadata, created_at, updated_at.

ReceiptResponse remains receipt_id/status/data/validation/sync/notification with its existing state values. Internal processing metadata is not added to its external shape.

## Fixed and extended interfaces

| Module/class | Signature | Execution |
| --- | --- | --- |
| integrations.extractor | extract(pdf_bytes: bytes, filename: str) -> ReceiptData | async |
| integrations.extractor | extract_with_metadata(pdf_bytes: bytes, filename: str) -> tuple[ReceiptData, ExtractionMetadata] | async |
| integrations.extractor | normalize_receipt_data(data: ReceiptData) -> tuple[ReceiptData, list[NormalizationEvent]] | sync, pure |
| integrations.extractor | parse_extraction_with_metadata(response: Response) -> tuple[ReceiptData, ExtractionMetadata] | sync |
| services.validation | validate_receipt(data: ReceiptData) -> ValidationResult | sync |
| services.receipt_service | process_receipt(pdf_bytes: bytes, filename: str) -> ReceiptResponse | async; uses DATA_DIR |
| ReceiptService | ReceiptService(data_dir: Path, *, extractor: async callable returning ReceiptData or None) | explicit local instance; None uses production metadata adapter |
| ReceiptService | start() -> None | async; startup initialization/recovery |
| ReceiptService | process_receipt(pdf_bytes: bytes, filename: str) -> ReceiptResponse | async |
| ReceiptService | get_receipt(receipt_id: str) -> ReceiptResponse or None | async wrapper around synchronous storage |
| storage.repository | initialize_database(*, db_path: Path, data_dir: Path) -> None | sync |
| storage.repository | claim_receipt(receipt_id: str, pdf_sha256: str, *, db_path: Path) -> tuple[StoredReceipt, bool] | sync; bool indicates reservation ownership |
| storage.repository | attach_original(receipt_id: str, original_pdf_ref: str, *, db_path: Path) -> None | sync; processing row only |
| storage.repository | save_receipt(receipt: ReceiptResponse, *, db_path: Path, original_pdf_ref: str or None, metadata: ProcessingMetadata) -> None | sync; guarded terminal commit |
| storage.repository | get_receipt(receipt_id: str, *, db_path: Path) -> ReceiptResponse or None | sync |
| storage.repository | get_record(receipt_id: str, *, db_path: Path) -> StoredReceipt or None | sync; internal evidence |
| storage.files | save_original_pdf(pdf_bytes: bytes, receipt_id: str, *, data_dir: Path) -> str | sync; relative reference |
| integrations.airtable | sync_receipt(receipt: ReceiptResponse) -> str | async, unimplemented |
| integrations.notifier | record_notification(receipt: ReceiptResponse) -> NotificationResult | sync, unimplemented |

save_receipt is now a guarded finalization of a prior claim, not an upsert. It cannot overwrite a terminal result. The interface change and all callers/tests are coordinated here. Monetary JSON strings and all existing API response fields remain unchanged.

## Deterministic validation

Required merchant/date/currency/total generate missing_merchant, missing_date, missing_currency, missing_total for null values (or blank merchant/currency). Zero total is not missing. No field is guessed. Unknown optional values remain null.

All applicable checks use Decimal with precision scaled to the inputs, no float, tolerance, rounding, or absolute-value conversion:
- Complete quantity/unit_price/amount triples must satisfy quantity × unit_price = amount; otherwise item_amount_mismatch at items[i].amount.
- Non-empty item lists with every amount known and a known subtotal must sum to subtotal; otherwise subtotal_mismatch.
- Only when subtotal, discount, tax, tip, and total are all explicitly known, compare subtotal - discount + tax + tip to total; otherwise total_mismatch. Printed total is never replaced.
- Explicit money must be a numeric multiple of 0.01; otherwise invalid_amount_precision. Extra trailing decimal zeros do not cause a precision error. Quantity is not restricted to two decimals.
- A negative discount passed directly to validation produces invalid_discount; normal extraction/service boundaries normalize it first.

Applicability is conservative: a null optional component does not become zero for arithmetic. Partial lines, missing subtotal, null/empty item lists, or unknown total-formula components skip only the affected formula. This can allow a receipt with required fields present but unknown optional components to pass; it does not claim those skipped relationships were verified. These choices are tested and must not silently change in a later phase.

ValidationResult contains passed and structured code/field/message issues. Any business issue produces needs_review. F produces missing_currency. Technical extraction/validation-execution/storage faults are failed, with a sanitized ProcessingMetadata.failure_code rather than invented business issues.

## Persistence and concurrency

All runtime data resides under the configured DATA_DIR, resolved once per service instance:
- receipts.sqlite3: receipts table with receipt_id PRIMARY KEY, pdf_sha256 NOT NULL UNIQUE, original_pdf_ref, status, complete response_json, metadata_json, and UTC created_at/updated_at.
- originals/{server-generated UUID}.pdf: original bytes. Uploaded filenames are only extraction context and never storage paths.

A shared asyncio lock per resolved DATA_DIR on the single event loop serializes local workflows across ReceiptService instances, including callers awaiting the same PDF. It also coordinates startup recovery. Different PDFs are currently serialized too. This is a deliberate single-process implementation, not a task queue. Queries through Service may wait for current processing to finish.

A short transaction claims the SHA-256 before any model call. Duplicates return the existing terminal result and receipt_id, including failed results, without extracting again. A unique DB constraint independently prevents duplicate rows under transaction contention. Different PDFs receive distinct UUIDs. Final writes require status=processing and cannot overwrite a prior terminal result.

Every SQLite operation creates/closes its connection in its executing worker thread, with a 10-second lock timeout and synchronous=FULL. Connections/transactions are closed before awaiting the model. Blocking storage, startup, hashing, and validation operations are invoked through asyncio.to_thread.

The public service method shields ownership from normal caller cancellation, waiting for the owned workflow to finish before propagating cancellation. A forced task/process interruption is handled by recovery; a second process or concurrent event loop for the same DATA_DIR is unsupported and must not be started. There is no distributed lock or multi-process orchestration.

## Atomic originals and failure recovery

Original writes require a canonical UUID and a server-owned originals directory that resolves inside DATA_DIR. A sibling temporary file is written, flushed, fsynced, and atomically replaced into the final path. POSIX directory entries are fsynced; Windows uses file fsync plus os.replace. Existing identical originals are reused; different bytes and symbolic links are rejected. Only the operation's own temporary file is removed on an ordinary exception.

Files and SQLite cannot share one atomic transaction. Ordering is:
1. Commit processing claim with its hash and ID.
2. Atomically save original; commit its reference to the processing row.
3. Extract/normalize and validate outside DB transactions.
4. Commit terminal response and extraction/processing metadata together.
5. Return only after that commit succeeds.

On startup, before processing, every leftover processing row becomes failed with failure_code=interrupted_processing and an explicit recovery reason. The ID/hash reservation is retained and no model retry is made. If the deterministic final original exists inside DATA_DIR and matches its hash, recovery attaches it even if the process died between file replacement and reference commit. If absent/corrupt, its reference is null and no file-save success is claimed. Crash-left temporary files/unreferenced files are retained for deliberate maintenance; they are not treated as receipts or automatically deleted.

An ordinary model/original-save failure commits failed when possible. If final result storage fails, Service tries to commit failed; if that is also impossible it raises sanitized ReceiptStorageError, never saved. The runtime is marked for reinitialization/recovery before its next operation. An unresolved processing owner is an error rather than a trigger to call the model again. No automatic failed-receipt retry/reset is implemented.

Terminal data and originals are read as stored snapshots. External deletion/corruption of a terminal original is not automatically repaired or continuously audited; volume reliability, permissions, backups, and single-process operation remain deployment responsibilities. Power-loss durability and platform-specific volumes have not been verified with Docker or destructive fault tests.

## States and HTTP boundary

processing is a transient local reservation. saved requires locally committed original/data and validation.passed=true. needs_review requires locally stored original/data with business issues. failed indicates a technical failure; if the database itself cannot commit, the service raises ReceiptStorageError.

Phase 3 always uses sync.status=skipped and notification.status=not_sent because those integrations are deferred, even if environment credentials exist. It does not report pending/synced/recorded or execute external side effects.

GET /health stays unauthenticated and returns 200. Startup validates configuration, checks writable DATA_DIR, initializes SQLite/recovery, and exposes the production ReceiptService through app.state and get_receipt_service. Both receipt routes retain X-API-Key authentication. Routes own HTTP/file admission only; Service owns extraction, validation, persistence and deduplication. Service, schema and storage signatures above are unchanged.

POST /api/v1/receipts accepts one multipart field named file. Content-Type must be application/pdf or application/octet-stream (an absent file media type is treated as octet-stream). Filename suffixes do not establish format. Empty files return 400/empty_file; non-PDF headers or unsupported media return 415/unsupported_media_type. Strict pypdf structure parsing runs via asyncio.to_thread before any service call; unreadable/zero-page PDFs return 422/invalid_pdf, and any encrypted PDF returns 422/encrypted_pdf. No repair, password decryption, text extraction or rendering is performed by this admission step.

MAX_UPLOAD_BYTES is a positive integer, default 10485760 (10 MiB); MAX_PDF_PAGES is a positive integer, default 20. Files exceeding these limits return 413/file_too_large or 413/too_many_pages. File bytes are counted in bounded reads independently of metadata. ASGI middleware additionally bounds actual multipart body bytes to MAX_UPLOAD_BYTES + 65536, including fields/headers/boundaries, and returns 413/request_too_large. It does not trust Content-Length and stops parsing/cleans multipart spool files on overflow. The body envelope is checked before dependencies; oversized unauthenticated requests can therefore return 413 before 401. Other malformed multipart bodies return framework 400; missing/invalid parameters return framework 422. These limits do not provide a CPU/memory sandbox for malicious PDF structures, an upload/read deadline, or ingress connection limits.

POST invokes ReceiptService.process_receipt with the actual bytes and filename. A new PDF follows the production metadata extractor unless a test overrides the service dependency with an injected substitute. Both saved and needs_review return HTTP 200 and the unchanged ReceiptResponse shape. A durably stored technical failed result returns HTTP 502 with the same full ReceiptResponse, including its ID; duplicate failed submissions return that same stored result without retrying extraction. A 502 therefore indicates a known local terminal failure, not a guessed timeout outcome. Querying any stored receipt, including failed, returns HTTP 200 and its snapshot. Unknown string receipt IDs return 404/not_found. Internal metadata/raw model text remain outside the response. GET /api/v1/receipts/{id}/export remains authenticated 501 for json/csv and 422 for invalid formats.

HTTP_WAIT_TIMEOUT_SECONDS is a finite positive number, default 130. Its clock starts after file admission when awaiting Service (including lock wait), or when starting a query. If that wait expires, POST returns 504/processing_timeout and GET returns 504/query_timeout, with detail.outcome=unknown and no invented receipt status/ID. The service task is shielded, strongly retained in app.state.http_tasks, and continues after timeout or request cancellation; this set is in-process lifetime bookkeeping, not a queue or external job system. Queries can time out behind an active workflow; they must not return a premature 404. Graceful lifespan shutdown awaits retained tasks. Forced termination still relies on the existing interrupted-processing recovery. Retry the identical PDF bytes after processing completes to retrieve the stable result/ID; do not treat 504 as failed or blindly submit changed bytes. No progress/poll-by-hash endpoint is implemented. The existing model SDK request deadline remains 120 seconds without retries; its actual exception is handled by Service as a technical failure when a failure commit succeeds. Parser, thread scheduling, lock and filesystem durations mean the HTTP wait limit is not a hard process execution deadline.

ReceiptStorageError maps to HTTP 503/storage_unavailable and unexpected service exceptions to 500/internal_error; both have detail.outcome=unknown, sanitized messages and no claim of failed/saved. Framework validation errors retain their native detail structure. Missing/incorrect API keys return 401/unauthorized. Application HTTP errors otherwise use detail.code/message; raw exception text, filenames, credentials and processing audit metadata are not echoed in those errors. Responses always retain sync=skipped and notification=not_sent, even when credentials exist.

Environment names remain APP_API_KEY, MODEL_API_KEY, MODEL_NAME, DATA_DIR, PORT, AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID, plus the three limits above. Imports, Settings.from_env and ASGI lifespan read existing environment variables only and never load .env. For explicit local use, python -m app.main --env-file .env loads only that named file with override=False and interpolate=False before constructing Settings; an absent requested file is an error. Running python -m app.main without the flag or uvicorn app.main:app never implicitly reads dotenv. Deployment injects process environment variables; Compose's existing env_file mechanism injects variables before Python starts. SDK credentials are required only on a new production extraction, not at startup/query/duplicate retrieval. Offline verification uses substitutes; no real model request is authorized or claimed in this assignment.

## Offline verification and evidence

Only tests/scripts explicitly inject historical real A/B/C/D/F outputs; new HTTP and independent acceptance tests use synthetic data. Production app modules contain no experiment/expected paths. tests/test_phase3.py covers normalization, Decimal conflicts, five-sample workflow, cross-instance concurrent deduplication, database unique contention, fresh-interpreter querying, originals, failure handling, cancellation, and crash recovery. tests/test_http_receipts.py uses valid in-memory blank PDFs and injected extractors to verify HTTP admission, processing/query, errors, limits, deduplication, cancellation, timeout continuation and graceful shutdown. The former upload/query 501 regression expectations are superseded; exports/auth/schema and all other historical checks remain.

scripts.phase3_offline_acceptance is an explicitly offline acceptance harness, not a production data source. It saves new evidence under data/phase3/<run_id>/ without changing earlier phase 2/2B evidence or original inputs/answers. Its local-store is isolated from default production records.

Historical phase 3 offline result: A/B/C/D saved; F needs_review with missing_currency. D discount becomes 7.10 and all other fields/items match the prior data/answer. This does not constitute new real model end-to-end verification.

scripts.offline_regression runs pytest tests in a fresh interpreter with application credentials removed, real SDK construction/external connections blocked, project .env access blocked, and inherited guards for child interpreters. Loopback is allowed for the existing actual Uvicorn health check. Results/JUnit/logs go to a new ignored data/http_api/<run_id>/ directory; authorized input/authority hashes are checked before/after. Run acceptance/phase3_independent/run.py --record <unique-name> --snapshot-current for the unchanged independent test assertions against a fresh run-local source snapshot. That option never overwrites the original baseline or original execution evidence; the source/contract is frozen during each run. The accepted phase 3 main commit preserves the original independent test sources. Historical evidence, local paths, databases and real PDFs are not published to Git.

Deploy as one worker on 0.0.0.0 with PORT (default 8000), without reload; persist DATA_DIR=/app/data in Docker. Docker build/startup, volume permissions, restart signals, and deployment remain unverified. See docs/DEPLOYMENT.md and TASKS.md for limits and actual results.
