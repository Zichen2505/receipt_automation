# Receipt Agent

FastAPI serves the existing upload page and authenticated receipt APIs, plus opt-in durable server-to-server extraction jobs. Both workflows reuse structured extraction, discount normalization and deterministic Decimal validation; new jobs have independent persistence, idempotency and interruption recovery and never synchronize to Airtable. Legacy receipt synchronization and response contracts remain unchanged. This milestone implements the extraction-job application contract with offline verification only. No Render service is created or deployed; actual results and historical acceptance are recorded in TASKS.md. Notifications remain disconnected; exports return 501.

Before taking over, read the four files specified in AGENTS.md. Shared models are implemented only in app/schemas/receipt.py. AIRTABLE_SCHEMA.md at this project root is the sole authority for Airtable mappings; preserve the supplied v1.1 document unchanged. Actual verification results and future tasks are in TASKS.md.

## Durable extraction jobs

The application developer's complete contract and future NEW isolated Render
service checklist are in [docs/EXTRACTION_API_HANDOFF.md](docs/EXTRACTION_API_HANDOFF.md).
POST /api/v1/extractions accepts one PDF with a client-persisted canonical UUID
in Idempotency-Key; GET /api/v1/extractions/{request_id} reads durable status.
Creation returns 202 without waiting for the model; identical terminal retries
return 200. Never create a new UUID automatically after a timeout or GET 404.
The application must authorize employee/document ownership before proxying calls
and preserve the entire extraction snapshot before employee corrections.

Jobs are disabled by default. Enabling EXTRACTION_JOBS_ENABLED=true requires a
dedicated EXTRACTION_API_KEY (different from APP_API_KEY), stable
EXTRACTION_INTEGRATION_SCOPE, MODEL_API_KEY and MODEL_NAME. Existing APP_API_KEY
startup/legacy authentication stays required. New credentials are server-only.
Persist DATA_DIR with one instance/process/worker; jobs live in its separate
extraction_jobs directory. Defaults: EXTRACTION_MAX_ACTIVE_JOBS=32,
EXTRACTION_CONCURRENCY=1, EXTRACTION_SHUTDOWN_GRACE_SECONDS=10. Queued work resumes
after restart; uncertain processing becomes unknown without automatic resend.
No new UI, employee/approval/payment database, reset/retry endpoint or external
worker is added. Leave all Airtable settings absent on the proposed isolated
service. Deployment and live model requests require a future explicit assignment.

```powershell
.\.venv\Scripts\python -B scripts\offline_regression.py tests/test_extraction_jobs.py
```

The upload-page, receipt API and older deployment notes below describe the
preserved legacy workflow. Use the new handoff's branch/configuration/checklist
for future extraction-service preparation, not its historical Airtable checklist.

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

In another window run `Invoke-RestMethod http://localhost:8000/health`. Open the upload page at http://localhost:8000/ (adjust PORT if configured). Interactive API documentation is at http://localhost:8000/docs . Receipt requests require X-API-Key; stop with Ctrl+C.

## Upload page

1. Open `/` on the running FastAPI server and enter your application access key.
2. Select one PDF and choose **Upload PDF**. The controls are disabled while the request is pending.
3. Review extracted details, ordered line items and validation issues. **Saved locally** and **Synced to Airtable** are separate outcomes; synchronization is confirmed only when the API returns `sync.status=synced`.

The page uses plain HTML/CSS/JavaScript under app/web, with no frontend build or framework. Its assets are served at `/web/upload.js` and `/web/style.css`. It sends the entered key only in X-API-Key, never in the URL or multipart body. The application does not persist the key in browser storage; autocomplete is disabled and navigation clears the input. MODEL_API_KEY and AIRTABLE_TOKEN stay on the backend. Response content is displayed as text, including model-derived merchant names, items and validation messages.

The page handles access rejection, invalid/encrypted/oversized PDFs, needs_review, every existing sync state, stored technical failures and unknown outcomes. A failed/unknown sync does not erase local saving. A 504, connection interruption or the page's 180-second request timeout may leave processing active: no local/sync success is inferred. There are no automatic resubmissions or polling. Wait for processing to finish before deliberately submitting the identical PDF to retrieve its stored result; existing backend deduplication/reconciliation rules still apply. Unknown synchronization requires operator reconciliation. This minimal page has no receipt lookup, retry-sync, export or notification controls.

Starting the normal app and submitting a new PDF uses the real production integrations. For this assignment, verification uses only the offline test server and mocks below; no real model or Airtable request is authorized.

```powershell
.\.venv\Scripts\python -B scripts\offline_regression.py tests/test_web_page.py tests/test_web_browser.py
```

Browser tests use the pinned Playwright development dependency and an already installed Chrome (`RECEIPT_BROWSER_CHANNEL` defaults to `chrome`; `msedge` can select installed Edge). They run a temporary loopback Uvicorn server, select the user-provided development A.pdf with a real browser file chooser event, submit multipart HTTP, and render injected synthetic extraction/simulated Airtable results. Additional mocked API states cover errors, sync, XSS-safe text, duplicate submission, timeout, null/zero values, mobile layout and key handling. Browser tests explicitly skip when required tooling/browser or the supplied A.pdf is missing. No browser binary is downloaded by the tests. Logs, browser version and a screenshot are retained under the runner's new ignored data/http_api/ directory. Servers and browser contexts are closed after verification.

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

## Render and Docker preparation (not deployed)

Use the separately pushed chore/render-predeploy branch, based on the existing
upload-page version; do not default to main. The repository root already contains
Dockerfile and app/, so Render Root Directory stays blank, Docker build context
is ., and Dockerfile Path is ./Dockerfile. Select Docker, leave Docker Command
blank to use python -m app.main, use /health, one instance/worker without reload,
and mount a persistent disk at /app/data with DATA_DIR=/app/data. The application
listens on 0.0.0.0 and reads PORT. No Render service or deployment is authorized.

Full field/environment checklist, disk permissions, offline Docker reproduction
and limits: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Required production variable
names are APP_API_KEY, MODEL_API_KEY, MODEL_NAME, AIRTABLE_TOKEN, AIRTABLE_BASE_ID,
AIRTABLE_TABLE_ID and DATA_DIR; honor platform PORT. Optional limits/timeouts are
MAX_UPLOAD_BYTES, MAX_PDF_PAGES, HTTP_WAIT_TIMEOUT_SECONDS and
AIRTABLE_TIMEOUT_SECONDS. Model/Airtable variables are needed for their respective
business operations, not startup/health. Startup still requires APP_API_KEY;
/health requires no request key and calls neither service. No .env file is required.

Dockerfile installs all pinned runtime requirements, runs pip check and includes
the page/static assets. The build context permits requirements.txt and app/
sources only, then excludes nested credentials, local state, PDFs and evidence.
The verification harness/substitutes are excluded from the image and normal CMD.
Database results, extraction metadata, sync status/IDs and original PDFs reside
under the persistent DATA_DIR. Same-database duplicate protection survives a
container replacement only when that directory is reused. Cross-database
deduplication is a known limitation and is not fixed in this phase.

The initial preparation could not reach Docker Engine. The follow-up acceptance
on 2026-10-28 built commit df878d852a88f548bf42aa5f20fe8a49119704b3 with
Docker Desktop Linux Engine and passed all existing container checks, including
default startup/assets/health/auth/write access, simulated upload/query and
recreated-container persistence/deduplication. All containers had networking
disabled; real model/Airtable calls were zero. The image's 30 application files
matched the authorized source manifest exactly. Evidence remains local under
data/docker/20261028T220021Z_dcff829b/. To reproduce with Linux Docker Engine
and the unchanged user-provided development A.pdf present:

```powershell
.\.venv\Scripts\python -B scripts/docker_acceptance.py
```

This builds the production image, mounts a new isolated evidence/data directory,
checks default startup/assets/health/auth/write access, injects synthetic extraction
and simulated Airtable for upload/query, then recreates the default production
container with the same store and checks persisted results/deduplication. Containers
have no network; no real service key is forwarded. Results/logs/data remain ignored
under data/docker/. Exit 2 explicitly reports an unavailable Engine. Local helper
tests do not count as container acceptance. The minimal GitHub Actions workflow
runs guarded clean-clone offline suites and a Docker build without service secrets;
its remote run status is not established by the local checks. Actions for the
accepted commit remains UNCONFIRMED: GitHub CLI was unauthenticated and the
credential-free Actions API request could not connect. No Render service was
created or deployed. The follow-up delivery changes documentation only.

For optional local Compose usage when Docker is available:

```powershell
Copy-Item .env.example .env
# Edit .env locally and set a real APP_API_KEY; do not commit the file.
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
docker compose down
```

Docker Engine must be running. This optional Compose configuration reads .env;
Render uses injected environment variables directly. The port follows PORT.
Named volume receipt-data mounts at /app/data. Stopping containers retains the
volume; avoid down -v. Containers run as UID/GID 10001. Local isolated bind-mount
permissions and persistence passed; Render disk behavior is unverified. Do not upload
new PDFs to the default app during offline acceptance: it uses real integrations.
