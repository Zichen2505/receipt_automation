# Airtable synchronization handoff - 2026-10-28

Repository: https://github.com/Zichen2505/receipt_automation.git.
Prior upload/query development branch was verified both locally and through
git ls-remote at 279c9a0ebc3c51e6273deb4ec5a2f30238144ff2. Main was
f7de7ed2c8a751591331a9e3490412fc65c833b7. The initial working tree was clean.
This phase uses feature/receipt-airtable-sync, created from that prior development
commit. No merge or force push is authorized or performed. The final phase
commit is this handoff's enclosing commit and is reported in the delivery reply.

## Behavior and boundaries

The HTTP application injects AirtableClient using backend environment settings.
Only saved and validation.passed=true records can synchronize after their
original/data/metadata commit. The unchanged pure mapper implements the six
columns from the unchanged AIRTABLE_SCHEMA.md v1.1. RawJSON includes the entire
data object, item detail, original decimal strings and nulls. No schema mutation
or account-discovery calls are implemented. Routes only delegate to Service;
HTTP calls reside in Integration and SQLite changes in Storage. Shared models
and deterministic validation are unchanged.

Sync state and returned rec... ID persist in the existing response_json, without
a database migration. A shared DATA_DIR lock serializes uploads and retries.
ReceiptID lookup precedes create, and confirmed synchronization avoids later
network work. The adapter verifies the returned/matched content before claiming
success, including complete parsed RawJSON. Duplicate/conflicting remote records
are unknown and require reconciliation. Local saved status/data/original/audit
metadata survive all sync failures, including sync-state storage faults.

Pending is committed before lookup. Unknown is committed before sending POST;
that barrier must succeed before a write. POST transport/timeout/5xx/408 or invalid
success responses retain unknown. Definite 4xx rejections except 408 are failed;
no automatic retries or redirects occur. A remote success followed by failure
to commit its ID leaves unknown for later lookup. Startup converts pending to
unknown, without network work. An unknown/pending retry never creates, including
when its lookup returns no row: a timed-out prior request might still commit.
There is no unsafe reset API. Known duplicate prevention is scoped to this one
process, DATA_DIR and unchanged destination, not independent external writers.

POST /api/v1/receipts/{receipt_id}/sync requires X-API-Key. It needs no file or
model parameters, never calls extraction, returns 404 for an unknown local ID,
and returns the existing ReceiptResponse for known outcomes. Review/failed local
results remain unchanged and never contact Airtable. Identical PDF resubmission
also retries eligible unsynchronized receipts without model work. GET only
reads. Sync errors return HTTP 200 with local saved and sync failed/unknown;
storage-state errors use sanitized 503. HTTP waiting timeout returns
504/sync_timeout with outcome=unknown while retained/shielded work continues.
Exports stay 501 and notifications stay not_sent.

AIRTABLE_TOKEN, AIRTABLE_BASE_ID and AIRTABLE_TABLE_ID must all be nonblank.
Use a PAT scoped to data.records:read and data.records:write for the intended
existing base; no schema write scope is needed. Missing configuration yields
not_configured without HTTP, except existing unknown/pending is preserved so
configuration removal cannot erase uncertainty. AIRTABLE_TIMEOUT_SECONDS is
finite positive, defaults to 15, and bounds each request with total and phase
deadlines. No credentials or remote error bodies are printed. HTTP wait limits
and upload limits retain their prior configuration names and behavior.

The explicit local-only ReceiptService without an adapter, and its module-level
local wrapper, retain skipped for compatibility with the accepted phase 3
workflow. Production HTTP always injects an adapter, including when unconfigured.
An already saved prior-phase record can synchronize through the retry API; no
model call or reprocessing is necessary. Do not change the Airtable destination
for an existing DATA_DIR; destination migration is not implemented.

## Verification and retained evidence

All execution was offline. Guards removed application credentials, blocked SDK
construction, external network and secret/private file access in the verification
processes. No real model or Airtable endpoint was called. Authorized development
fixtures and the supplied authority matched their pre-run SHA-256 values.

| Executed command | Actual result |
| --- | --- |
| `git ls-remote` for prior branch/main | Matched the two full commits above; initial sandbox network failure and elevated relative-origin failure were resolved with explicit repository URL/path |
| `scripts/offline_regression.py tests/test_airtable_sync.py` | 30 passed, 0 failed/errors/skipped; data/http_api/20261028T163905Z_07543b46/ |
| `acceptance/airtable_independent/run.py --record first-run` | 13 passed, no failures/errors/skips/guard violations, sources frozen; first evidence retained |
| `scripts/offline_regression.py` first full run | 136 passed, 1 failed; data/http_api/20261028T164149Z_c06c4d63/; old 30 ms timeout helper queried with 30 ms and got 504 |
| `scripts/offline_regression.py tests/test_http_receipts.py::test_detached_failure_after_timeout_is_never_reported_as_premature_terminal` | Both parameter cases passed alone, unchanged assertions; data/http_api/20261028T164249Z_5a2247b1/ |
| `scripts/offline_regression.py` second full run | 136 passed, 1 failed; data/http_api/20261028T164332Z_5f692f4a/; other parameter read before the processing claim had reached disk |
| `scripts/offline_regression.py` final full run | 137 passed, 0 failed/errors/skipped, 1 existing AnyIO deprecation warning; 5.32 seconds; data/http_api/20261028T164408Z_dea29ead/ |
| `acceptance/airtable_independent/run.py --record deadline-expanded` | 15 passed, 0 failures/errors/skips, no guard violations, source/test hashes unchanged during execution; 1.547 seconds |
| `acceptance/phase3_independent/run.py --record airtable-20261028 --snapshot-current` | Original 90 cases passed, no failures/errors/skips/guard violations; 8.844 seconds |
| `acceptance/phase3_independent/run.py --record airtable-final-20261028 --snapshot-current` | Original 90 cases passed, no failures/errors/skips/guard violations; 8.719 seconds; final source/spec snapshot |
| `scripts/verify_airtable_handoff.py` | All prior test assertions unchanged; original independent suite/schema/authority/validation unchanged; historical evidence hashes and retained first-run sources matched |
| `.venv/Scripts/python -m pip check` | Passed; no broken requirements |
| `git diff --check` | Passed |
| `scripts/audit_staged.py` / `git diff --cached --check` | 23 staged files, zero secret/private-file findings; cached whitespace check passed |
| English-language scan / remote pre-push ref check | No Han text in changed project files; new branch absent remotely, main/prior branch unchanged |

Commands in the table are invoked with `.\.venv\Scripts\python -B` unless they
are explicitly Git/pip commands. Evidence is exclusive-create, local and ignored;
no failing first result was overwritten or relabeled as a pass. HTTPX/httpcore/
certifi pins moved from development to runtime requirements, using already
installed dependencies without downloads or version changes.

The old HTTP test's helper now waits for its injected extractor-entry event
before inspecting the processing claim, and uses a normal five-second budget
for the later independent query. Its initial processing wait remains 30 ms;
every original assertion is unchanged, confirmed by AST comparison. Product
timeout behavior was not changed to satisfy these checks. Original independent
test sources and evidence remain untouched. The new contract suite uses literal
oracles and no existing tests/data, but was authored by the implementation agent;
it does not claim external human review. Its original 13 assertions were retained
when adding two separate deadline cases.

Coverage includes the six fields and null/item fidelity, durable pre-write barrier,
business/storage eligibility, concurrent duplicate submissions across instances,
matching/duplicate/conflicting ReceiptID lookup, incomplete configuration,
401/403/422/429/408/5xx, lookup failure, lost response with/without remote commit,
malformed success, retry/restart recovery, local sync-write faults, production
HTTP wiring/auth/query/export, actual adapter deadline and HTTP timeout continuation.

## Remaining limits and stop point

NOT RUN: real model, live Airtable/account/schema/permissions verification, UI,
notifications, exports, Docker/deployment, malicious-PDF resource isolation,
multi-process operation, destructive crash/power-loss or platform-volume tests.
The remote table and ReceiptID physical field remain unconfirmed. There is no
global account rate limiter or automatic scheduler; wait at least 30 seconds
after 429 before explicitly retrying. The DATA_DIR lock can delay other work
during synchronization. Synced remote rows are not continuously audited/repaired.
Persistent unknown without a matching row needs deliberate operator reconciliation
under a later assignment; there is no automatic create/reset for that case.

No active implementation blocker remains in this offline scope. Push the reviewed
development branch without changing main, report the actual commit/results, then
stop. Any live verification, maintenance reset, UI, notifications or deployment
requires a new explicit assignment.
