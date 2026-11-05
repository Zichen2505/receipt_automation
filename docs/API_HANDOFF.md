# Upload/query API handoff

For the newly authorized durable server-to-server extraction contract, read
[EXTRACTION_API_HANDOFF.md](EXTRACTION_API_HANDOFF.md). It uses separate
credentials, a stable integration scope, client UUID idempotency, independent
SQLite/originals and a lifespan execution loop. The legacy receipt API described
below keeps its response/authentication/synchronization/waiting behavior.

Date: 2026-10-28 (America/New_York).

Authenticated upload and persisted query now delegate to ReceiptService. The
production route uses the real metadata extraction adapter unless a test injects
a substitute. No real model request, Airtable call, UI, notification, export or
deployment work was performed. saved remains local commit plus validation passed;
sync=skipped and notification=not_sent.

## Repository baseline

Repository root: receipt-agent, verified by git rev-parse --show-toplevel.
Remote: https://github.com/Zichen2505/receipt_automation.git.
The remote had no references before initialization; no existing remote work was
overwritten. Baseline main commit, already pushed:
`f7de7ed2c8a751591331a9e3490412fc65c833b7`.
Development branch: `feature/receipt-upload-query-api`; it is intentionally not
merged into main. Neither push uses force.

Baseline review staged 61 source/document/test files and passed the secret/private
file audit. .env/credential copies, real PDFs, databases, fixtures, runtime data,
original acceptance logs/JSON/reports and first-run source snapshots are excluded.
Independent test source remains tracked. Original evidence stays locally in
acceptance/phase3_independent/ and data/. The supplied Airtable authority is
protected against Git line-ending transformation. Git metadata initially required
elevation for filesystem access; the sandbox/host ownership difference is handled
with a command-scoped safe.directory, without changing global Git trust.

## Implementation and contract

Upload admission checks media/header, actual byte count, strict PDF structure,
encryption and page count in a worker thread. pypdf is pinned at 6.21.3. An ASGI
body envelope also bounds multipart parsing and closes existing spool files on
overflow. Its count does not trust Content-Length. Defaults are 10 MiB, 20 pages,
and 130 seconds of HTTP Service waiting. PROJECT_SPEC.md and .env.example define
the configurable names and errors.

Service owns normalization, validation, persistence and deduplication. Shared
models, validation implementation and storage code are unchanged. ReceiptService
has only a docstring correction; its behavior/signatures are unchanged. The routes
contain no model, SQL or Airtable calls. GET returns persisted snapshots or 404;
POST returns 200 for saved/needs_review and 502 with the stored ReceiptResponse for
technical failed. Storage/unexpected errors are sanitized 503/500. Exports remain
authenticated 501.

HTTP timeout returns 504 with outcome=unknown, never a fabricated terminal receipt.
The original service task remains shielded/retained after timeout or disconnect.
Queries can time out while waiting for that workflow. Graceful shutdown waits for
retained work; force termination retains the existing recovery semantics. The
task set only retains live request calls and does not introduce a queue, worker
service or retry system.

Imports and ASGI startup use process environment only. An explicit local
`python -m app.main --env-file .env` loads that named file with override=False and
interpolate=False. Without the flag no dotenv file is loaded. Deployment/Compose
inject process variables before startup; this work did not deploy anything.

## Actual offline checks

| Executed command/check | Actual result |
| --- | --- |
| `git ls-remote --symref https://github.com/Zichen2505/receipt_automation.git HEAD` and all-reference listing | Succeeded with no references; sandbox network denial was retried with elevation |
| `git init -b main`, remote add, root verification, stage/review/commit, `git push -u origin main` | Baseline commit above pushed; no prior repository or remote history replaced |
| `git switch -c feature/receipt-upload-query-api` | Created a separate development branch |
| `python -m pip index versions pypdf`, then `.\.venv\Scripts\python -m pip install pypdf==6.21.3 --no-deps` | Installed pinned parser; initial index lookup was blocked by sandbox and then succeeded with elevation |
| `.\.venv\Scripts\python -B scripts\offline_regression.py tests/test_http_receipts.py` | Initial 37/37 passed; expanded coverage later passed 42/42; logs retained in fresh local run directories |
| `.\.venv\Scripts\python -B scripts\offline_regression.py` | Final 107 passed, 0 failed/errors/skipped, 1 existing AnyIO deprecation warning in 4.77 seconds |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\run.py --record upload-query-20261028 --snapshot-current` | 90 passed, 0 failed/errors/skipped; 8.532 seconds; frozen source/contract matched before/after |
| `.\.venv\Scripts\python -m pip check` | No broken requirements found |
| `git diff --check` | Passed; Git only reported existing Windows line-ending conversion notices |
| Diff/hash comparisons against main and original independent evidence manifest | Three independent test files byte-identical, assertions unmodified; original evidence hashes unchanged; shared schema/validation/storage/Airtable authority unchanged |

The regression runner guards the parent and child interpreters: real SDK clients,
external connections, root secret dotenv and private data reads are blocked.
Loopback permits the existing real Uvicorn health check. Both final suites recorded
zero guard violations. Authorized fixture and Airtable authority hashes matched
before/after regression. No input or expected answer was edited. Two obsolete
upload/query 501 cases were removed from the earlier stub-only parameterization;
the export 501/auth/schema regressions remain, with 42 new HTTP cases exercising
the new contract. The independent 90 assertions were not adapted. Its runner alone
supports a separate source snapshot/name for this explicitly authorized revision,
leaving the accepted original baseline/results intact.

Final evidence (local only; ignored by Git):

- data/http_api/20261028T093620Z_95e0141b/: console.txt, regression.xml,
  result.json and protected-input hashes for 107 regressions.
- acceptance/phase3_independent/upload-query-20261028.baseline.json,
  upload-query-20261028.console.txt and upload-query-20261028.results.json:
  new run snapshot and 90 individual results.
- Earlier exploratory HTTP runs are also retained under data/http_api/:
  20261028T093135Z_8f1f4d01 (37 HTTP tests),
  20261028T093307Z_736b8a9d (102 regressions before added edge cases), and
  20261028T093408Z_362fd1ba (42 HTTP tests).

HTTP tests cover upload/query, authentication, empty/spoofed/malformed/encrypted/
zero-page PDFs, byte/page boundaries, streamed multipart overflow with absent or
false Content-Length and temporary-file closure, duplicate/same-name handling,
business review, durable technical failure, failed failure-commit recovery,
production-adapter wiring with an offline request double, timeout continuation
to saved or failed, query wait timeout, disconnected requests, and graceful
shutdown. Explicit dotenv precedence/interpolation and invalid limit settings
are also exercised.

## Limits and next assignment

NOT RUN: real model-backed HTTP processing, external integrations, Airtable
schema/writes, browser/UI uploads, exports, notifications, Docker/platform
deployment, power-loss/destructive crash tests or hostile-PDF resource testing.
There is no proof of the final public URL-to-PDF-to-Airtable flow. The previous
model SDK deadline stays 120 seconds, with no retries. Upload/parsing/ingress
deadlines and process resource limits remain deployment concerns; 504 does not
cancel work or provide an ID until a later identical upload retrieves it. Multiple
workers/processes for one DATA_DIR remain unsupported.

Full historical regression requires authorized local development fixtures and
prior extraction artifacts; these are intentionally not in Git. A clean clone can
run the synthetic HTTP suite and independent --snapshot-current suite without
those private/local artifacts. The retained baseline/evidence is historical;
original freeze verification is not redefined to pretend API source never changed.

Current implementation and offline verification are complete. Review the
development branch and separately authorize any real-model, Airtable, UI or
deployment phase. Stop here.

Final pre-commit index review: 23 changed files, zero secret/private-file findings;
cached whitespace check passed. The project-language scan found no Han text
(normal rg exit 1); explicit ignore checks confirmed that sensitive/local inputs
and original/new acceptance artifacts remain excluded.
