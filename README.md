# Receipt Agent

PDF receipt processing project at phase 3: the local service implements discount normalization with audit metadata, deterministic Decimal validation, atomic original-PDF storage, SQLite records/query, duplicate protection, and interrupted-processing recovery. Health checks work; authenticated business HTTP endpoints still explicitly return 501. Airtable, notifications, UI, exports, and deployment are not implemented or enabled. Current local workflow verification reuses historical real outputs offline; no new real model end-to-end run is claimed.

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

Do not use the placeholder secret. The HTTP application does not automatically load .env and currently needs no model or Airtable credentials. In another window run `Invoke-RestMethod http://localhost:8000/health`. Interactive API documentation is at http://localhost:8000/docs . Business requests require X-API-Key; POST uses multipart field file. Valid business requests currently return 501. Stop with Ctrl+C.

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pip check
```

Contract tests use separate temporary directories and labeled synthetic data. User development PDFs belong in tests/fixtures/development/pdfs/ and expected JSON in tests/fixtures/development/expected/. Compatibility tests unwrap data and verify the matching PDF exists. Never translate original receipts or edit expected answers. Do not use private evaluation or held-out answers.

## Phase 2 verification evidence

The authorized text probe and A.pdf request are complete; see TASKS.md for results and artifact paths. The local modules scripts.phase2_probe, scripts.phase2_extract_a, and scripts.phase2_compare_a implement the staged workflow. Do not rerun the first two without an explicit new request: they send paid model requests. Only these explicit runners load project-root .env, preserving existing environment values and disabling interpolation. MODEL_API_KEY is passed explicitly to the SDK and MODEL_NAME is used without fallback. Retries are disabled. The independent comparison runner is offline and reads expected/A.json only after actual output is saved. No complete processing API returns saved.

Phase 2B is also complete: scripts.phase2b_extract made one request each for B/C/D/F using the unchanged extractor and prompt, without a new text probe or A call. scripts.phase2b_compare is the separate offline step; it compares stored results using Decimal, reports decimal-format-only differences separately, and reuses A's earlier evidence. B/C/F matched; D's printed negative discount was returned as -7.10 while the answer expects the positive magnitude 7.10. This remains a recorded mismatch, not a formatting issue. No paid reruns or prompt changes were made. Detailed five-sample results are in TASKS.md and ignored data/phase2b/ artifacts. Run the full offline suite without exclusions; do not rerun paid scripts without another assignment.

## Phase 3 local workflow

The programmatic entry point is app.services.receipt_service.ReceiptService(data_dir). Its async start/process_receipt/get_receipt methods use the configured directory for receipts.sqlite3 and originals/{receipt_id}.pdf. The module-level process_receipt wrapper uses DATA_DIR. Calling the production process method on a new PDF invokes the model; no such call is authorized during the current phase. HTTP routes are deliberately disconnected and remain 501.

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
