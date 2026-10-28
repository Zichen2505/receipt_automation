# Render deployment preparation (not deployed)

## Current preparation - 2026-10-28

Prepared from feature/minimal-upload-page at
45d9924455fae15f1bd6494007aa830a18a2dcd8 on the separate
chore/render-predeploy branch. This includes the API, Airtable synchronization
and upload page. No merge into main, force push, cloud deployment or Render
service creation is authorized. Actual commands/results are in TASKS.md.

The initial preparation attempt had no reachable Docker Engine and did not run
container acceptance. A later explicit acceptance assignment on 2026-10-28
verified commit df878d852a88f548bf42aa5f20fe8a49119704b3 with the now-available
Docker Desktop Linux Engine. The actual image build, dependency/asset checks and
all three existing container acceptance stages passed. This supersedes the
earlier local Docker blocker only; Render deployment remains unperformed.

Evidence: data/docker/20261028T220021Z_dcff829b/ (local and ignored). The default
production container passed home/static assets, unauthenticated /health,
receipt authentication, explicit 501 export and UID 10001 mounted-store writes.
The explicit substitute container passed synthetic extraction, simulated
Airtable GET/POST, upload/query, originals/results/metadata and duplicate checks.
A recreated default production container reused that isolated /app/data store,
queried the same complete record and handled duplicate uploads without another
extraction or simulated Airtable call. All three containers stopped with exit 0
and were removed. Containers used --network none; real model/Airtable calls: 0.

An additional image audit confirmed Linux amd64, UID/GID 10001:10001, the default
CMD, DATA_DIR/PORT defaults and no business secret environment variable names.
All 30 files under /app exactly matched the authorized app/requirements source
manifest; there were no extra environment files, PDFs, databases, test harnesses
or local evidence in the image. Image ID:
sha256:f6483b4a934818fd87de7792bb6f886949c933416742b6c945d8ad9660205d9e.

GitHub Actions for that exact commit remains UNCONFIRMED. GitHub CLI is installed
but unauthenticated; the credential-free read of the commit-filtered Actions REST
endpoint could not connect. Neither failure establishes a passed/failed/absent
workflow run. No manual workflow dispatch or rerun was requested. Pushing the
documentation handoff can trigger the existing push workflow. An authenticated
operator can inspect the repository Actions page and match the full head SHA;
do not substitute local Docker success for a remote Actions result. The delivery
commit updates only documentation; application/build/harness/CI sources stay
identical to the accepted commit. See the latest TASKS.md section for provenance.

## Render fields for a future authorized deployment

| Field | Value |
| --- | --- |
| Repository | https://github.com/Zichen2505/receipt_automation |
| Branch | chore/render-predeploy; use the final pushed commit reported at handoff |
| Service runtime | Docker web service |
| Root Directory | Leave blank: this Git repository already has app/ and Dockerfile at its root |
| Docker build context | . (repository root) |
| Dockerfile Path | ./Dockerfile |
| Docker Command | Leave blank to use CMD: python -m app.main |
| Build/pre-deploy overrides | None; Dockerfile installs requirements.txt, checks dependencies and includes app/web |
| Listener | 0.0.0.0, platform PORT, one worker, no reload |
| Health Check Path | /health |
| Instances | One, with no horizontal scaling |
| Persistent disk | Mount at /app/data; use a service plan supporting persistent disks |
| DATA_DIR | /app/data |

Use the same branch and exact commit for later review; do not default to main.
Do not click Deploy or create a service during this assignment. No Blueprint or
automatic deployment integration is added. The disk must be writable by UID/GID
10001:10001. Image-directory ownership does not prove permissions of a mounted
Render disk; verify actual ownership/write access before live uploads. Do not use
world-writable permissions. Disk data is unavailable during build/pre-deploy.

| Environment variable name | Requirement or default |
| --- | --- |
| APP_API_KEY | Required non-placeholder secret for startup and receipt authentication |
| MODEL_API_KEY | Backend secret required for a new production extraction |
| MODEL_NAME | Required configured model name for a new production extraction; no fallback |
| AIRTABLE_TOKEN | Backend PAT required for synchronization; record read/write scope on the intended base |
| AIRTABLE_BASE_ID | Required for synchronization to the existing intended base |
| AIRTABLE_TABLE_ID | Required for synchronization to the existing intended table |
| DATA_DIR | Set /app/data |
| PORT | Honor Render's injected PORT; application default is 8000 |
| MAX_UPLOAD_BYTES | Optional, default 10485760 |
| MAX_PDF_PAGES | Optional, default 20 |
| HTTP_WAIT_TIMEOUT_SECONDS | Optional finite positive number, default 130 |
| AIRTABLE_TIMEOUT_SECONDS | Optional finite positive number, default 15 |

No secret values belong in this checklist, Git, build arguments, images or logs.
MODEL_API_KEY/MODEL_NAME and Airtable variables are unnecessary for startup or
health; all Airtable variables must be nonblank for synchronization. Missing
Airtable configuration yields not_configured. APP_API_KEY remains mandatory at
startup; /health itself requires no X-API-Key and makes no model/Airtable call.
Production startup uses process environment and requires no local .env. The
optional --env-file flag and Compose env_file remain local conveniences.

Only /app/data is persistent: receipts.sqlite3 includes receipt results, validation,
extraction metadata and synchronization IDs/status; originals/*.pdf stores the
unchanged uploads. Keep a consistent database/PDF backup. Keep AIRTABLE_SCHEMA.md
v1.1 and the remote schema unchanged. Retain upload authentication, byte/page/body
limits and explicit 501 exports. A 504 leaves an unknown outcome; graceful shutdown
waits for retained work, while forced termination relies on startup recovery.
Platform grace periods must accommodate the model deadline, Airtable deadlines
and lock/storage time; Docker defaults alone do not guarantee this.

Known limitation: identical PDFs in different databases receive different backend
ReceiptIDs and can create duplicate Airtable rows. Deduplication is scoped to the
same persistent database and fixed Airtable destination. Cross-database/global
deduplication is not implemented or fixed here. Never run two instances against
one DATA_DIR or change the Airtable destination of an existing store.

## Reproduce the local Docker acceptance when Linux Docker Engine is available

From the repository root with the existing Python environment:

```powershell
.\.venv\Scripts\python -B scripts/docker_acceptance.py
```

The harness builds a uniquely tagged production image and creates a new isolated
data/docker/<run-id>/store bind mount. It never mounts existing runtime data or
loads .env. Only synthetic verification credentials are passed. Containers use
--network none; requests run inside each container over loopback on PORT=8765.
The helper and supplied development A.pdf are read-only runtime mounts, absent
from the image. No expected answer is read; missing A.pdf is an explicit failure.

Three sequential, recreated containers reuse that store: default production CMD
for public page/assets, health without business service credentials, receipt
authentication, 501 exports and UID 10001 write access; an explicitly selected
verification server with synthetic extraction and HTTPX MockTransport for upload,
query, persisted IDs/data/originals and duplicates; then default production CMD
again for query and duplicate upload without new extraction/Airtable activity.
The event journal must remain exactly one synthetic extraction, one simulated GET
and one simulated POST. Containers stop normally with exit-code checks. Cleanup
removes only owned containers; image and all evidence/data remain for review.

Exit 0 means all stages passed; exit 2 means Docker unavailable with no acceptance
stages passed; exit 1 means failure. Read result.json and console.txt in the new
ignored evidence folder. An unavailable Engine means build/startup/assets/health/
authentication/write-permission/upload/query/restart/deduplication inside Docker
are all NOT RUN. It is not a successful container acceptance.

The clean-clone GitHub Actions workflow runs synthetic offline API/integration/
page/helper suites and docker build without service secrets. Original development
PDFs, answers, historical evidence and browser binaries stay outside Git, so that
workflow does not claim full historical/browser/container-upload acceptance.
The A.pdf-dependent helper test explicitly skips if the user fixture is absent.
Run the full local regression and unchanged independent suites as recorded in
TASKS.md when those authorized local artifacts exist.

Official configuration references: [Docker on Render](https://render.com/docs/docker),
[persistent disks](https://render.com/docs/disks),
[health checks](https://render.com/docs/health-checks), and
[web service port binding](https://render.com/docs/web-services#port-binding).
These describe intended settings, not a provisioned or verified Render service.

## Historical conventions

The following pre-preparation notes are retained as history. Current scope,
verification limits and Render fields are specified above; older statements
about assignment authorization or live verification are historical.

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
