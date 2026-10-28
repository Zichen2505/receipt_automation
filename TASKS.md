# Phase 3 handoff and verification record

Updated: 2026-10-24 (America/New_York). Phase 3 is complete for local adaptation,
validation, persistence, querying, deduplication, recovery and offline verification.
Stop here. No new model request, Airtable connection, UI/export/notification work,
business HTTP integration, or deployment was performed.

## Implemented in phase 3

- Read AGENTS.md and the required specification, Airtable authority, handoff and
  shared schema before implementation. Project prose remains English; user
  communication remains Chinese. .env and credential values were not printed.
- Discount-only normalization at the extraction adapter: explicit discount uses
  its positive Decimal magnitude; null stays null. Normalization is non-mutating
  and idempotent. All other amounts remain unchanged. Original/normalized values
  and reason are retained in ExtractionMetadata alongside raw model text and
  available SDK metadata. Historical raw_output and experiment files are intact.
- Existing extract/parse_extraction remain compatible. Added metadata-preserving
  adaptation helpers and centralized all additional metadata/storage models in
  app/schemas/receipt.py. ReceiptData, ReceiptItem and ReceiptResponse field names,
  status values, Decimal/date serialization and expected answers are unchanged.
- Deterministic required-field and exact Decimal checks, without guessed values,
  floats or tolerance. Business issues produce needs_review; valid committed
  records produce saved; technical faults produce failed or ReceiptStorageError
  if no durable failure commit is possible. Printed total is never overwritten.
- Atomic, server-UUID original PDF files and SQLite storage of ID, unique PDF
  SHA-256, relative original reference, processing state, complete response/data,
  validation, extraction/normalization/failure metadata and UTC timestamps.
- Async ReceiptService orchestration and local querying. Blocking storage,
  initialization/recovery, hashing and validation run in threads. No transaction
  remains open while awaiting a model. App startup initializes storage/recovery;
  dependency access is prepared, but business HTTP routes are still explicit 501.
- DATA_DIR coordination serializes workflows across service instances on the
  single supported event loop. Unique PDF hashes independently prevent duplicate
  DB rows; guarded terminal updates prevent overwriting completed results.
- Startup recovery converts leftover processing records to failed, retains IDs,
  recovers matching deterministic original references, and never automatically
  retries extraction. Duplicate failed records return the same failed result.

## Validation codes and applicability

Required merchant/date/currency/total generate missing_merchant, missing_date,
missing_currency, missing_total (blank required text also counts as missing).
Other checks produce item_amount_mismatch, subtotal_mismatch, total_mismatch,
invalid_amount_precision and invalid_discount as specified in PROJECT_SPEC.md.

Only complete quantity/unit_price/amount triples are checked. Item sum requires
a non-empty list, every amount known and subtotal known. The final total equation
requires subtotal/discount/tax/tip/total all explicitly known. Unknown optional
components are never silently replaced with zero. Thus a receipt can pass when
required fields and applicable checks pass while some optional equations remain
unverified. Exact multiples of 0.01 are compared without rounding; extra trailing
zeros alone are not errors. Synthetic tests explicitly exercise total conflicts
with complete components, partial formulas, decimal arithmetic, and precision.

## Actual offline acceptance results

Evidence: data/phase3/20261024T041152Z_4771e674/.
This is a new isolated offline test run, not a new real model end-to-end run.
The explicit acceptance harness injects phase 2/2B raw outputs as test substitutes.
Production app code does not read those outputs, fixtures, or standard answers.

| Sample | Local status | Validation | Data/original verification |
| --- | --- | --- | --- |
| A | saved | passed | Complete data/items match expected; original bytes and hash preserved |
| B | saved | passed | Tip, total and all items retained; original preserved |
| C | saved | passed | All five two-page items retained; no duplicate carried-forward item |
| D | saved | passed | discount becomes 7.10; every other field/item unchanged and matching expected |
| F | needs_review | failed with missing_currency | currency stays null; complete data and original retained |

Each sample has a distinct backend ID. Repeating every original reuses that ID
without another substitute call. SQL records include audit metadata; D retains
original_value=-7.10, normalized_value=7.10 and the explicit conversion reason.
No saved result indicates reimbursement/payment approval or external integration.
All phase 3 responses have sync=skipped and notification=not_sent.

Reviewable artifacts:

- acceptance.json: five full persisted records, normalized data, validation,
  hashes, original references, normalization/raw metadata and duplicate checks.
- local-store/receipts.sqlite3 and local-store/originals/: the isolated acceptance
  database and five real development PDFs, all inside that test DATA_DIR.
- offline-regression.xml: final complete offline pytest JUnit report.
- verification.json: parsed regression counts and historical-evidence/input,
  prompt/authority and credential-exposure audit results.

No earlier experiment output was overwritten. The standard answers and Airtable
v1.1 document remain byte-for-byte unchanged. New persistence here is exercised
with substitute extraction only; live HTTP/model processing was not performed.

## Actual verification commands and results

| Check / command | Actual result |
| --- | --- |
| Initial `.venv/Scripts/python -m pytest -q tests/test_phase3.py` | 26 passed in 2.02 seconds, before additional failure-edge coverage |
| Final `.venv/Scripts/python -m pytest -q --junitxml=data/phase3/20261024T041152Z_4771e674/offline-regression.xml` | 67 passed, 0 skipped, 0 deselected, 1 warning in 4.36 seconds |
| Full development Schema compatibility / existing SDK and HTTP checks | Passed in the complete offline suite, including all five expected schemas and 401/422/501/health behavior |
| D normalization and signed/positive/zero/null/idempotence checks | Passed; other fields unchanged, raw source retained |
| Synthetic required fields / exact line, subtotal and total conflicts / unknown applicability | Passed; conflicts do not replace printed totals or become saved |
| Five real-output-substitute workflow and repeated input checks | Passed; A/B/C/D saved, F needs_review; no model requests |
| 20 concurrent identical submissions across three service instances | Passed; one substitute call, one ID, one DB row and no terminal overwrite |
| 12 concurrent SQLite claims for the same hash | Passed; one reservation owner and one ID |
| New service instance and new Python interpreter querying | Passed; same record, ID, normalized data and original PDF bytes |
| Crash-left processing before/after original replacement | Passed; converted to failed, retained ID, matching original reattached, no retry |
| Model failure / original-save failure / final-commit failure | Passed; durable failed when possible; sanitized storage exception when even failure cannot commit; no false saved |
| Same-loop recovery after failure commit is impossible | Passed; the next operation reinitializes/reconciles storage and returns failed without retrying extraction |
| Original atomic replacement failure / unsafe paths / overwrite prevention | Passed; temporary cleanup, safe UUID paths, existing original retained |
| Caller cancellation ownership | Passed; owner finishes and duplicate does not call the substitute again |
| `.venv/Scripts/python -m scripts.phase3_offline_acceptance` | Passed; five matching local results, duplicates reused, five substitute calls, zero new model requests |
| `.venv/Scripts/python -m pip check` | Passed: No broken requirements found |
| Historical actual/raw/PDF integrity | Passed against stored hashes and raw/actual equality; old D remains -7.10 in historical evidence |
| Expected answers, Airtable authority and prompt integrity | Passed against earlier hashes; no edits |
| Acceptance artifact credential audit | Passed; no values printed and no configured credentials found in evidence |
| Changed project source/documentation language scan | No Han matches; normal rg no-match exit code 1 |
| New real model end-to-end requests, Airtable, UI, exports, notifications, Docker/deployment | NOT RUN, explicitly outside phase 3 |

The existing warning is Starlette TestClient referencing a deprecated AnyIO alias.
All SDK calls in regression tests are mocked. Tests do exercise local Uvicorn
startup and HTTP requests, with business routes still disconnected. No private
evaluation or held-out data was accessed.

## Recovery, limits and next handoff

File replacement and SQLite commit are not one atomic transaction. The committed
claim comes first; original replacement and reference commit precede extraction;
terminal response/metadata commit precedes returning success. If interrupted,
startup marks processing as failed and checks the deterministic original against
its stored hash. No automatic model replay occurs. Crash-left temporary and
unreferenced files are preserved for deliberate maintenance, not silently deleted.
Ordinary operation failures remove only their own temporary file. If failure
commit also fails, subsequent service initialization attempts recovery.

The supported deployment remains one process, one worker, one asyncio event loop
per DATA_DIR. The gate serializes different PDFs too, and service reads may wait
for active processing. No distributed/process lock or multi-worker support is
claimed. Failed PDFs remain deduplicated; retry/reset semantics are not implemented.
Terminal-original external corruption/deletion is not continuously repaired.
Power-loss behavior and actual Docker volume/permissions/signals are unverified.

Next phase requires a user assignment. Likely work is connecting HTTP upload/query
to the local service with bounded file validation, timeouts, error mapping and
configuration checks, followed only if authorized by new real model end-to-end
verification. Do not infer permission to call models or enable Airtable/exports/
notifications/deployment from this handoff. Preserve the local acceptance evidence
and historical runs; never use them as production extraction fallbacks.

# Historical phase 2B handoff

The following records are historical. Earlier implementation limits, D mismatch
and phase restrictions are superseded only by the explicit phase 3 changes above.

Updated: 2026-10-23 (America/New_York). Phase 2B is complete for the authorized
single request each for B, C, D, F and complete offline regression. Stop here.
No text probe or A request was repeated. No Airtable, business persistence,
deployment, or full processing endpoint was implemented.

## Phase 2B actual results across all five development samples

Model: gpt-5.6-terra, read from existing MODEL_NAME. MODEL_API_KEY was passed
explicitly by the unchanged official SDK extractor. No retries, model fallback,
prompt edits, schema changes, expected-answer changes, or scorer changes.

Current run: data/phase2b/20261023T224454Z_695f2d59/.
Prior A evidence: data/phase2/20261023T222741Z_0d6db5ab/; reused offline only.

| Case | Value checks matched | Value errors | Format-only differences | Input tokens | Output tokens | Total tokens | Seconds | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 30/30 | 0 | 0 | 748 | 172 | 920 | 2.950283 | Prior phase 2 result; not rerun |
| B | 22/22 | 0 | 0 | 765 | 136 | 901 | 2.346167 | New single request |
| C | 30/30 | 0 | 0 | 993 | 205 | 1198 | 3.194606 | New single request |
| D | 21/22 | 1 | 0 | 765 | 136 | 901 | 2.429850 | New single request |
| F | 18/18 | 0 | 0 | 700 | 111 | 811 | 2.527326 | New single request |

Overall: 121/122 diagnostic field/item-count checks match; four of five data
objects match completely. These are extraction diagnostics, not the official
scorer or business-validation results. The four new requests consumed 3223
input + 588 output = 3811 tokens, taking 10.497949 seconds combined. Across all
five PDFs, usage is 4731 tokens, excluding the earlier 16-token text probe.
All four new calls reported zero cached, cache-write, and reasoning tokens.
No monetary cost or remaining account balance was inferred.

## Required case observations and difference analysis

- B: tip="12.00", tax="4.96", subtotal="62.00", final total="78.96". Decimal
  check 62.00 + 4.96 + 12.00 = 78.96 passed. All three items match.
- C: original PDF has two page objects. All five ordered items from both pages
  match, totaling 330.00. The 288.00 carried-forward/brought-forward amount is
  not an additional item and was not counted twice. Tax=26.40 and total=356.40
  match; the page-two zero balance due was not substituted for total paid.
- D: discount actual="-7.10", expected="7.10". This is one genuine Decimal
  value/sign difference, not a small decimal-place formatting difference.
  Inspection of the original PDF text operators confirmed that it prints
  Discount (10%) -7.10. The model preserved this printed deduction sign; the
  expected schema instance uses a positive discount magnitude. Subtotal=71.00,
  VAT=12.78, and total paid=76.68 match. 71.00 + (-7.10) + 12.78 = 76.68.
  No absolute-value normalization, answer edit, prompt change, or paid rerun
  was performed. Future treatment of discount sign requires a separately
  assigned contract/prompt decision; the mismatch remains visible now.
- F: currency is null as required; no currency was guessed. Its two items,
  amounts and remaining data match. No needs_review status is required or
  assigned in extraction; that belongs to later business validation.

Source observations are in pdf_notes.json (standard-library inspection of
supplied ReportLab ASCII85/Flate text operators, not a visual render) and
analysis.json (Decimal arithmetic and explicit interpretation). The temporary
inspection helpers were removed after saving evidence and are not production
PDF-processing code.

## Execution isolation and saved evidence

- scripts.phase2b_extract processed only B/C/D/F sequentially using the existing
  request_extraction/parse_extraction functions and settings. It never reads
  expected answers or imports the comparison module. Automatic retries remain
  disabled. It stops conservatively after any failure, including all required
  authentication/quota/model-permission failures. No failures occurred.
- Every case saved pdf_attempt.json, raw_output.txt, actual.json and
  extraction_metadata.json before comparison. Evidence includes PDF/raw/output
  SHA-256, actual SDK response ID/status, configured model, complete usage,
  timestamps, elapsed time, and expected_read=false. All four actual outputs
  parsed into the existing ReceiptData.
- Only after all extraction evidence was saved did a separate offline command
  invoke scripts.phase2b_compare. It verifies successful metadata and output
  hashes before reading each matching expected JSON. A's older actual output
  was re-compared offline; its original actual.json and exact comparison.json
  were not rewritten. New decimal_comparison.json was added alongside it.
- Each case has decimal_comparison.json. The current run contains
  five_sample_summary.json, source_hashes.json, extraction_summary.json,
  pdf_notes.json, and analysis.json.
- Decimal comparison keeps exact strings and exact-string difference counts,
  then separately records finite Decimal numeric equality and format-only
  differences. It does not round, apply tolerances, change signs, normalize
  nulls, or modify official scoring. Item quantity is also compared numerically;
  monetary errors are identified separately. Missing data remains an error.
- No secrets or .env contents were printed. Evidence is ignored by Git and
  excluded from Docker. These files are experiment artifacts, not business
  persistence and not proof of a saved/synced/notified receipt.

## Actual phase 2B verification

| Check / command | Actual result |
| --- | --- |
| Pre-request `python -m pytest -q tests/test_phase2b.py` | 6 passed in 0.61 seconds |
| `python -m scripts.phase2b_extract` | Four successful single PDF requests B/C/D/F; no probe, no A request, no retries |
| `python -m scripts.phase2b_compare --run-dir data/phase2b/20261023T224454Z_695f2d59 --a-dir data/phase2/20261023T222741Z_0d6db5ab` | Five evidence comparisons, one D discount sign mismatch, zero format-only differences |
| `.venv/Scripts/python -m pytest -q` | 35 passed, 0 skipped, 0 deselected, 1 warning in 2.03 seconds |
| Existing all-development Schema compatibility test | Passed as part of the complete offline suite; included A/B/C/D/F despite no new A request |
| Failure-stop / answer-isolation / Decimal tests | Passed: failures stop later requests, repeat case directory blocks another attempt, extraction cannot read expected, decimal-format differences are separate, null/missing/text differences remain visible |
| Existing HTTP regression checks | Passed: health/startup/authentication/parameters preserved; authenticated business endpoints remain explicit 501 |
| `.venv/Scripts/python -m pip check` | Passed: No broken requirements found |
| Source and original-input integrity | Passed: extractor, prompt, shared schema, Airtable authority and five PDFs unchanged against pre-request hashes; five expected JSON files unchanged against earlier handoff hashes |
| Credential exposure audit of current run artifacts | Passed; credential values were never displayed |
| Official scorer, business validation/status, business persistence, Airtable, notifications, Docker/deployment | NOT RUN / unimplemented as applicable; no success claimed |

The one test warning is the existing Starlette TestClient / AnyIO deprecated
alias. The full suite is offline: SDK calls in tests are mocked, and only local
HTTP startup is exercised. No evaluator_private or held-out data was accessed.

## Next handoff

Stop after this task. Keep D's discrepancy and original evidence intact.
Do not automatically edit the prompt, replay paid calls, or change answers to
make the result pass. The next user assignment should determine whether and how
to express positive discount magnitudes, then separately assign any validation
or orchestration work. process_receipt and business endpoints remain unimplemented;
extraction success does not imply saved, needs_review, payment approval, Airtable
synchronization, or notification. No additional credentials or fixtures are
required to understand the current evidence.

# Historical phase 2 handoff

The following phase 2 and phase 1 records are retained as history. Their earlier
scope restrictions and unrun checks are superseded only by the narrow phase 2B
work and actual verification recorded above.

Updated: 2026-10-23 (America/New_York). Current phase: 2, completed for the
authorized one-text-probe / one-A.pdf experiment. Stop here. No batch model
tests, Airtable connection, full processing API, deployment, or later phase
was performed or is authorized by this task.

## Phase 2 scope and implementation

- Read AGENTS.md and its required files before work. Followed the OpenAI Docs
  skill and official Python SDK/PDF input documentation. Did not display .env
  contents or credential values.
- Installed and pinned official openai==3.37.0 and python-dotenv==1.2.4, plus
  their added runtime dependencies. Installation first hit sandbox network
  restrictions, then succeeded with approved network access.
- Explicit AsyncOpenAI api_key reads MODEL_API_KEY; model reads MODEL_NAME
  verbatim. The actual configured model was gpt-5.6-terra. No model fallback,
  OPENAI_API_KEY fallback, or custom API endpoint was used.
- Both live requests used max_retries=0 and store=False. The text request used
  a 30-second timeout and max_output_tokens=32. The PDF request used a
  120-second timeout and max_output_tokens=4096. Exactly one request of each
  type was sent; no automatic or manual model retries were made.
- Implemented extract(pdf_bytes, filename) -> ReceiptData with the async
  Responses API and inline base64 PDF input, without a Files API upload.
  Strict JSON Schema is derived from the existing shared ReceiptData model;
  no receipt data structure was duplicated or changed.
- Replaced the placeholder prompt with English extraction instructions using
  only the attached PDF and shared schema. Original text is preserved, unknown
  values stay null, and unprinted values are not invented.
- Added local scripts.phase2_probe, scripts.phase2_extract_a, and the separate
  offline scripts.phase2_compare_a. Failed text probes block PDF execution;
  an exclusive PDF-attempt marker prevents silent repeats in one run folder.
- The explicit runners alone load project-root .env with no interpolation and
  without overriding existing environment values. Importing or starting the
  HTTP app still does not load .env automatically.
- Updated AGENTS.md, PROJECT_SPEC.md, README.md, and dependency pins. Extended
  Git/Docker exclusions to .env* to cover credential-bearing copy filenames
  as well; .env.example remains the Git exception.

## Actual phase 2 live results

Run directory: data/phase2/20261023T222741Z_0d6db5ab/ (ignored by Git and excluded
from the Docker build context). Artifacts are local experiment evidence, not
production receipt storage or a ReceiptResponse with status=saved.

| Stage | Outcome | Input tokens | Output tokens | Total tokens | Elapsed seconds |
| --- | --- | --- | --- | --- | --- |
| Minimal text request | completed; output OK | 11 | 5 | 16 | 2.204010 |
| development/pdfs/A.pdf extraction | completed; parsed as ReceiptData | 748 | 172 | 920 | 2.950283 |
| Combined requests | Both completed, no retries | 759 | 177 | 936 | 5.154293 |

Both responses reported zero cached, cache-write, and reasoning tokens. Durations
are measured wall time for each request stage, not total implementation time.
Successful requests establish access and capacity for these calls; remaining
account balance and future quota were not queried or established.

Artifacts:

- text_probe.json: actual model, response ID/status, text output, token usage,
  timing, retry count, and text-stage evidence that PDF/expected were not read.
- pdf_attempt.json: exclusive attempt marker and UTC start time.
- raw_output.txt: actual model output written before parsing or comparison.
- actual.json: schema-validated actual ReceiptData, including all five items.
- extraction_metadata.json: response ID/status, configured model, complete
  usage details, timing, original PDF/output hashes, completion time, and
  expected_read=false for the extraction stage.
- comparison.json: every compared field and item, exact actual/expected values,
  hashes, comparison time, counts, and differences.

The extraction scripts never read expected answers. Only after raw_output.txt,
actual.json, and successful extraction_metadata.json existed did the separate
offline comparison read development/expected/A.json. It verified the actual
output hash before reading that answer. This ordering is explicit in the scripts
and in the recorded extraction/comparison timestamps.

Comparison result: 30 checks matched, 0 differences. This includes all nine
top-level scalar fields, item count, and four fields for each of five items.
Decimal strings were compared exactly without normalization. Actual merchant
was MAPLE MARKET, date 2026-10-12, currency USD, and total "32.78". No business
validation rules were executed and no saved receipt status was assigned.

## Actual phase 2 local checks

| Check / command | Result |
| --- | --- |
| Pre-PDF offline extractor tests | 6 passed in 0.56 seconds; no expected-answer reads or network requests |
| `.venv/Scripts/python -m pytest -q tests/test_extractor.py tests/test_phase2_runner.py tests/test_phase1.py -k 'not development_schema_compatibility'` | 28 passed, 1 deselected, 1 warning in 1.92 seconds |
| SDK boundary and stopping-rule checks | Passed: explicit MODEL_API_KEY, configured model, no retries, inline PDF bytes, strict shared schema, incomplete/invalid output rejection, failed probe blocks PDF, and error artifacts do not expose synthetic credentials |
| Exact offline comparison behavior | Passed: missing fields differ from null, decimal strings are compared exactly, and item-count differences are reported |
| Existing HTTP regression checks | Passed: health/startup/authentication/parameter behavior preserved; authenticated business endpoints remain 501 |
| `.venv/Scripts/python -m pip check` | Passed: No broken requirements found |
| Credential exposure audit | Passed: .env credential values absent from run artifacts and checked project records; audit printed no values |
| Original schema/A.pdf/A.json SHA-256 comparison | Passed: unchanged against previous handoff hashes |
| Han-character scan of changed application/scripts/tests/docs | No matches; rg returned its normal no-match exit code 1 |
| Other development cases | NOT RUN in this phase; the all-development compatibility test was deliberately deselected to keep the check scoped to A |
| Business validation, SQLite/PDF business persistence, full processing API, Airtable, notification, Docker | NOT RUN / unimplemented, as applicable; no claim of completion |

The one warning is the existing Starlette TestClient / AnyIO deprecated alias.
SDK tests and all checks after the live A extraction were offline. No other PDF
was sent to a model. No private evaluation or held-out answers were accessed.

## Remaining work and next handoff

The current task is complete; wait for the user's next phase assignment. Full
process_receipt remains explicitly unimplemented, and authenticated HTTP business
routes continue returning 501. Direct extraction returning ReceiptData does not
imply saved, validated, reimbursable, paid, synchronized, or notified.

Future work still includes business validation rules, atomic original-PDF storage,
SQLite persistence, stable IDs/idempotency/recovery, full service orchestration,
exports, and any separately authorized Airtable/notification integration. The
authoritative Airtable v1.1 file and original development fixtures remain unchanged.
Do not rerun the paid probe/PDF scripts or perform broader live evaluations without
a new assignment. The evidence files under data/ are intentionally local; preserve
them for handoff without adding secrets, inputs, or expected data to Git/images.

# Historical phase 1 record

The following sections preserve the previous phase 1 handoff. Their descriptions
of unimplemented extraction and phase limits are historical and superseded only
by the narrow completed phase 2 scope above. Their earlier verification results
have not been relabeled as newly executed checks.

## Current file locations and authority

- Workspace root: C:/Users/26716/Dev/AI/Expense_Auto.
- Project root: receipt-agent/. The sole authoritative Airtable mapping document
  is receipt-agent/AIRTABLE_SCHEMA.md, supplied schema_version 1.1.
- There is no AIRTABLE_SCHEMA.md at the workspace root and no
  "AIRTABLE_SCHEMA copy.md" on disk. IDE tabs do not establish file existence.
  No schema documents were moved, renamed, duplicated, or rewritten.
- Development PDFs: tests/fixtures/development/pdfs/.
- Development expected answers: tests/fixtures/development/expected/.
- Supplied cases: A, B, C, D, F; five PDFs and five expected JSON files.
  No additional cases were requested or inferred from private data.
- Expected JSON wraps receipt fields under data, with case_id, expected_status,
  expected_issue_codes, pdf_file, and page_count as evaluation metadata.

## Completed skeleton

- AGENTS.md specifies the four required startup reads, unique shared models,
  coordinated interface updates, boundaries, and handoff requirements.
- Added the required language rules: communicate with the user in Chinese;
  write project documentation, comments, docstrings, prompts, UI text, and
  handoff records in English; preserve original inputs and evaluation data.
- PROJECT_SPEC.md defines architecture, final flow, module responsibilities,
  fixed signatures and storage parameters, async conventions, states, errors,
  configuration, and deployment.
- Shared Pydantic models preserve nulls, Decimal money as JSON strings, ISO
  dates, and the specified response states. Extra fields and non-finite money
  are rejected.
- FastAPI checks startup configuration and writable DATA_DIR, exposes /health,
  authenticates business endpoints with X-API-Key, and explicitly returns 501
  for valid authenticated business requests. No fabricated business results.
- Service, Integration, and Storage functions retain their signatures and
  explicit unimplemented exceptions. Prompt and UI remain unconnected.
- The pure Airtable adapter maps the exact six columns and preserves complete
  RawJSON, with saved/validation.passed eligibility checks. No remote writes.
- Dockerfile and Compose specify non-root execution, configurable PORT, exec
  startup, Python health checks, and a persistent volume. Runtime dependencies
  and development dependencies are pinned, including transitive dependencies.
- Windows local setup and deployment requirements are documented.

## Language update

Translated project-owned documentation, the placeholder prompt, UI text and
HTML language declaration, test messages, and synthetic contract labels.
Existing English code comments, docstrings, and API error messages were reviewed
and retained. Filenames, schema fields, function signatures, API paths, states,
and business logic are unchanged.

The original Chinese directory-name exclusion pattern in .dockerignore remains
unchanged because it is a filesystem pattern, not prose. Its explanatory comment
is English. The non-ASCII authentication test retains its original input via
Unicode escapes; this remains test input, not a user-facing message.

The supplied Airtable document, original PDFs, and expected answers are
preserved byte-for-byte. Only project-owned synthetic labels were translated.
No evaluator_private or held-out answers were requested, read, copied, or edited.

## Verification performed in this follow-up

Commands ran from receipt-agent/. Results below are actual execution results.

| Check | Result |
| --- | --- |
| File-location inspection | Confirmed the project-root v1.1 authority, absent workspace-root schema/copy, and five PDF/JSON pairs in the requested directories |
| Pre-edit development compatibility check | All five data objects accepted by ReceiptData; JSON-mode round trips exactly matched supplied data; all corresponding PDFs existed |
| Existing test discovery correction | Updated the compatibility test from development/*.json to development/expected/*.json and development/pdfs/*.pdf; unwraps data without changing evaluation metadata or shared schema |
| `.venv/Scripts/python -m pytest -q` | 20 passed, 0 skipped, 1 warning in 1.48 seconds |
| Independent Uvicorn subprocess within pytest | Passed: application startup and actual HTTP /health 200 on a dynamically assigned PORT; process cleaned up |
| Health, authentication, and business HTTP contracts | Passed: /health 200; missing/incorrect/non-ASCII API keys 401; valid authenticated POST/GET/JSON-export/CSV-export 501; invalid parameters 422 |
| Configuration import/startup contracts | Passed: import without configuration; startup rejects missing APP_API_KEY |
| Shared models and synthetic Airtable contracts | Passed: Decimal strings, ISO date, nulls, non-finite rejection, response round trip, exact six-column mapping, complete RawJSON, and synchronization eligibility |
| Development schema compatibility in pytest | Passed: all five data objects, exact JSON round trips, wrapper keys, case identifiers, status/issue-code representations, and matching PDF/JSON filenames; no longer skipped |
| `.venv/Scripts/python -m pip check` | Passed: No broken requirements found |
| Original-document and fixture SHA-256 comparison | Passed: all 11 files unchanged (the supplied v1.1 document, five PDFs, and five expected JSON files) |
| Project language scan using rg and the Han Unicode property | Passed for project-owned prose: the only remaining literal Han text is the intentionally preserved directory-name exclusion pattern in .dockerignore; fixtures, caches, and the virtual environment were excluded |
| Model extraction, business validation accuracy, live receipt API processing, persistence, idempotency, remote Airtable schema/writes, or notification delivery | NOT RUN; these features are unimplemented or outside this follow-up |
| Docker build/startup, container health, volume permissions/persistence, SIGTERM shutdown | NOT RUN in this follow-up; prior Docker Engine check failed |

The warning is the existing Starlette TestClient reference to a deprecated AnyIO
BlockingPortal alias. It does not change these test outcomes. Schema compatibility
does not demonstrate receipt extraction accuracy, validate printed PDF contents,
or execute the business validation rules. Tests do not use expected answers to
fabricate actual API or Airtable results.

## Earlier phase 1 history

During the initial skeleton task, the workspace was empty and not a Git repository.
No v1.1 document or development samples were present then. The initial handoff
therefore correctly reported those checks as not run. The supplied v1.1 document
and development fixtures are now present; the compatibility and document checks
above supersede those earlier blockers.

Initial environment: Python 3.12.10 and a project-local .venv. Dependency download
first failed due to sandbox network restrictions and then succeeded with user
authorization. Initial pytest: 19 passed, 1 skipped, 1 warning in 1.58 seconds.
Initial pip check and application compileall passed.

Initial Docker client version: 29.2.1. Reading the user's Docker config produced
a permission warning, and docker info failed because the docker_engine named
pipe did not exist. Docker build/startup were not run. Windows subprocess
termination does not verify container SIGTERM behavior.

## v1.1 document review and remaining work

The supplied authority preserves Expense Tracker / Receipts, Vendor as primary,
and the six exact mapping names already used by the adapter. It specifies
complete RawJSON including all items/nulls, numeric Airtable Amount, and saved
plus validation.passed=true eligibility. These match the existing pure mapper.

The document also requires stable IDs for repeated identical PDFs, unique IDs
for distinct PDFs, duplicate synchronization prevention, and locally saved
Airtable rec... IDs. These are future implementation requirements, not features
of the current skeleton. The document's remote ReceiptID creation and physical
field settings remain unconfirmed; this task performed no account inspection
or Airtable modification.

Unimplemented: model extraction, business validation rules, atomic PDF storage,
SQLite persistence/migrations, recovery/idempotency, remote Airtable requests,
notification event recording, exports, and connected upload UI.

The next Agent must read the four required files and wait for an explicit
next-phase assignment. The v1.1 document and development data no longer need to
be requested again. For a later model phase, confirm provider, MODEL_NAME, PDF
input method, size/page limits, timeouts, cost limits, validation tolerances,
and failure/recovery behavior. Inject credentials through environment/secret
management rather than source code or chat.

When Docker Engine is available and the relevant verification is authorized,
check image build/startup, Linux dependency availability, UID 10001 volume
permissions, persistence, health checks, and SIGTERM shutdown. Do not claim these
checks passed based on local Windows tests. Do not deploy or proceed to model
development as part of this task.

# Independent phase 3 acceptance handoff - 2026-10-28

This section records the later independent offline acceptance assignment. It
does not replace or relabel any historical test or live extraction result above.
No new feature, business code, shared schema or business contract was changed.
The user authorized new synthetic cases instead of historical-output substitutes
for this independent run. Communication was Chinese; all added project prose,
test code and evidence labels are English.

Review [the independent report](acceptance/phase3_independent/REPORT.md), its
contract coverage/error table, and the adjacent retained evidence. Test oracles
were fixed in DESIGN.md before reading implementation details. Existing test
contents, development answers, historical extraction results, .env, and private
evaluation data were not used to construct or run these tests. Required handoff
document reads were not used as test-answer sources.

| Executed command | Actual result |
| --- | --- |
| `git rev-parse HEAD` / `git status --short` | Both exit 128: not a Git repository; commit and pre-existing changes unavailable |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\capture_baseline.py` | Exit 0; SHA-256 baseline of 29 business source/authority/dependency files |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\run.py` | Exit 1; FIRST RUN preserved: 90 run, 85 passed, 0 assertion failures, 5 test-helper cleanup errors, 0 skipped; 8.703 seconds |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\diagnose_harness.py` | Exit 0; stdlib-only reproduction: SQLite context manager leaves connection open and Windows unlink fails until explicit close |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\run.py --record resource-fix-run` | Exit 0; same 90 cases, 90 passed, 0 failures/errors/skips; 8.047 seconds |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\verify_evidence.py` | Exit 0; 29 frozen hashes unchanged; original first-run source preserved; assertions and case IDs unchanged |

The first-run errors belong to the new test helpers: two helper connections used
the SQLite transaction context manager without closing the connection. The only
test correction adds contextlib.closing at those sites and its import. No
assertion or test data changed. The runner gained a distinct evidence record
name. First-run-source/, first-run.console.txt and first-run.results.json remain
available alongside separate resource-fix-run artifacts. No product defect was
established in the executed scope; the first run must not be described as clean.

Coverage includes required omissions/nulls/blanks/zero, Decimal precision and
conflicts, conservative unknown applicability, discount-only normalization and
audit/raw preservation, input immutability, saved/needs_review/query snapshots,
duplicate and same-name handling, 17 concurrent requests across four instances,
nine concurrent SQLite claims, terminal-write guards, atomic original failures,
sequential fresh-interpreter restart/recovery, injected technical failures,
uncommittable storage recovery, and normal caller cancellation. All service
tests explicitly inject extractors and use isolated temporary DATA_DIR paths.
Both runs reported zero isolation guard violations and unchanged source hashes.

NOT RUN: the existing regression suite, development/private evaluation, PDF
parsing/model accuracy, real model requests, HTTP/auth/business routes, Airtable,
UI, exports, notifications, Docker/deployment, destructive crash/power-loss and
platform-volume tests, POSIX/symlink checks, or multi-process operation. The
runtime failures were injected and interrupted states prepared through public
storage interfaces. No final website-to-Airtable end-to-end success is claimed.

Blocker: Git commit/diff provenance cannot be established in this non-Git
workspace; hashes establish only stability during this session. No material
interface mismatch was encountered in the exercised scope. Unspecified exact
message/failure-code strings and malformed-PDF policy were not invented.

Next steps require a new user assignment: review this evidence and provenance
blocker before authorizing any fix or later integration. Independent acceptance
is complete. Stop and wait for review; do not implement the final upload/Airtable
flow or run any live service/model/deployment work.

Final read-only checks: all 29 frozen hashes still match; the prior TASKS.md
content is preserved as an exact byte prefix. `rg -n '\p{Han}'
acceptance/phase3_independent` returned no matches (normal no-match exit 1).
