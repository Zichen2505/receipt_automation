# Independent phase 3 offline acceptance

Design date: 2026-10-28 (America/New_York).
The oracle is PROJECT_SPEC.md (Data and normalization, Fixed and extended
interfaces, Deterministic validation, Persistence and concurrency, Atomic
originals and failure recovery, States and HTTP boundary), together with
app/schemas/receipt.py and app/contracts.py. This design is written before
reading implementation details or running the new suite.

AGENTS.md requires reading TASKS.md and AIRTABLE_SCHEMA.md. Those required
handoff reads are not test oracles. Existing tests, development answers,
historical extraction artifacts, and private evaluation data are not sources
for these tests. All receipt objects and byte payloads are newly invented.
Byte payloads exercise storage identity and preservation, not PDF parsing or
model extraction accuracy. No development PDF is needed or read.

## Contract cases

1. Missing and explicit null merchant/date/currency/total produce their specified
   missing codes; blank merchant/currency also count. Zero total is valid.
   Optional nulls stay null. Decimal JSON values remain strings.
2. Explicit money (including item prices/amounts) must be a multiple of 0.01;
   trailing zeros are accepted; fractional quantity is unrestricted. Exact line,
   subtotal and final-total conflicts are detected without repairing inputs.
   Very large values and a deliberately small ambient Decimal context must not
   change the mathematical result. Unknown components skip only affected checks.
3. Negative discount is invalid when validating directly. Boundary normalization
   changes only discount to its magnitude, preserves null, records each original
   and normalized value with a nonempty reason, is idempotent, and leaves the
   caller's complete nested object unchanged. No exact reason text is assumed.
4. An injected async extractor drives service saved/needs_review outcomes, with
   stored snapshots, original bytes/hash, pre-normalization JSON and audit events.
   Querying unknown IDs returns None. Deferred effects are skipped/not_sent.
5. Repeated identical bytes, including changed filenames and failed outcomes,
   reuse the ID and terminal response without extracting again. Distinct bytes
   with the same filename have distinct IDs and originals. Concurrent requests
   across service instances on one loop have one owner. SQLite concurrent claims
   have one owner independently of service locks. Terminal saves cannot overwrite
   prior terminal results.
6. Restart is tested sequentially in fresh interpreters, never by running two
   loops/processes against a DATA_DIR concurrently. Saved snapshots survive.
   Interrupted claims become failed with interrupted_processing and a nonempty
   recovery reason, retain ID/hash and never retry extraction. Matching originals
   are reattached; missing/corrupt originals have null references. Orphan/temp
   files are retained. Prepared interruption states use public storage interfaces.
7. Extractor failure, validation execution failure, original-save failure,
   terminal-commit failure, and inability to commit even failure must never claim
   saved. Errors are sanitized. Recovery must occur on the next operation after
   an uncommittable failure. Failure codes are nonempty; only the specified
   interrupted_processing code is asserted exactly.
8. Atomic original replacement failure preserves an existing original and removes
   only its own temporary file. Unsafe IDs and conflicting byte overwrites fail.
   Normal caller cancellation completes the owned workflow before propagating.

## Isolation and evidence

Use standard-library unittest with explicit discovery in this new directory;
do not load pytest configuration, existing tests or plugins. All service calls
inject a substitute extractor and use TemporaryDirectory DATA_DIR paths. The
runner removes inherited application credentials/configuration, blocks network
connections, .env and historical/fixture reads, and real SDK client construction.
Implementation inspection is allowed only for invocation and fault-injection
seams; it must not supply expected outcomes.

Capture Git commands and SHA-256 source/contract baselines before testing; absent
Git metadata is a baseline blocker, not a fabricated commit. Record source hashes
again after running. First-run stdout/stderr, individual results, exit code and
test source hashes are exclusive-create artifacts. Do not change business code,
contracts, or assertions to eliminate failures. If the harness itself is wrong,
retain its initial result and classify the error separately from product defects.

Undefined exact reason/message strings, unspecified exception types, malformed
PDF policy, multi-process execution, HTTP/Airtable and production integrations
are not assigned new semantics. Any material interface mismatch or ambiguous
rule is recorded as a blocker for review.
