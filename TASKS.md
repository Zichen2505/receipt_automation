# Phase 3 handoff and verification record

Latest assignment: bounded live connectivity acceptance resumed and passed,
2026-10-28, after the user privately replaced the local APP_API_KEY. Exactly one
model extraction and one Airtable creation were made. See the final section for
actual evidence, IDs, usage, comparisons and limits. The prior startup failure
remains preserved below; earlier restrictions/results are historical and are
superseded only by the latest explicit user assignment.

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

# Upload/query API integration handoff - 2026-10-28

Repository: https://github.com/Zichen2505/receipt_automation.git.
receipt-agent is the verified Git root. The remote was empty. Initialized main,
reviewed/staged 61 safe files, committed and pushed baseline
f7de7ed2c8a751591331a9e3490412fc65c833b7. Development is on the separate
feature/receipt-upload-query-api branch, without merging or force-pushing. The
earlier missing-Git provenance blocker is resolved for this baseline forward;
it does not retroactively create a historical commit for the original run.

Scope: POST/GET now delegate to existing ReceiptService, retaining X-API-Key.
Added actual PDF admission, configurable byte/page limits, bounded multipart
parsing, sanitized errors, and HTTP wait timeouts that keep work alive without
inventing a terminal outcome. Graceful shutdown waits for retained operations.
Exports remain 501; sync=skipped and notification=not_sent. Shared models,
validation and storage code remain unchanged. Service behavior is unchanged;
only its stale docstring was corrected. PROJECT_SPEC.md, README.md, environment
example, deployment conventions and AGENTS.md reflect the user-authorized scope.
Explicit local --env-file loading never overrides existing environment variables
and disables interpolation; imports/ASGI startup never implicitly read dotenv.

| Executed command/check | Actual result |
| --- | --- |
| Git remote read/init/root/stage/audit/commit/push | Remote had no refs; main baseline above pushed without replacing existing work; initial sandbox/ownership failures handled by scoped elevated commands |
| `.\.venv\Scripts\python -m pip install pypdf==6.21.3 --no-deps` | Succeeded after querying the index with network authorization; parser pinned in requirements.txt |
| `.\.venv\Scripts\python -B scripts\offline_regression.py tests/test_http_receipts.py` | Initial 37 passed; expanded final HTTP-only run 42 passed; both saved locally |
| `.\.venv\Scripts\python -B scripts\offline_regression.py` | Final 107 passed, 0 failed/errors/skipped, 1 existing AnyIO deprecation warning in 4.77 seconds |
| `.\.venv\Scripts\python -B acceptance\phase3_independent\run.py --record upload-query-20261028 --snapshot-current` | Original 90 cases passed; 0 failed/errors/skipped; source/contract frozen throughout run; 8.532 seconds |
| `.\.venv\Scripts\python -m pip check` | Passed: no broken requirements |
| `git diff --check` and focused baseline diff/hash comparisons | Passed; independent test files/assertions byte-unchanged, original evidence hashes unchanged; shared schema, validation, storage and supplied Airtable authority unchanged |

Final local evidence: data/http_api/20261028T093620Z_95e0141b/ and
acceptance/phase3_independent/upload-query-20261028.*. Original independent
evidence remains preserved alongside it, excluded from Git. Regression guards
removed application credentials, blocked actual SDK/external network/root .env
access in parent/children, and recorded zero violations. Authorized fixture and
authority hashes are unchanged. No real model call was made. Two old upload/query
501 stub expectations were superseded by new HTTP cases; independent acceptance
assertions were not modified. The independent runner gained only explicit new
run-name/current-snapshot support; the original freeze/evidence was not replaced.

Coverage includes valid upload/query, authentication, invalid/empty/zero-page/
encrypted PDF, exact byte/page limits, multipart overflow and spool cleanup with
misleading/missing Content-Length, duplicate/same-name PDFs, business review,
durable extraction/storage faults, uncommittable failure recovery, production
adapter wiring with an offline double, 504 continuation to saved/failed, query
timeouts, request cancellation, graceful shutdown, and dotenv/limit configuration.

Secrets, .env copies, real PDFs, databases, original fixtures, runtime data and
acceptance logs/JSON/reports/snapshots remain excluded. scripts/audit_staged.py
checks the staged index against local/environment credential values and common
credential patterns without printing matching values. See docs/API_HANDOFF.md
for the detailed retained commands, results, implementation and limits.

NOT RUN: live model-backed HTTP, Airtable, UI/browser uploads, exports,
notifications, Docker/deployment, destructive crash/power-loss or malicious-PDF
resource tests. No final public URL-to-Airtable success is claimed. Single
process/worker/event loop per DATA_DIR remains mandatory. Upload/parser/ingress
deadlines and resource isolation are not provided; a 504 leaves the result
unknown and does not stop processing. Full historical regression requires the
authorized local fixtures/history, deliberately absent from the remote repository.

No active implementation blocker remains. Next step is user review of the
development branch; live model/Airtable/UI/deployment requires a new assignment.
After committing and pushing this handoff, stop and wait for review.

Final pre-commit review: 23 staged development files, zero secret/private-file
audit findings, clean cached whitespace check. The English-language scan found
no Han characters in changed project prose/code (rg no-match exit 1). Ignored
path checks confirmed .env, real PDFs/answers, historical data and original/new
acceptance evidence remain local. The development commit ID is reported in the
delivery response and can be resolved from this handoff's enclosing Git commit.

# Airtable synchronization handoff - 2026-10-28

Read AGENTS.md and its four required files before implementation. Confirmed the
clean working tree and the prior upload/query branch locally and remotely at
279c9a0ebc3c51e6273deb4ec5a2f30238144ff2. Main remains
f7de7ed2c8a751591331a9e3490412fc65c833b7. Repository remains
https://github.com/Zichen2505/receipt_automation.git. This phase uses the separate
feature/receipt-airtable-sync branch based on the prior development commit;
no merge or force push is performed. The final commit is this section's enclosing
commit and is reported in the delivery response.

Implemented eligible Airtable sync strictly after local commit, using the
unchanged six-column mapper/authority and complete RawJSON. Shared schema and
validation are unchanged. Sync status and record_id persist independently of
local saved/data/original/metadata. ReceiptID lookup and durable uncertainty
before POST protect retries; confirmed IDs prevent repeated creation. Missing
configuration returns not_configured without HTTP. Definite rejection is failed;
ambiguous POST outcomes are unknown, and unknown retries only query, never
blindly create. Startup recovers pending to unknown without network work.

Added authenticated POST /api/v1/receipts/{receipt_id}/sync, using persisted data
without extraction/model work. Identical uploads also retry eligible unsynced
records. HTTP routes only delegate; Integration owns HTTP, Service orchestrates,
Storage persists. AIRTABLE_TIMEOUT_SECONDS defaults to 15, finite positive.
Runtime HTTPX dependency pins were moved from development without downloads or
version changes. Updated English specification, README, environment example,
deployment conventions and AGENTS.md. Details: docs/AIRTABLE_HANDOFF.md.

| Executed command/check | Actual result |
| --- | --- |
| Remote branch/main `git ls-remote` | Matched prior commits above; sandbox connection and elevated relative-origin failures resolved using explicit repository path/URL |
| `.\.venv\Scripts\python -B scripts/offline_regression.py tests/test_airtable_sync.py` | 30 passed, zero failures/errors/skips; data/http_api/20261028T163905Z_07543b46/ |
| `.\.venv\Scripts\python -B acceptance/airtable_independent/run.py --record first-run` | 13 passed; zero failures/errors/skips/guard violations; original evidence retained |
| First full regression | 136 passed, 1 failed; data/http_api/20261028T164149Z_c06c4d63/; old 30 ms timeout helper's subsequent query also timed out |
| Focused detached-failure timeout regression | Both original parameter cases passed; data/http_api/20261028T164249Z_5a2247b1/ |
| Second full regression | 136 passed, 1 failed; data/http_api/20261028T164332Z_5f692f4a/; helper inspected the claim before it was durably created |
| `.\.venv\Scripts\python -B scripts/offline_regression.py` final | 137 passed, zero failures/errors/skips; 1 existing AnyIO warning; 5.32 seconds; data/http_api/20261028T164408Z_dea29ead/ |
| `.\.venv\Scripts\python -B acceptance/airtable_independent/run.py --record deadline-expanded` | 15 passed; zero failures/errors/skips/guard violations; frozen source/test hashes unchanged; 1.547 seconds |
| `.\.venv\Scripts\python -B acceptance/phase3_independent/run.py --record airtable-20261028 --snapshot-current` | Original 90 passed; zero failures/errors/skips/guard violations; 8.844 seconds |
| `.\.venv\Scripts\python -B acceptance/phase3_independent/run.py --record airtable-final-20261028 --snapshot-current` | Original 90 passed again; zero failures/errors/skips/guard violations; 8.719 seconds; final source/spec snapshot |
| `.\.venv\Scripts\python -B scripts/verify_airtable_handoff.py` | Prior assertions unchanged by AST comparison; original independent files/shared schema/validation/authority unchanged; retained historical evidence/first-run source hashes matched |
| `.\.venv\Scripts\python -m pip check` | No broken requirements |
| `git diff --check` | Passed |

The only prior-test edit fixes timing in its helpers: await extractor entry
before inspecting processing storage, and use a normal five-second budget for
the later query. The initial 30 ms HTTP processing timeout and all original
assertions are unchanged. No product timeout was weakened. Both initial full-run
failures remain recorded. The original independent suite/assertions/evidence are
unchanged. The new separate Airtable suite uses literal contract oracles with no
prior data/tests, but is authored by the implementation agent and does not claim
external human review. Two deadline cases were added separately after its first
13-case run, without changing prior assertions.

All regressions use offline guards; all original development inputs and authority
hashes matched before/after. Coverage includes six-column/item/null fidelity,
eligibility, configuration, success/401/403/422/429/408/5xx/transport/invalid-success
outcomes, duplicates/concurrency, model-free retry, unknown lookup reconciliation,
pending recovery, restart, sync-state write faults, production HTTP/auth/query,
adapter and HTTP deadlines, continuation, and unchanged 501 exports.

NOT RUN: real model/Airtable/account/schema/permissions requests, UI, notifications,
exports, Docker/deployment, destructive crash/power-loss, malicious-PDF resource
isolation, platform volumes or multi-process operation. The remote table and
ReceiptID field configuration remain unconfirmed. No remote schema was modified.

Limits: single process/loop/DATA_DIR and fixed Airtable destination; no global
rate limiter or automatic scheduler (wait at least 30 seconds after 429 before
retry). Unknown with no matching row requires deliberate operator reconciliation
under a new assignment; there is no automatic reset/create. Unknown is preserved
if configuration is removed. Confirmed remote rows are not continuously audited.
The explicit local-only service mode retains skipped; HTTP always injects the
adapter. See PROJECT_SPEC.md for these decisions and complete HTTP semantics.

No active implementation blocker remains in the offline assignment. Complete
staged secret/private-file/whitespace review, commit and push only the development
branch, verify remote commits, report results and stop. Any live verification,
maintenance reset, UI, notifications or deployment requires a new assignment.

Final pre-commit review: 23 explicitly selected files staged. Executed
`.\.venv\Scripts\python -B scripts/audit_staged.py`: passed, zero secret or
private-file findings. `git diff --cached --check` passed. The English-language
scan of changed project files found no Han text (normal rg no-match exit 1).
Remote pre-push check found no existing feature/receipt-airtable-sync branch,
and main/prior-development refs still matched the verified commits above.
Local PDFs, expected answers, databases, dotenv and all old/new acceptance
evidence remain excluded from the index. Final commit/push/ref verification is
reported in the delivery reply; stop after that authorized push.

# Live connectivity acceptance stopped - 2026-10-28

The user explicitly authorized read-only Airtable verification, one development
PDF upload through authenticated local HTTP, at most one real model extraction
and at most one Airtable row creation. They required stopping on any failure or
unknown, without model retries, blind creation, schema changes, deletions or
state resets. No new business module, UI, notification, export or deployment was
authorized. This bounded assignment superseded the prior offline-only restriction
for the intended acceptance, but did not authorize changing credentials.

Read AGENTS.md, PROJECT_SPEC.md, AIRTABLE_SCHEMA.md, TASKS.md and the canonical
app/schemas/receipt.py before the acceptance attempt. Verified a clean working
tree, local HEAD and the actual remote feature/receipt-airtable-sync ref at
74b8542d82929eaf700aa0bd962c755455366c62. Main remained
f7de7ed2c8a751591331a9e3490412fc65c833b7. No merge or force push was performed.

Loaded only the local project .env for acceptance, with interpolation disabled;
values were never displayed. A sanitized presence check found all six required
setting names nonblank, but a presence check does not establish valid credentials.
A.pdf was a locally inspected candidate: one unencrypted page with explicit
merchant/date/currency/total and five items. It was not uploaded. No expected
answer or private/held-out data was read for selection or this acceptance.

Prepared exclusive local evidence under
data/live_acceptance/20261028T170341Z_cd6c4914/ (ignored by Git).
The intended isolated DATA_DIR was that directory's store/ subdirectory.
Temporary acceptance-only launcher/controller files remain there for provenance;
they are not application modules and contain no credential values. The launcher
would run the existing app with real transports, suppress credential-bearing logs,
deny expected/private-file access and enforce durable budgets of one model
extraction and one Airtable creation across restarts. It substitutes no extraction
or remote response. The startup failed before these transports or the app were
initialized, before a listener or receipt store was created.

| Executed command/check | Actual result |
| --- | --- |
| Scoped `git ls-remote` for Airtable development/main | Passed; matched the two full commits above |
| Local dotenv presence-only check | .env exists; APP_API_KEY, MODEL_API_KEY, MODEL_NAME, AIRTABLE_TOKEN, AIRTABLE_BASE_ID and AIRTABLE_TABLE_ID nonblank; no values printed |
| Local pypdf inspection of development/pdfs/A.pdf | One unencrypted page, 2200 bytes; selection inspection only, no model/text-probe request and no expected read |
| Syntax/ignore checks of the two local acceptance helpers | Parsed successfully; both paths ignored by Git |
| Absolute `.venv/Scripts/python.exe -B data/live_acceptance/20261028T170341Z_cd6c4914/server_audit.py 1` (authorized outside sandbox) | Exit 1; Settings.from_env raised ValueError: APP_API_KEY must be set to a non-placeholder secret; process wall time 0.1589859 seconds |
| Subsequent sanitized configuration classification | Confirmed APP_API_KEY nonblank but equal to the known placeholder; value not displayed or changed |
| Local evidence capture | startup-failure.json retains error category, unused budgets, absent IDs/usage, unrun checks and source/PDF hashes |
| `git diff --exit-code HEAD -- app AIRTABLE_SCHEMA.md tests/fixtures/development` | Passed; no application/authority/tracked fixture changes |

Actual request counts for this assignment: model extraction 0; text probes 0;
Airtable reads 0; Airtable creates 0; local HTTP PDF uploads 0. No receipt_id or
Airtable record_id was generated. Model usage and extraction duration are not
applicable, not zero-token evidence of a model request. No server was left running.
The credential file was not modified; no credentials or evidence were committed.

Outcome: STOPPED / configuration_error at HTTP startup. Per the user's stop rule,
no attempt was made to fix .env, restart the server, read Airtable, upload/reupload
the PDF, synchronize, delete a row or reset local state. No paid request occurred.

NOT RUN: target Airtable access/permissions/schema verification; authenticated
PDF processing; model content extraction/usage; local-to-remote six-column and
RawJSON comparison; post-extraction comparison against the original PDF; duplicate
upload/row-count check; service-restart persistence query; regressions, UI,
notifications, exports and deployment. In particular, neither local/remote
consistency nor content correctness against the original PDF has been accepted.

Blocker and next step: the user must set a valid non-placeholder APP_API_KEY
privately in the local .env, then explicitly resume the live acceptance. Do not
paste credentials into chat. The server-side startup error does not establish
whether the model or Airtable credentials/permissions are valid. Preserve this
failed attempt and use fresh, separately recorded evidence for any resumed run.
The at-most-one model/create budgets were unused in this attempt. Stop here.

# Resumed live connectivity acceptance passed - 2026-10-28

The user explicitly resumed the bounded live acceptance after privately replacing
APP_API_KEY. Read the required handoff files again and preserved the existing
TASKS.md change and all prior failure evidence. The updated key passed the existing
Settings validation. No key was displayed, edited by the agent, placed in a command
argument or committed. Configuration was loaded from the project-root .env with
interpolation disabled. Authenticated local HTTP calls used the X-API-Key header.

Local HEAD and the actual remote feature/receipt-airtable-sync ref were verified
again at 74b8542d82929eaf700aa0bd962c755455366c62. Main still pointed to
f7de7ed2c8a751591331a9e3490412fc65c833b7. No application module, prompt, shared
schema, validation rule, fixture or remote schema was changed. No merge or force
push occurred. This assignment updates the handoff locally; it does not create
a new implementation commit.

Fresh evidence: data/live_acceptance/20261028T210509Z_521a46dc/ (ignored by Git).
Isolated DATA_DIR: that directory's store/. The previous failed attempt remains
unchanged in data/live_acceptance/20261028T170341Z_cd6c4914/. Acceptance-only local
helpers ran the existing Uvicorn app with real HTTP transports; no extraction or
response was substituted. Their observation wrappers suppressed logging of secrets,
denied expected/private-file reads and durably limited model requests and Airtable
creates to one each across both server processes. No limit-blocked call occurred.

## Actual request ledger

| Request | Count | Actual result |
| --- | --- | --- |
| Real model POST /v1/responses with the complete development A.pdf | 1 | HTTP 200, completed; no text probe, fallback or retry |
| Airtable GET for read-only table/six-field preflight | 1 | HTTP 200; FALSE() filter avoided fetching unrelated rows; 1.875 seconds |
| Airtable GET for service ReceiptID lookup before create | 1 | HTTP 200, no matching row; 0.312 seconds |
| Airtable POST for the validated, locally saved receipt | 1 | HTTP 200; exactly one returned record; 0.328 seconds |
| Airtable GET for independent remote/local comparison | 1 | HTTP 200, exactly one matching ReceiptID; 0.421 seconds |
| Airtable GET after duplicate upload | 1 | HTTP 200, same single record and field values; 0.422 seconds |
| Local HTTP GET /health | 1 | HTTP 200 |
| Local authenticated PDF POST, including the required identical duplicate | 2 | Both HTTP 200; the second invoked no model or Airtable operation |
| Local authenticated GET after process restart | 1 | HTTP 200; no model or Airtable operation |

Totals: model extraction requests 1; text probes 0; Airtable reads 4; Airtable
creates 1; updates/deletes/schema writes 0; automatic/manual model retries 0.
All six external requests returned HTTP 200. Error categories: none in this
resumed run; unknown outcomes: none. The earlier startup configuration error
remains a separate historical failed attempt with zero external requests.

## IDs, usage and timing

- Receipt ID: 343e9d7f-df4c-4902-b5e8-61bb3c20c669.
- Airtable record ID: recrfWVU8Rhsyp2x9.
- Actual model: gpt-5.6-terra, unchanged from local configuration.
- Model response ID: resp_0ddae32a3a0631ad016ae263c0a50487d1b2f247f2892489e4.
- Model request ID: req_1a85029f3f104c8fa4e658590859f609.
- Usage: 748 input + 172 output = 920 total tokens; cached, cache-write and
  reasoning tokens all 0. No monetary cost or remaining balance was inferred.
- Extraction metadata elapsed: 3.6061838001478463 seconds. Transport response
  observation: 3.3909999998286366 seconds; these measure different boundaries.
- Initial local upload HTTP elapsed: 4.655999999959022 seconds.
- Identical duplicate HTTP elapsed: 0.2029999999795109 seconds.
- Restart query HTTP elapsed: 0.20300000021234155 seconds.
- Original input: tests/fixtures/development/pdfs/A.pdf, one unencrypted page,
  2200 bytes, SHA-256 fd98df1bae90f5e9dde7ce127e39e872c114ae3c8c4c8f74515623751dddd968.

## Separate acceptance conclusions

Local-to-remote consistency: PASSED. The first upload returned saved with
validation.passed=true and sync.status=synced. SQLite retained the original PDF,
complete data, validation, extraction metadata and returned record ID. An actual
targeted Airtable GET found exactly one corresponding ReceiptID, with the exact
six columns Vendor, Date, Amount, Currency, RawJSON and ReceiptID. Amount was a
JSON number matching the local printed total; RawJSON parsed to the complete
local data object, including all five ordered items, decimal strings, tip=null
and discount=null. This establishes consistency, not by itself extraction accuracy.

Content against the original PDF: PASSED in the reviewed text scope. After
extraction and persistence, independently decoded and manually reviewed the
original PDF text operators using pypdf, without any expected-answer read. All
30 scalar/item/count comparisons matched: MAPLE MARKET; 2026-10-12; MM-10482;
USD; subtotal 30.35; tax 2.43; total 32.78; Apples/Bread/Milk/Coffee/Soap with
their printed quantities, unit prices and amounts. Tip and discount are not
printed and correctly remain null. Original text and each comparison are retained
in original-pdf-text.txt and pdf-content-review.json. This was not a visual render
or an evaluation of another receipt/model request.

Duplicate prevention: PASSED. Uploading identical original bytes again returned
the entire same ReceiptResponse, receipt_id and record_id. Request audit showed
no additional attempted or dispatched model/create request and no budget guard
intervention. A separate actual Airtable GET still found exactly one corresponding
row with unchanged fields and the same record ID.

Restart persistence: PASSED. Generation 1 (PID 276832) shut down normally. A new
process, generation 2 (PID 294416), started the existing app against the same
isolated DATA_DIR. Its authenticated query returned the unchanged complete
ReceiptResponse and synced status. A separate local stored-record comparison
also verified unchanged extraction/usage/audit metadata and original PDF bytes.
No external request was made on restart or query. Both server processes then
shut down normally; no acceptance service was left running.

## Executed commands and retained checks

Helper commands below used the project .venv Python with -B and absolute paths
for authorized outside-sandbox execution where real network access was needed.
All helpers reside only in the fresh ignored evidence directory, not app/.

| Command/check | Actual result |
| --- | --- |
| Scoped git ls-remote | Remote development and main commits matched the verified IDs above |
| Configuration validation / copy of prior acceptance helpers into fresh directory | Passed; only presence/validity booleans displayed; original failure files preserved |
| server_audit.py 1 | Existing HTTP app started on loopback with the isolated store |
| check.py preflight | Passed; actual health and read-only Airtable/six-field request |
| check.py upload | Passed; one complete PDF, one extraction, one row, stored saved/synced response |
| check.py verify_remote | All record-ID/six-column/data/RawJSON checks passed against an actual Airtable response |
| review_pdf.py | 30 post-extraction original-PDF comparisons passed, zero expected reads |
| check.py duplicate / check.py verify_duplicate | Identical response and one unchanged actual Airtable row |
| Graceful stop generation 1 / server_audit.py 2 / check.py restart_query 2 | New PID, same persistent result; both process exit codes 0 after graceful stops |
| finalize.py | 18 retained acceptance invariants passed; acceptance-summary.json written without replacing any earlier evidence |
| Credential scan of fresh evidence | 36 files checked against actual backend credential values; zero findings; values not printed |
| git diff --check / git diff --exit-code HEAD -- app AIRTABLE_SCHEMA.md tests | Passed; no business code/authority/test changes |

Retained evidence includes real request timestamps/statuses/counts, usage/request
IDs, original input hash, the SQLite database and original PDF, initial/duplicate/
restart responses, actual scoped Airtable snapshots, separate remote/local and
PDF-content comparisons, server start/stop records, credential audit and the
final acceptance-summary.json. All remain local and ignored; no credential
values or evidence were submitted to Git. Only TASKS.md is a tracked change.

NOT RUN: more development PDFs, expected/private/held-out evaluation, visual PDF
rendering, account-wide uniqueness audit, remote field-configuration/physical-type
inspection, regression suites, browser UI, notifications, exports or deployment.
No table/field structure, existing record, local sync state or original receipt
was modified to force success. The one newly created authorized receipt row is
retained; it was not deleted as cleanup. This proves the bounded local HTTP-to-
model-to-Airtable path for this PDF and configuration, not broader production
readiness. No blocker remains for this bounded acceptance. Stop here; further
live requests or feature/deployment work require a new explicit assignment.


# Minimal upload page handoff - 2026-10-28

The user explicitly assigned a minimal same-origin upload page, offline browser
verification, documentation, and a new development-branch commit/push. This
supersedes the historical no-UI restriction only for this assignment. No real
model/Airtable request, notification, export implementation or deployment was
performed or authorized. Read AGENTS.md, PROJECT_SPEC.md, AIRTABLE_SCHEMA.md,
TASKS.md and app/schemas/receipt.py before implementation. All existing TASKS.md
content, including the two latest live-acceptance records, is preserved as an
exact byte prefix (compared with the pre-edit local snapshot). Previous evidence
and original PDFs/answers remain unchanged.

Repository: https://github.com/Zichen2505/receipt_automation.git.
Development branch: feature/minimal-upload-page, based on
74b8542d82929eaf700aa0bd962c755455366c62. The pre-push remote check found no
existing branch with this name. Remote feature/receipt-airtable-sync still
matched that base commit; main remained
f7de7ed2c8a751591331a9e3490412fc65c833b7. No merge, reset or force push is used.
The implementation commit is this section's enclosing commit; the delivery
response reports its resolved ID and actual push/ref-verification result.

## Delivered behavior

- GET / is the public upload page; GET /web/upload.js and /web/style.css serve
  its two fixed assets. FastAPI reuses app/web with no frontend framework/build.
  Presentation routes perform only asynchronous file delivery. Existing receipt
  routes, shared models, service/integration/storage code, validation rules,
  API contracts and the sole AIRTABLE_SCHEMA.md v1.1 mapping are unchanged.
- English, responsive HTML/CSS/JavaScript provides a password access-key input,
  PDF picker, upload button, waiting message, result and error regions. One
  same-origin multipart POST uses the existing file field and X-API-Key header.
  The key never enters source, URL, multipart body, cookies, browser storage or
  logs. It stays in the input's memory and clears on navigation/cache restore.
  MODEL_API_KEY and AIRTABLE_TOKEN remain backend-only. CSP, no-store, nosniff,
  no-referrer and redirect rejection support that boundary.
- Merchant, date, currency, total, other receipt scalars, complete ordered line
  items and structured validation issues render through textContent/DOM creation.
  Original decimal strings remain intact; null displays Unknown, zero stays zero.
  No response-derived content is interpreted as HTML.
- Local saved/needs_review is separate from sync; only sync.status=synced gets
  the Synced to Airtable label and success styling. Failed/unknown/pending/
  not_configured/skipped are distinct. Known 502 failures retain the stored ID
  without successful local-processing claims.
- All in-flight controls are disabled and duplicate submit events are guarded.
  Previous result/error is hidden for a new submission; controls recover on
  every completion path. Handles authentication, PDF admission errors, review,
  synchronization errors, 500/503/504, malformed responses and connection loss.
  Browser wait is bounded at 180 seconds, including response-body reading;
  timeout means unknown and does not cancel server processing. No automatic
  re-upload, query, retry-sync or polling is added.
- README and PROJECT_SPEC describe entry, usage, security, states, timeouts,
  offline reproduction and limits. The pinned Playwright dependency is
  development-only; production requirements and Docker configuration are intact.

## Executed checks and retained results

| Command/check | Actual result |
| --- | --- |
| Initial git switch -c | Sandbox denied .git write; no branch created by that failed command |
| Repository-scoped elevated git switch | Initial ownership check rejected; per-command safe.directory succeeded without changing global Git settings |
| Initial pip install playwright | Sandbox socket access denied; dependency unavailable in that attempt |
| Authorized pip install playwright --retries 0 --disable-pip-version-check | Installed playwright 1.64.1, pyee 14.0.0 and greenlet 3.5.6; no browser binary downloaded |
| First scripts/offline_regression.py tests/test_web_page.py tests/test_web_browser.py | 4 passed, 25 failed, 3 teardown errors; data/http_api/20261028T212114Z_26c6a07d/ retained |
| Corrected focused page/browser regression, same command | 29 passed, 0 failures/errors/skips, 1 existing warning, 15.22 seconds; data/http_api/20261028T212158Z_3ca2fcec/ |
| scripts/offline_regression.py | 166 passed, 0 failures/errors/skips, 1 existing warning, 20.01 seconds; data/http_api/20261028T212335Z_fe4fae03/ |
| acceptance/phase3_independent/run.py --record upload-page-20261028 --snapshot-current | Original 90 cases passed, no failures/errors/skips/guard violations, 8.954 seconds; fresh run snapshot retained |
| acceptance/airtable_independent/run.py --record upload-page-20261028 | Original 15 cases passed, no failures/errors/skips/guard violations, 1.484 seconds; source hashes unchanged during the run |
| scripts/verify_airtable_handoff.py | Original assertions, protected tracked files, first-run sources and historical independent evidence all unchanged |
| .venv/Scripts/python -m pip check | Passed: No broken requirements found |
| Focused git diff --exit-code HEAD for business/shared/authority/existing-test/acceptance paths | Passed: no changes |
| git diff --check | Passed |
| Origin comparison and scoped git ls-remote | Authorized repository matched; main/prior-development refs matched IDs above; new branch absent before push |
| Pre-edit TASKS.md byte-prefix comparison | Passed; prior work preserved exactly |
| English project-source/documentation Han scan | No matches; normal rg no-match exit 1 |

All Python commands used the project's .venv and verification runners used -B.
The first browser-run failures were in new test helpers: expression-string
wait_for_function invoked eval, correctly blocked by the page CSP. Helpers were
changed to locator-based DOM waits; no product policy or prior assertion was
weakened. Its additional JUnit-property warning was removed by writing browser
metadata to a separate ignored file. The sole final warning is the existing
Starlette TestClient/AnyIO deprecated alias. The original failed run is preserved.

Actual browser: installed Chrome 156.0.8078.48, headless, driven by Playwright.
The test opened the page served by a temporary real loopback Uvicorn app, filled
a synthetic access key, activated the real file-chooser event, selected the
unchanged development A.pdf, clicked Upload PDF, sent actual multipart HTTP and
rendered the resulting persisted local saved/synced response. Its extractor
returned explicitly synthetic data; its Airtable adapter used HTTPX MockTransport
(one simulated GET and POST). Browser request assertions verified exact original
PDF bytes/filename, the header-only access key, empty browser storage and no key
in serialized page source. No expected answer supplied an API result.

Other real-browser cases simulated API states at the HTTP boundary: every sync
state, needs_review, structured issues, null versus zero, malicious merchant/item/
issue strings, 401, empty/invalid/encrypted/oversized PDFs, page/body limits,
500/503/504, durable 502, connection interruption, invalid JSON/response shape,
pending controls/duplicate events, stale-result clearing, reload key clearing
and 390-pixel mobile layout. Virtual time exercised the actual 180-second abort
without weakening the production timeout. No uncaught page JavaScript errors
occurred in the passing runs. Reviewed browser-synced-desktop.png visually;
browser.json and screenshots are retained alongside focused/full regression
JUnit/log/result files, all ignored by Git. Browsers and owned servers closed.

The offline runner removed credentials and blocked real SDK construction,
external Python network and project dotenv/private-file access. Both page runs
and full regression reported unchanged authorized input/authority hashes and
zero guard violations. Browser contexts allowed only the loopback test origin;
backend transports and browser API simulations had no real model/Airtable access.
New implementation verification request counts: real model 0, real Airtable 0.
Prior live acceptance is historical and is not relabeled as page acceptance.

## Limits, unrun checks and stop condition

NOT RUN: live page-to-model-to-Airtable acceptance, Firefox/Safari/Edge, headed
manual native-dialog review, screen-reader audit, deployment/Docker, notifications,
export generation, private/held-out evaluation, power-loss/malicious-PDF resource
isolation, remote schema changes or maintenance. Headless Chrome exercised the
real chooser event and supplied file, not a human-operated OS dialog. The page
has no lookup/history, retry-sync, export or notification controls. A custom
backend wait exceeding 180 seconds may outlast the browser wait; processing
continues and no success is inferred. The usual single process/worker/event-loop
per DATA_DIR and conservative unknown-sync reconciliation limits remain.

The local entry after normal startup is http://localhost:8000/ (or configured
PORT). The normal application uses production integrations; do not upload a new
PDF as an additional live check without a fresh assignment. No service remains
running from verification. No active implementation blocker remains. Complete
staged credential/private-file/whitespace checks, commit/push only this new
branch, verify remote refs, report results and stop. Future work requires a new
explicit user assignment.

Final staged review: 11 explicitly selected files; scripts/audit_staged.py passed
with zero credential/private-file findings. git diff --cached --check passed.
The staged handoff retains the entire prior TASKS.md prefix after Git newline
normalization; working-file bytes retain the original exact prefix. English
source/documentation scan returned no Han matches (normal no-match exit 1).
Only the new page/tests/docs and development-only test dependencies are staged;
credentials, PDFs, answers, SQLite and all old/new runtime evidence remain local.

# Render deployment preparation handoff - 2026-10-28

The user explicitly assigned Render preparation, offline regression, local Docker
acceptance when available, minimal CI, documentation, and a separate branch
commit/push. Cloud deployment and Render service creation are excluded. This
supersedes earlier scope restrictions only for this preparation assignment.
Read AGENTS.md, PROJECT_SPEC.md, AIRTABLE_SCHEMA.md, TASKS.md and
app/schemas/receipt.py before inspecting/editing. Communication remains Chinese;
all added project prose/code comments/handoff records remain English. No agent
delegation, real model request, real Airtable request, schema modification, new
business feature, export, notification or cloud deployment was performed.

## Version and branch provenance

Initial working tree was clean on feature/minimal-upload-page, local and actual
remote commit 45d9924455fae15f1bd6494007aa830a18a2dcd8. That commit includes
the authenticated upload/query API, persisted Airtable synchronization/retry and
same-origin upload page. Created chore/render-predeploy directly from it; no
main merge, reset, overwrite or force push. Repository remains
https://github.com/Zichen2505/receipt_automation.git, with the project itself at
the Git repository root (not an additional receipt-agent/ subdirectory).

Actual initial remote refs also remained:

- feature/receipt-airtable-sync: 74b8542d82929eaf700aa0bd962c755455366c62.
- feature/receipt-upload-query-api: 279c9a0ebc3c51e6273deb4ec5a2f30238144ff2.
- main: f7de7ed2c8a751591331a9e3490412fc65c833b7.

The new branch was absent from the initial remote listing. Initial sandbox
git ls-remote failed due network restrictions; the repository-scoped elevated
read succeeded. Branch creation used scoped safe.directory without changing
global Git configuration. Final commit is this section's enclosing commit; the
delivery reports its resolved ID and actual push/ref-verification result.

## Prepared configuration

- Preserved the production app and all business interfaces/rules unchanged:
  environment-only default startup, 0.0.0.0 plus PORT, single worker/no reload,
  public health/assets, authenticated receipt routes, byte/page/body limits,
  synchronization behavior, shared models and explicit 501 exports.
- Dockerfile already installed the complete pinned runtime requirements and
  copied app/, including app/web. Added build-time pip check and three static
  asset existence checks. Retained exec-form python -m app.main, non-root
  UID/GID 10001, /app/data default and Python-only health probe.
- Restricted .dockerignore to requirements.txt and app/ sources, with subsequent
  recursive exclusions for environment files, keys, runtime databases/PDFs,
  evidence, tests, private paths, virtual environments and caches. Scripts, CI,
  local acceptance evidence, credentials and fixtures are outside the image.
  The original directory-name exclusion pattern is preserved. Actual image
  contents/Linux dependency installation are unverified because no image built.
- Added scripts/docker_acceptance.py as an explicit development-only harness.
  It builds a unique image, mounts a new isolated store, forwards only synthetic
  configuration, uses --network none and performs HTTP checks over container
  loopback. Its helper and original development A.pdf are read-only runtime
  mounts; they never enter the default production CMD or image. It plans three
  sequential containers with the same store: default production smoke checks,
  injected synthetic extraction/HTTPX MockTransport upload-query checks, and
  recreated default production query/duplicate checks. It checks UID/write
  access, original hash/bytes, SQLite results/metadata/record IDs, one extraction
  and two simulated HTTP calls, no extra work on duplicates/restart, and normal
  shutdown. It does not publish ports or contact real services. The two local
  helper tests validate the unavailable result and injected-to-production
  persistence; they are not actual container acceptance.
- No GitHub Actions workflow existed. Added .github/workflows/offline.yml with
  read-only repository permissions, Python 3.12 pinned-dependency installation,
  guarded clean-clone synthetic regression and a production Docker build. No
  real service secrets, original PDFs, expected answers, historical evidence or
  browser binaries are provided. One A.pdf-dependent helper test skips in a
  clean clone. No Render deployment integration/Blueprint is added.
- README and docs/DEPLOYMENT.md provide the exact Render field/environment
  checklist, disk ownership and persistent-store rules, reproduction command
  and actual unverified status. PROJECT_SPEC and AGENTS reflect current scope.
  Existing startup still requires APP_API_KEY; the /health request itself needs
  no key and neither model nor Airtable configuration, and makes no external call.

## Executed commands and actual results

All Python checks used the existing project .venv. Offline runners used -B and
fresh evidence paths. No prior evidence/independent assertion was overwritten.

| Command/check | Actual result |
| --- | --- |
| git status --short --branch / branch -vv / log / remote -v / rev-parse --show-toplevel | Clean upload-page branch; correct repository and included API/sync/page history |
| Scoped elevated git ls-remote --heads | Actual remote matched all four original refs listed above; preparation branch absent |
| Scoped elevated git switch -c chore/render-predeploy | Created branch from the existing upload-page version |
| docker version / docker info, sandbox and elevated | Client 29.2.1 exists; default docker_engine and desktop-linux dockerDesktopLinuxEngine pipes absent; no Engine connection |
| Elevated docker build --tag receipt-agent:render-predeploy . | Failed connecting to Docker Desktop Linux Engine before build; no image built |
| scripts/docker_acceptance.py, sandbox and elevated | Explicit not_run_docker_unavailable, zero completed stages; latest evidence data/docker/20261028T214850Z_dd7eb75c/; earlier data/docker/20261028T214612Z_219e16de/ retained |
| scripts/offline_regression.py tests/test_deployment.py | 2 passed, no failures/errors/skips, protected inputs unchanged, no guard violation; data/http_api/20261028T214611Z_ce887a19/ |
| scripts/offline_regression.py | 168 passed, no failures/errors/skips, 1 existing AnyIO warning, 20.15 seconds; data/http_api/20261028T214814Z_d83c92ec/ |
| Actions-selected seven test files through scripts/offline_regression.py | 92 passed, no failures/errors/skips, 1 existing warning, 1.85 seconds; data/http_api/20261028T214846Z_0138b95d/ |
| Initial inline-Python clean-source simulation | Failed before pytest because the temporary copy omitted tracked AIRTABLE_SCHEMA.md; original failed directory data/render-ci/20261028T214922Z_33b0ef29/ retained; no product/assertion change |
| Corrected fresh inline-Python clean-source simulation including unchanged schema document, excluding fixtures/evidence | 91 passed, 1 explicit absent-A.pdf skip, no failures/errors, protected authority unchanged, no guard violation; data/render-ci/20261028T214931Z_9c0c835b/checkout/data/http_api/20261028T214931Z_dc7a6b79/ |
| acceptance/phase3_independent/run.py --record render-predeploy-20261028 --snapshot-current | Original 90 passed, no failures/errors/skips/guard violations, 9.093 seconds |
| acceptance/airtable_independent/run.py --record render-predeploy-20261028 | Original 15 passed, no failures/errors/skips/guard violations, sources unchanged, 1.5 seconds |
| scripts/verify_airtable_handoff.py | Prior assertions, protected authority/shared/validation/independent files, first-run sources and retained original evidence unchanged |
| python -m pip check | No broken requirements found in the local Windows environment; not a Linux image installation check |
| git diff --exit-code 45d9924 -- app AIRTABLE_SCHEMA.md acceptance and all pre-existing tests | Passed; all business code, shared structures, authority and pre-existing/independent assertions unchanged |
| git diff --check / changed English prose/source Han scan | Passed; no Han matches in changed prose/code; the existing .dockerignore directory pattern is intentionally preserved |

Full regression includes the existing real headless-browser page checks with
simulated responses/integrations, not live service processing. All offline
regression/independent runners reported zero guard violations. The full/local
selected runs retained unchanged authorized input/authority hashes. Original PDFs,
expected answers, Airtable v1.1, historical evidence and independent assertions
are unchanged. Actual new real model/Airtable request counts are both zero.

## Unrun checks, blocker and stop condition

Docker blocker: no running Linux Engine is reachable. Docker image build,
runtime dependency installation/image inspection, actual container startup,
page/assets/health/authentication inside Docker, mounted UID permissions,
container upload/query, replacement persistence/deduplication and shutdown are
NOT RUN. No container acceptance is claimed. Both default and elevated explicit
prechecks and the actual failed build establish this blocker; no privileged
daemon/service installation or host configuration change was attempted.

The clean-source simulation validates the selected test set on Windows without
local data; it is not GitHub-hosted Linux CI. Remote Actions execution/result is
not established here. Render disk permissions, HTTPS/ingress/timeouts, deployment
and live processing are unverified. No Render service was created. No real
model/Airtable call, private/held-out evaluation, export or notification ran.

Known limitation, documented without a fix: identical PDFs in separate databases
receive separate ReceiptIDs and can duplicate Airtable rows. Same-database
deduplication requires reusing the same persistent /app/data and fixed Airtable
destination. Single process/worker/instance remains mandatory; do not add workers
or silently change destinations. Unknown sync remains conservative.

Future work requires an explicit assignment: start a Linux Docker Engine and
run the retained harness to establish actual container acceptance, review Actions
results, then separately authorize any Render service creation/deployment and
platform/live checks. This assignment stops after staged audit, commit/push and
remote verification of this preparation branch; no cloud service is created.
The entire pre-assignment TASKS.md is preserved as an exact byte prefix against
data/docker/20261028T214850Z_dd7eb75c/tasks-before.md.

Final pre-commit review: all 10 explicitly selected preparation files were
staged. scripts/audit_staged.py passed with zero credential/private-file findings;
git diff --cached --check passed. Both the working-byte prefix and Git-normalized
staged historical TASKS.md prefix matched their pre-assignment versions. Ignore
checks confirmed .env, original A.pdf and new Docker evidence stay outside Git.
The final pre-push remote check still had no preparation branch and all four
original refs matched the IDs above. No daemon/container/server was left running
by this work. Commit/push only this branch, verify the new ref and original refs,
report the exact commit/results/checklist and stop without creating a service.

# Follow-up Docker acceptance - 2026-10-28

The user explicitly resumed pre-deployment acceptance from chore/render-predeploy
at df878d852a88f548bf42aa5f20fe8a49119704b3. Read AGENTS.md,
docs/DEPLOYMENT.md and the required specification/schema/handoff/shared models.
Initial branch/HEAD matched the requested version and the working tree was
clean. No new business rule, feature, independent assertion or fixture change is
authorized or made. Render service creation/deployment remains excluded.

## Actual Docker acceptance

The existing scripts/docker_acceptance.py was executed once with the existing
project .venv and repository-scoped elevated access, avoiding a misleading
sandbox Docker context. Its single initial Engine check succeeded. Docker
Desktop Linux Engine is now available; no unavailable-engine retry, daemon
installation, service configuration change or manual intervention was needed.

Evidence is new and ignored: data/docker/20261028T220021Z_dcff829b/.
The initial pre-deployment failure evidence remains unchanged. The actual build
installed Linux runtime dependencies, passed pip check and all static-asset
existence checks, and built receipt-offline-724151251d0f:verification.
Image ID: sha256:f6483b4a934818fd87de7792bb6f886949c933416742b6c945d8ad9660205d9e.

| Actual command/check | Result |
| --- | --- |
| .venv/Scripts/python -B scripts/docker_acceptance.py | Exit 0; status=passed; completed image_build, production, simulated, restart |
| Default production CMD, PORT=8765, isolated /app/data mount | Passed: homepage, upload.js/style.css, /health without request key or model/Airtable settings, missing/wrong receipt key 401, authorized missing query 404, export 501, UID 10001 directory write/read/delete |
| Explicit mounted verification server, same isolated store | Passed: supplied unchanged A.pdf admitted; synthetic extraction; simulated Airtable GET then POST; saved/validated/synced result with simulated record ID, query and identical duplicate responses |
| Recreated container using default production CMD, same store | Passed: complete stored response queried before duplicate upload, unchanged receipt/record IDs and data, duplicates returned identical result without a new extraction or simulated request |
| Original and SQLite checks inside containers | Passed: exactly one row; original bytes/SHA-256 match the mounted input; persisted response/metadata/raw extraction and sync IDs/status match |
| All three container stops and removal | Passed: each stopped with exit 0 and was removed; image and isolated evidence/data retained |
| Separate offline image manifest/configuration audit | Passed: Linux amd64, UID/GID 10001:10001, default python -m app.main, /app WORKDIR, DATA_DIR=/app/data and PORT defaults, no business secret environment variable names |
| Exact image /app file/hash comparison against requested source manifest | Passed: exactly 30 authorized app/requirements files, no extra .env, PDF, DB, local evidence, tests or verification scripts |
| Owned-container presence check | Passed: no receipt-offline-724151251d0f container remains |

The production/simulated/restart containers all had --network none and no
published ports. Only the explicit synthetic APP_API_KEY and PORT/PYTHONPATH
were passed; no host .env or real business credential was loaded/forwarded. The
helper and original A.pdf were read-only runtime mounts, absent from the image.
The exact event journal remained one synthetic_extraction, one
simulated_airtable_GET and one simulated_airtable_POST across duplicates and
replacement. Real model requests: 0. Real Airtable requests: 0. No expected
answer/private/held-out data was used. Startup readiness briefly logged expected
loopback connection refusals before the app was listening; subsequent checks
passed. Docker's --time deprecation warning did not affect successful shutdown.

## GitHub Actions verification

For the exact requested head SHA, executed the read-only command:
gh run list --repo Zichen2505/receipt_automation --commit
df878d852a88f548bf42aa5f20fe8a49119704b3 --limit 10 --json
databaseId,headSha,headBranch,status,conclusion,url,name,event,createdAt,updatedAt.
It exited 1 because GitHub CLI is not authenticated. No token was requested,
read for authentication, printed or added to the environment.

Then attempted one credential-free GitHub REST read of
https://api.github.com/repos/Zichen2505/receipt_automation/actions/runs?head_sha=df878d852a88f548bf42aa5f20fe8a49119704b3&per_page=10.
It could not connect. Sanitized metadata is retained as
actions-original-commit.json beside Docker result.json/console.txt and
image-verification.json. Actual Actions status/conclusion/run URL is UNCONFIRMED;
these access failures do not prove that a workflow passed, failed or is absent.
No manual dispatch/rerun was requested. The ordinary documentation push can
trigger the existing push workflow, whose remote result is also unconfirmed.

An authenticated operator can open the repository Actions page, select the
Offline regression and Docker build workflow and match its full head SHA to the
requested commit; inspect every job/step and preserve its actual run URL/result.
Local container success is not a substitute for that remote result. No login or
credential/configuration change was attempted just to obtain an Actions result.

## Handoff and limits

Only README.md, docs/DEPLOYMENT.md and this appended TASKS.md record are changed.
No deployment/runtime defect was found, so no code/configuration/assertion fix or
unaffected regression rerun was needed. The image/application/harness/CI sources
remain identical to the requested accepted commit; documentation is excluded
from the Docker context. The original full 168-case regression and independent
90/15-case results remain historical; they were not rerun or relabeled here.
Exact pre-follow-up TASKS.md bytes are retained as
data/docker/20261028T220021Z_dcff829b/tasks-before-followup.md for prefix checks.

Current local Docker blocker is resolved. Remote Actions remains unconfirmed;
Render disks/ingress/platform shutdown, cloud deployment, live model/Airtable
acceptance, backups/power loss and cross-database deduplication remain unverified
or unchanged. This local isolated bind mount is not a Render persistent disk.
Cross-database deduplication remains the documented known limitation, without a
fix in this assignment. No Render service, real integration request, export or
notification was created. Complete documentation/secret/whitespace/protected-file
review, commit and push only this branch without force or merging main, verify
remote refs, report the exact final commit and actual results, then stop.

Final documentation review: git diff --check and git diff --cached --check
passed; scripts/audit_staged.py reviewed exactly three staged documentation
files with zero credential/private-file findings. The original working-byte and
staged normalized TASKS.md prefixes are preserved. Ignore checks passed for .env,
the supplied PDF and the new Docker evidence. A protected-path diff against
df878d852a88f548bf42aa5f20fe8a49119704b3 was empty for app/, all requirements,
Dockerfile/.dockerignore, scripts/tests/acceptance, authority and Actions workflow.
The actual pre-push git ls-remote succeeded: chore/render-predeploy remained at
the requested base, and main/all earlier development refs retained their prior
commits. Commit/push the reviewed documentation update without force; the final
delivery reports its resolved commit and actual remote verification. No new
container execution is needed for documentation excluded from the image.

# Durable extraction jobs handoff - 2026-11-04

The user's pasted assignment explicitly authorizes this new backend milestone
and supersedes earlier restrictions on durable jobs only. Read AGENTS.md,
PROJECT_SPEC.md, AIRTABLE_SCHEMA.md, all historical TASKS.md sections and
app/schemas/receipt.py before implementation. The working tree was clean on
chore/render-predeploy at the exact reviewed baseline
4e5cad9ccbec0cc5261233f15a753e031e7c4d7b. Fetched origin before editing: the
baseline had not advanced and feature/extraction-jobs did not exist. Created
feature/extraction-jobs from that baseline, without using the older main.

Initial sandbox git fetch could not write FETCH_HEAD; the first elevated fetch
reported ownership mismatch. A command-scoped safe.directory override allowed
fetch/branch operations without changing global Git configuration. Pre-delivery
ls-remote confirmed main, baseline and all earlier development refs unchanged;
the new feature branch was still absent. Commit and push only this branch,
without force, merge, PR or deployment. Its implementation/delivery SHA is the
enclosing commit; the final delivery response reports the resolved local and
verified remote SHA rather than embedding a self-referential commit hash here.

## Implemented behavior and contract

- Added opt-in POST /api/v1/extractions and GET /api/v1/extractions/{request_id},
  dedicated server-only EXTRACTION_API_KEY, stable EXTRACTION_INTEGRATION_SCOPE
  and canonical client UUID Idempotency-Key. APP_API_KEY remains unchanged for
  legacy receipt APIs and is still required at startup. Enabled invalid feature
  credentials/model/scope/limits/storage fail closed; the disabled default uses
  existing startup configuration. Key rotation preserves scope/idempotency.
- Reused strict PDF admission and deterministic validation, extending total-body
  middleware coverage to the new POST. Exactly one file field is accepted; no
  caller identity is trusted. PDF filenames never choose paths/configuration.
- Added only canonical shared models in app/schemas/receipt.py, preserving every
  original model definition. The envelope contains request_id, status, UTC
  timestamps, full ReceiptData/ValidationResult, sanitized error and selected
  extraction-version metadata. Decimal strings, nulls and ordered items persist.
- New DATA_DIR/extraction_jobs/jobs.sqlite3 and originals are independent of
  legacy storage/recovery/locks. SQLite primary key (scope, request_id),
  BEGIN IMMEDIATE and guarded transitions coordinate concurrent submissions.
  A committed private reservation precedes atomic/fsynced original storage;
  verified association precedes the queued readiness commit and POST 202.
  Unpublished reservations can yield GET 404 while acceptance still completes.
- Identical terminal retries return 200 without a model call, including failed
  and unknown; changed bytes return 409. Different request IDs never share a
  result based on PDF hash. Actual digest, selected model/prompt/schema/limits
  and executable version/fingerprint are stored at first reservation. Later
  defaults do not reinterpret old jobs; incompatible queued pipelines become
  unknown. The fingerprint covers extractor/schema/validation/job service and
  pinned runtime requirements with normalized source line endings.
- Lifespan-managed bounded workers persist processing before dispatch, recheck
  input integrity, hold no transaction/legacy workflow lock during extraction,
  and allow status reads during blocked model execution. Ordinary worker faults
  are contained so future work is still considered. Active capacity includes
  accepting/queued/processing, with separately bounded extraction concurrency.
- Completed requires extraction and receipt validation to pass; needs_review
  preserves structured issues/data; failed is a committed technical failure;
  unknown represents uncertain/interrupted work with no usable result assumed.
  Raw output, normalization/provider metadata and failure/recovery evidence stay
  internal, including invalid structured output when the adapter received it.
  No diagnostic exception, secret or internal path is exposed in job responses.
- Startup resumes valid queued input and marks interrupted accepting/processing
  unknown, without replaying a model call. Missing/corrupt inputs cannot execute.
  Shutdown stops claims, completes admission durability, waits the extraction
  grace, then cancels remaining workers and preserves uncertainty. No automatic
  input deletion or public reset/retry endpoint is implemented.
- Existing receipt routes, page, validation, original storage, Airtable adapter,
  prompt and response contracts remain compatible. Jobs have no Airtable,
  notification or payment path. Original AIRTABLE_SCHEMA.md v1.1 and independent
  assertions/evidence/fixtures remain unchanged. Exports remain explicit 501.
- Added the job tests to existing minimal offline/Docker-build CI, stripped new
  credentials/configuration from guarded runners and included the new credential
  name in the staged-secret audit. No dependency version or Docker build/runtime
  source was changed. No new UI, external queue, service or multi-agent work.

The application developer's primary contract is
docs/EXTRACTION_API_HANDOFF.md. It includes exact multipart/envelope fields,
state transitions/errors, authentication/configuration, ownership enforcement,
known-ID polling and lost-response recovery, the prohibition on automatic new
jobs after timeout/404, form mapping, immutable full snapshots before corrections,
stale-response/confirmation responsibilities, retention and controlled maintenance,
disk/process/backup/migration/restart requirements, and a future NEW isolated
Render service checklist with no Airtable credentials. PROJECT_SPEC.md, README,
the legacy handoffs, .env.example and AGENTS.md are consistent with this scope.
The OpenAI Docs skill was used to review the official Responses create reference;
no real SDK request, model/provider migration or prompt change was made.

## Actual offline commands and results

All Python commands used the existing .venv. Evidence is fresh, local and ignored.
Timestamps in evidence are UTC (2026-11-05); this handoff date uses America/New_York
(2026-11-04). No earlier execution record or protected input was overwritten.

| Executed command/check | Actual result |
| --- | --- |
| git status/branch/log/remote; scoped git fetch origin and switch -c feature/extraction-jobs | Clean exact reviewed baseline; origin fetched and new branch created; no newer baseline commit |
| scripts/offline_regression.py tests/test_http_receipts.py tests/test_extractor.py tests/test_phase1.py | 66 passed; no errors/skips/guard violations; protected inputs unchanged; data/http_api/20261105T015620Z_9df4e366/ |
| First scripts/offline_regression.py tests/test_extraction_jobs.py | 43 passed, 2 failed; test multipart fixture was malformed before reaching the body limit and a new test guessed a legacy issue message; original failure evidence data/http_api/20261105T015904Z_e665523d/ retained |
| Corrected new-suite run, same command | 45 passed; valid streaming multipart fixture exercises overflow and the exact existing message is asserted; no product/assertion weakening; data/http_api/20261105T015932Z_00332297/ |
| Expanded new-suite run, same command | 49 passed; data/http_api/20261105T020032Z_0f426207/ |
| First full scripts/offline_regression.py | 217 passed, 1 existing AnyIO warning, 23.66 seconds; zero guard violations, unchanged protected inputs; data/http_api/20261105T020406Z_a512684b/ |
| Final new-suite run after preserving invalid-output evidence and extending pipeline fingerprint | 50 passed, zero errors/skips/guard violations; data/http_api/20261105T020702Z_b8f345b9/ |
| Final scripts/offline_regression.py | 218 passed, zero failures/errors/skips, 1 existing AnyIO warning, 22.80 seconds; protected inputs unchanged, zero guard violations; data/http_api/20261105T020726Z_12c7c9eb/ |
| acceptance/phase3_independent/run.py --record extraction-jobs-final-20261104 --snapshot-current | Original 90 assertions passed; zero failures/errors/skips/guard violations, 8.812 seconds; new evidence only; earlier extraction-jobs-20261104 run also passed |
| acceptance/airtable_independent/run.py --record extraction-jobs-final-20261104 | Original 15 passed; zero failures/errors/skips/guard violations, sources unchanged, 1.453 seconds; earlier extraction-jobs-20261104 run also passed |
| Inline Python clean-source CI simulation, copying only tracked files plus intentional new source/tests into a fresh checkout, then running the eight workflow suites through scripts/offline_regression.py | 141 passed, 1 explicit absent-development-A.pdf skip, zero failures/errors/guard violations; protected authority unchanged; data/extraction_jobs/20261105T020830Z_67f93b0a/checkout/data/http_api/20261105T020830Z_459f4e29/ |
| python -m pip check | No broken requirements found in the local Windows environment |
| docker version, normal and elevated contexts | Client 29.9.2; default docker_engine and desktop-linux dockerDesktopLinuxEngine pipes unavailable; no reachable Engine |
| Elevated scripts/docker_acceptance.py | not_run_docker_unavailable, zero completed stages, zero real model/Airtable requests; data/docker/20261105T020451Z_92e8a354/ |
| git diff --exit-code 4e5cad9 on Airtable authority, all independent files, existing tests and unchanged legacy service/validation/storage/Airtable/prompt/page paths | Passed; no unrelated/protected modification |
| git diff --check; new English source/handoff Han scan | Whitespace passed after correcting one new documentation trailing blank line; Han scan had no matches (normal exit 1) |
| Scoped git ls-remote --heads origin before delivery | All five original refs matched their reviewed IDs; feature/extraction-jobs absent |

The new tests use actual SQLite transactions and concurrent HTTP/DB claims,
fictional in-memory PDFs, isolated stores, blocked real external connections and
injected extractors. Coverage includes admission/auth/config failures, limits,
one invocation under duplicates, 409, capacity/concurrency, nonblocking GET,
lost-response/disconnected POST recovery, initial GET 404 during unpublished
acceptance, missing/partial/renamed acceptance windows, valid queued recovery in a
new interpreter, interrupted processing unknown without replay, completed/review/
failed/unknown serialization, complete decimal/null/item persistence, credential
rotation/scope binding, unavailable pipeline, result/query storage failures,
contained worker failure, and internal invalid-model-output evidence. The full
suite also exercises the existing real headless browser with simulated responses.
Independent original assertions were not edited or relabeled as newly authored.

## Unrun checks, limitations and stop condition

Docker image build/startup/Linux dependencies/UID permissions, actual container
job persistence/replacement/signals and shutdown are NOT RUN for this branch:
Docker Engine is unavailable. The harness did not attempt or pass a build.
Historical baseline Docker acceptance is preserved and is not claimed for new
code. Clean-source simulation ran on Windows; hosted Linux Actions for the final
commit is UNCONFIRMED. No service creation/deployment or Render setting changed.

No real model/Airtable request, notification, payment, company record change,
private/held-out read, visual document evaluation or new UI was performed. Runtime
failures are injected and crash windows are prepared with actual committed state;
destructive power-loss behavior and platform durability are not established.
Single instance/process/worker/event loop and one persistent DATA_DIR remain
required. A disk preserves records, not an external request's cancellation.
Storage or model aliases can fail/change; uncertainty is deliberately sticky.
No cross-database idempotency, distributed lock, automatic expiry, live backup
service, public maintenance/reset or employee/approval/payment authority is added.
Full disk retention/growth and malformed-PDF CPU/ingress limits are operator
responsibilities, as documented. Existing legacy cross-database Airtable duplicate
limitations remain unchanged. Local success proves neither a Render disk nor live
application integration or completion of the reimbursement system.

Pre-assignment TASKS.md bytes are preserved in
data/extraction_jobs/20261105T020830Z_67f93b0a/tasks-before.md. Complete staged
secret/private-file/whitespace/prefix review, commit and push only
feature/extraction-jobs, verify its remote SHA and unchanged original refs, then
stop. Any Docker recheck, live integration, maintenance, application changes or
Render creation/deployment requires a future explicit assignment.

Final staged review: exactly 23 intentional files, scripts/audit_staged.py passed
with zero private-file/credential findings, cached whitespace check passed, and
ignore checks confirmed .env, original A.pdf and new regression/handoff evidence
remain outside Git. Historical TASKS.md working bytes are an exact prefix and
the original shared model definitions remain an unchanged normalized prefix.
All original independent assertions and original authority/fixtures/evidence are
preserved. No acceptance server/container/worker was left running by this work.
