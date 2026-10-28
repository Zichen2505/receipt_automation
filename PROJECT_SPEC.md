# PDF receipt processing specification

Current phase: 3. Discount normalization, deterministic validation, atomic local PDF storage, SQLite records/query/recovery, and local service orchestration are implemented. Verification is entirely offline, using historical real model outputs as injected test substitutes. No new real model end-to-end run is claimed. Business HTTP routes remain explicitly unimplemented (501). Airtable, notifications, UI, exports, and deployment are outside this phase.

## Architecture and ownership

Single instance, single process, single asyncio event loop. API owns HTTP/authentication/parameters; Service orchestrates; Integration adapts model/external data; Storage owns SQLite and files. No microservices, task queues, or multi-Agent orchestration.

Final product flow remains upload → extraction → validation → local save → eligible Airtable synchronization → notification event → response. Phase 3 implements only the local workflow, without connecting it to business HTTP routes. saved means locally committed and validation passed, never reimbursement/payment approval.

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

GET /health stays unauthenticated and returns 200. Startup validates APP_API_KEY/PORT/DATA_DIR, initializes SQLite and recovery, and exposes the service through app.state and get_receipt_service for later integration. POST /api/v1/receipts, GET /api/v1/receipts/{id}, and export remain authenticated 501 placeholders; invalid keys return 401 and invalid parameters 422. The repository/service can query locally, but the HTTP query route is not connected yet. Future query/export behavior (including 404) is not claimed now.

Environment names remain APP_API_KEY, MODEL_API_KEY, MODEL_NAME, DATA_DIR, PORT, AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID. App imports do not require configuration, and HTTP startup does not load .env. SDK credentials are required only if the actual extraction boundary is invoked. No model request was authorized or made during phase 3.

## Offline verification and evidence

Only tests/scripts explicitly inject historical real A/B/C/D/F outputs. Production app modules contain no experiment/expected paths. tests/test_phase3.py covers normalization, Decimal conflicts, five-sample workflow, cross-instance concurrent deduplication, database unique contention, fresh-interpreter querying, originals, failure handling, cancellation, and crash recovery. Existing development-schema compatibility and HTTP regressions remain in the full offline suite.

scripts.phase3_offline_acceptance is an explicitly offline acceptance harness, not a production data source. It saves new evidence under data/phase3/<run_id>/ without changing earlier phase 2/2B evidence or original inputs/answers. Its local-store is isolated from default production records.

Current offline result: A/B/C/D saved; F needs_review with missing_currency. D discount becomes 7.10 and all other fields/items match the prior data/answer. This does not constitute new real model end-to-end verification.

Deploy as one worker on 0.0.0.0 with PORT (default 8000), without reload; persist DATA_DIR=/app/data in Docker. Docker build/startup, volume permissions, restart signals, and deployment remain unverified. See docs/DEPLOYMENT.md and TASKS.md for limits and actual results.
