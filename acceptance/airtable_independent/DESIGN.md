# Offline Airtable contract acceptance

This is a separate contract-oracle suite for the user-authorized synchronization
phase. It is written by the same agent as the implementation, not an external
human review. Expected field names, values and state transitions are literal
requirements from the assignment and unchanged AIRTABLE_SCHEMA.md, not output
from the production mapper or historical receipt answers. The suite imports no
existing tests, fixtures, scripts, expected data or historical outputs. All
receipts, PDF bytes and HTTP responses are explicitly synthetic.

The first execution freezes app source, authority/spec/dependencies and these
test sources. The runner records unique evidence and never replaces prior runs.
Original phase 3 acceptance remains separate and its assertions are unchanged.
No expected answer or assertion is adjusted to obtain a passing run; any
implementation or harness correction requires a distinct recorded run.

Contract cases:

- Exact six columns, numeric Amount, complete literal RawJSON including item
  detail and nulls; local commit precedes network work.
- saved plus validation.passed eligibility at both service and adapter boundary;
  failed/review snapshots never read or write Airtable.
- Missing configuration returns not_configured without HTTP.
- Successful POST persists record_id; repeated/concurrent uploads and retries
  reuse it without another extraction or row.
- Existing matching ReceiptID reconciles without POST; conflicting or duplicate
  records cannot be treated as success.
- Definite rejection retains local saved and allows a model-free retry.
- Lost POST response persists unknown; a later query can confirm the record;
  absent/query-failed results cannot cause another POST.
- Recovery of pending, and uncertainty across sequential restart, never loses
  the original local result or invokes a model.
- Authenticated HTTP upload/retry uses the production service with only extractor
  and HTTP transport substituted; GET sees persisted sync; exports remain 501.
- HTTP sync wait timeout retains work through graceful shutdown.

Network, SDK construction, root dotenv and private data reads are blocked.
This verifies adapter/service/HTTP behavior under simulated responses only.
Remote table configuration, PAT permissions, model accuracy, real timing/rate
limits, independent writers, Docker, deployment and power-loss are not verified.
