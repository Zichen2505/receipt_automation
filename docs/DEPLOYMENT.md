# Deployment conventions (not deployed)

## Phase 3 local storage update

The local service now creates receipts.sqlite3 and originals/*.pdf in DATA_DIR.
HTTP business routes remain 501 and no new model-backed end-to-end run or
deployment has been performed. The settings below remain intended deployment
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

Set PORT (default 8000) and route platform ingress to that same port. Inject APP_API_KEY through platform secret variables. Set MODEL_API_KEY and MODEL_NAME when extraction is implemented, and AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID when Airtable is enabled. Do not place secrets in image build arguments, frontend assets, or logs. Public ingress should provide HTTPS and retain X-API-Key. Business endpoints currently return 501; receipt processing is not operational.

Set DATA_DIR=/app/data and mount a persistent disk there. SQLite receipts.sqlite3, originals/*.pdf, and future notification events all reside on that volume. The image directory belongs to UID/GID 10001. Platform mounts may override its permissions; initialize volume ownership/write access for 10001:10001. Grant only required permissions; do not use global 777. Startup creates the directory and probes temporary write access; an unwritable directory fails startup. Windows bind mounts and platform volume permissions require actual verification. Compose uses a named volume.

Run only one replica and one process. Do not scale horizontally or place SQLite on a shared filesystem without reliable file locking. Processing runs within the request; platform request timeouts must accommodate future model processing limits. Phase 1 does not specify upload/time limits; complete them before later production deployment.

Persistent storage needs independent backups and recovery exercises. Future SQLite backups must be consistent and include corresponding PDFs. The container writable layer can be lost on replacement. Without a persistent disk, do not claim files are reliably saved. Do not delete volumes containing production data.

The build context excludes .env, runtime data, all tests, PDFs, caches, and private/held-out paths. Never copy evaluation data into the build context or image. Docker build and startup remain unverified; see TASKS.md.
