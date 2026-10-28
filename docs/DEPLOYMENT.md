# Deployment conventions (not deployed)

## Local storage and upload/query API update

The local service now creates receipts.sqlite3 and originals/*.pdf in DATA_DIR.
HTTP upload/query routes now delegate to that service; exports remain 501.
No real model-backed HTTP end-to-end run or deployment has been performed.
The settings below remain intended deployment
conventions, not evidence of a verified Docker run.

Use one process, one asyncio event loop, one worker, and one instance for a given
DATA_DIR. Workflow coordination is process-local; a second process/loop is not
supported, even though the database independently enforces unique PDF hashes.
Do not use reload against a live data directory. Startup changes leftover
processing rows to failed, preserves IDs and matching originals, and never
automatically calls the model again. Duplicates of failed PDFs return the same
failed result; no automatic reset/retry is implemented.

Originals use same-directory temporary writes, file fsync and atomic replace;
POSIX also fsyncs the original directory. SQLite uses synchronous=FULL and short
transactions. These do not make files and SQLite one atomic transaction, nor
prove power-loss durability on an unverified platform. Detailed recovery ordering
is specified in PROJECT_SPEC.md. Crash-left temporary/unreferenced files are
retained for deliberate maintenance; do not delete them or terminal originals
without checking their database ownership and backups. External corruption or
deletion of terminal originals is not automatically repaired.

The previous deployment conventions follow.

Build from receipt-agent/Dockerfile using Python 3.12.10 and pinned dependencies in requirements.txt. Run `python -m app.main` as PID 1 using exec form, designed for normal SIGTERM shutdown. Listen on 0.0.0.0 with one worker and no reload. The health check uses Python's standard library without curl. Actual container shutdown remains unverified.

Set PORT (default 8000) and route platform ingress to that same port. Inject APP_API_KEY through platform secret variables. Set MODEL_API_KEY and MODEL_NAME for new production extractions. Airtable synchronization is now connected for eligible saved records when AIRTABLE_TOKEN, AIRTABLE_BASE_ID and AIRTABLE_TABLE_ID are all nonblank. Missing configuration returns not_configured without a remote request. The PAT needs record read/write access to the existing intended base/table, without schema write scopes. The six fields must already match AIRTABLE_SCHEMA.md. Do not change the destination for an existing DATA_DIR; no destination migration exists. AIRTABLE_TIMEOUT_SECONDS defaults to 15 per request. Imports/ASGI startup read process environment only. The optional local command python -m app.main --env-file .env explicitly loads the named file without overriding variables or interpolation; deployment should inject variables directly instead. Do not place secrets in image build arguments, frontend assets, or logs. Public ingress should provide HTTPS and retain X-API-Key. Upload/query/sync retry are implemented, while real Airtable, live model-backed HTTP processing and platform behavior remain unverified and unauthorized for this offline assignment.

Set DATA_DIR=/app/data and mount a persistent disk there. SQLite receipts.sqlite3, originals/*.pdf, and future notification events all reside on that volume. The image directory belongs to UID/GID 10001. Platform mounts may override its permissions; initialize volume ownership/write access for 10001:10001. Grant only required permissions; do not use global 777. Startup creates the directory and probes temporary write access; an unwritable directory fails startup. Windows bind mounts and platform volume permissions require actual verification. Compose uses a named volume.

Run only one replica and one process. Do not scale horizontally or place SQLite on a shared filesystem without reliable file locking. MAX_UPLOAD_BYTES (default 10485760), MAX_PDF_PAGES (20), and HTTP_WAIT_TIMEOUT_SECONDS (130) configure admission and waiting; all must be positive, with a finite timeout. The total multipart envelope permits an extra 65536 bytes. Configure ingress limits consistently; PDF parsing is not resource-isolated and upload/parsing have no application deadline. A 504 leaves the receipt outcome unknown and does not cancel processing. Retained service calls continue after HTTP timeout/disconnection, and graceful lifespan shutdown waits for them. Ingress/grace periods must accommodate the 120-second model deadline plus queued lock/storage time. Forced termination relies on startup recovery; these shutdown/volume behaviors have not been verified in a deployed environment.

Persistent storage needs independent backups and recovery exercises. Future SQLite backups must be consistent and include corresponding PDFs. The container writable layer can be lost on replacement. Without a persistent disk, do not claim files are reliably saved. Do not delete volumes containing production data.

Synchronization retains saved and commits pending/unknown/synced/failed separately in response_json. Startup converts leftover pending to unknown without contacting Airtable. Use authenticated POST /api/v1/receipts/{receipt_id}/sync for model-free retry. Unknown only queries ReceiptID and never recreates on an empty result; manual reconciliation under a future assignment is required if ambiguity persists. There is no automatic scheduler or global rate limiter; wait at least 30 seconds after 429. HTTP retry timeout returns 504/sync_timeout while retained work continues. Grace periods must accommodate both model and up to two Airtable requests plus lock/storage time. Confirmed record IDs are not remotely re-audited. Independent writers, multiple databases and changing destinations can defeat ReceiptID uniqueness; single-process operation and backups remain mandatory. See PROJECT_SPEC.md for complete behavior.

The build context excludes .env, runtime data, all tests, PDFs, caches, and private/held-out paths. Never copy evaluation data into the build context or image. Docker build and startup remain unverified; see TASKS.md.
