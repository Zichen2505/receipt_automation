# Receipt Agent

Authenticated PDF upload and persisted query APIs use the accepted phase 3 local service: discount normalization with audit metadata, deterministic Decimal validation, atomic originals, SQLite, deduplication and interrupted-processing recovery. Eligible saved uploads now attempt Airtable synchronization, persisting record IDs/status with conservative reconciliation and model-free retry. Notifications, UI and deployment remain disconnected; exports return 501. Verification uses offline extractors and simulated HTTP only. No live model/Airtable end-to-end success is claimed.

Before taking over, read the four files specified in AGENTS.md. Shared models are implemented only in app/schemas/receipt.py. AIRTABLE_SCHEMA.md at this project root is the sole authority for Airtable mappings; preserve the supplied v1.1 document unchanged. Actual verification results and future tasks are in TASKS.md.

## Windows local setup (PowerShell, Python 3.12)

```powershell
cd receipt-agent
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:APP_API_KEY = Read-Host 'Enter the local API key'
$env:DATA_DIR = Join-Path $PWD 'data'
$env:PORT = '8000'
.\.venv\Scripts\python -m app.main
```

Do not use the placeholder secret. Imports, ASGI startup and the command above read process environment only and never load .env. For an explicit local dotenv file, copy .env.example to .env, edit it privately, then use `.\.venv\Scripts\python -m app.main --env-file .env`. Only that named file is loaded, without overriding existing environment values and without variable interpolation. An absent requested file is an error. Deployment injects environment variables directly; Compose's env_file supplies process variables before Python starts. Neither environment values nor keys are logged. Startup/query need no model credentials. Processing a new production PDF requires MODEL_API_KEY and MODEL_NAME and invokes the real extraction adapter; only offline substitute tests are authorized for this assignment.

In another window run `Invoke-RestMethod http://localhost:8000/health`. Interactive API documentation is at http://localhost:8000/docs . Receipt requests require X-API-Key; stop with Ctrl+C. No upload page was added.

## Upload and query contract

| Endpoint | Behavior |
| --- | --- |
| POST /api/v1/receipts | Multipart field file; admitted bytes go directly to ReceiptService.process_receipt |
| GET /api/v1/receipts/{receipt_id} | Persisted ReceiptResponse, including failed results; unknown ID returns 404 |
| POST /api/v1/receipts/{receipt_id}/sync | Retry/reconcile persisted synchronization without PDF/model work; unknown ID returns 404 |
| GET /api/v1/receipts/{receipt_id}/export?format=json or csv | Authenticated 501; invalid format 422 |

PDF media type is application/pdf or application/octet-stream; content must have a PDF header and a readable, unencrypted PDF structure with at least one page. Filename suffix is not proof of format. Empty upload: 400; unsupported media/header: 415; malformed/zero-page/encrypted PDF: 422. MAX_UPLOAD_BYTES (default 10485760) and MAX_PDF_PAGES (default 20) are positive integers; exceeding either returns 413. Total multipart bytes, including overhead, are also limited to MAX_UPLOAD_BYTES + 65536 before parsing can spool an unlimited body. Counts do not trust Content-Length; overflow closes existing multipart temporary files. That envelope check can precede authentication and return 413. Parser validation is not a malicious-document sandbox.

Both saved and needs_review return 200 with the existing ReceiptResponse. saved means only locally committed and validation passed. A durably stored technical failed result returns 502 with its ReceiptResponse and queryable ID; an identical resubmission reuses that failure without a new model call. GET of any stored status returns 200. Only saved with validation.passed=true is eligible for Airtable. Ineligible sync stays skipped; notification is always not_sent.

Configure AIRTABLE_TOKEN (PAT with data.records:read/write access to the intended base), AIRTABLE_BASE_ID and AIRTABLE_TABLE_ID through backend environment only. Missing/blank configuration returns sync.status=not_configured without a request. AIRTABLE_TIMEOUT_SECONDS defaults to 15 (finite positive; per request). Existing ReceiptID and the five other columns must already match the unchanged AIRTABLE_SCHEMA.md; the application never modifies remote schema. Do not change the destination for an existing DATA_DIR. No Airtable account was inspected or contacted in this assignment.

Retry with authenticated POST /api/v1/receipts/{receipt_id}/sync, or upload identical PDF bytes again. The service queries ReceiptID before any eligible create and reuses confirmed record_id. Sync errors retain local saved/data/originals. Definite rejection returns sync=failed; POST timeout/ambiguous response returns unknown. An uncertain retry only queries: if no record is visible it remains unknown and requires operator reconciliation, without another create. Existing uncertainty is preserved if configuration is later removed. There is no unsafe reset endpoint, automatic scheduler, or model retry. Wait at least 30 seconds after 429 before retrying. The explicit programmatic ReceiptService without an adapter remains local-only (skipped); the HTTP app always injects a configured-or-unconfigured adapter. See PROJECT_SPEC.md and docs/AIRTABLE_HANDOFF.md for the state machine and limits.

HTTP_WAIT_TIMEOUT_SECONDS (default 130, finite and positive) bounds waiting for Service after admission, including its lock; it also bounds query waiting. A 504 processing_timeout/query_timeout has detail.outcome=unknown and never means failed/completed. Processing is shielded and retained after timeout/disconnection; queries may time out behind it. After processing finishes, resubmit identical bytes to obtain the stable ID/result. No progress or hash-query endpoint exists. The model SDK's own 120-second timeout remains unchanged. Storage unavailable returns sanitized 503; unexpected service errors return sanitized 500; neither claims a terminal outcome. Graceful shutdown waits for retained operations, while forced termination uses startup recovery. Upload reading/PDF parsing are outside the Service wait clock, and the application does not impose a hard process or ingress deadline. See PROJECT_SPEC.md for complete error codes and limits.

```powershell
.\.venv\Scripts\python -B scripts\offline_regression.py
.\.venv\Scripts\python -B acceptance\phase3_independent\run.py --record local-review-01 --snapshot-current
.\.venv\Scripts\python -B acceptance\airtable_independent\run.py --record local-review-01
.\.venv\Scripts\python -m pip check
```

Contract tests use separate temporary directories and labeled synthetic data. User development PDFs belong in tests/fixtures/development/pdfs/ and expected JSON in tests/fixtures/development/expected/. Compatibility tests unwrap data and verify the matching PDF exists. Never translate original receipts or edit expected answers. Do not use private evaluation or held-out answers.

Full historical regression needs the authorized local fixtures and prior phase 2/2B evidence, which deliberately stay outside Git. A fresh clone can run synthetic suites with `scripts\offline_regression.py tests/test_http_receipts.py tests/test_airtable_sync.py`, plus both separate acceptance runners above. The offline regression runner removes application configuration/credentials, blocks real SDK/external network/project .env access (including child interpreters), allows loopback for health checks, and saves fresh ignored results under data/http_api/. Original phase 3 assertions are unchanged; its runner supports a new per-run snapshot instead of replacing the original accepted baseline. All original independent evidence remains local and ignored. The additional Airtable contract suite uses literal oracles and simulated HTTP, written by the same agent rather than an external reviewer. Use a unique --record name; evidence files are exclusive-create. TASKS.md records actual results and handoff.

## Phase 2 verification evidence

The authorized historical text probe and A.pdf request are complete; see TASKS.md for results and artifact paths. The local modules scripts.phase2_probe, scripts.phase2_extract_a, and scripts.phase2_compare_a implement the staged workflow. Do not rerun the first two without an explicit new request: they send paid model requests. Those explicit experiment runners load project-root .env, preserving existing environment values and disabling interpolation, like the new explicitly flagged local API runner. MODEL_API_KEY is passed explicitly to the SDK and MODEL_NAME is used without fallback. Retries are disabled. The independent comparison runner is offline and reads expected/A.json only after actual output is saved. This historical extraction evidence is not a live run of the new HTTP processing API.

Phase 2B is also complete: scripts.phase2b_extract made one request each for B/C/D/F using the unchanged extractor and prompt, without a new text probe or A call. scripts.phase2b_compare is the separate offline step; it compares stored results using Decimal, reports decimal-format-only differences separately, and reuses A's earlier evidence. B/C/F matched; D's printed negative discount was returned as -7.10 while the answer expects the positive magnitude 7.10. This remains a recorded mismatch, not a formatting issue. No paid reruns or prompt changes were made. Detailed five-sample results are in TASKS.md and ignored data/phase2b/ artifacts. Run the full offline suite without exclusions; do not rerun paid scripts without another assignment.

## Phase 3 local workflow

The programmatic entry point is app.services.receipt_service.ReceiptService(data_dir). Its async start/process_receipt/get_receipt methods use the configured directory for receipts.sqlite3 and originals/{receipt_id}.pdf. The module-level process_receipt wrapper uses DATA_DIR. Upload/query routes now delegate to this same service through get_receipt_service. Tests explicitly inject substitutes or mock the production request adapter; no real model call is authorized during this assignment.

Discount is a positive reduction magnitude; only discount is normalized, with original/normalized values and reason retained in metadata. Unknown optional amounts stay null and incomplete formulas are skipped. See PROJECT_SPEC.md for exact validation applicability, concurrency and crash-recovery behavior. Duplicate bytes reuse the same terminal record, including failed records, without a model retry.

The offline script scripts.phase3_offline_acceptance injects historical outputs as test substitutes and creates isolated evidence under data/phase3/. It never invokes the model. TASKS.md links the executed run, including a sample SQLite database and original PDFs. saved here means local storage and business validation passed; it does not mean reimbursement/payment approval or Airtable synchronization.

## Docker (not verified)

```powershell
Copy-Item .env.example .env
# Edit .env locally and set a real APP_API_KEY; do not commit the file.
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
docker compose down
```

Docker Engine must be running. The port follows PORT in .env. Named volume receipt-data mounts at /app/data. Stopping containers retains the volume; avoid `down -v`. Phase 3 local records and originals require this persistent volume; without persistent storage, container files cannot be claimed to be reliably saved. Docker execution remains unverified. Containers run as non-root UID/GID 10001; production must not use reload. Platform configuration, volume permissions, and backup requirements are in docs/DEPLOYMENT.md.
