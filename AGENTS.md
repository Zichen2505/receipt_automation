# Agent handoff rules

Before starting, every Agent must read PROJECT_SPEC.md, AIRTABLE_SCHEMA.md, TASKS.md, and app/schemas/receipt.py, then inspect existing files and workspace changes. Preserve existing work and unrelated content.

Communicate with the user in Chinese.
Write all project documentation, comments, docstrings, prompts, UI text, and handoff records in English.
Preserve original input documents and evaluation data unchanged.

- Current authorization: connect authenticated PDF upload and persisted query HTTP APIs to the existing local service, including upload limits, explicit errors/timeouts, and configuration documentation. Verify offline with injected extractors; preserve independent acceptance assertions and original evidence. No real model requests, Airtable, UI, exports, notifications, or deployment. Exports remain explicit 501. Commit and push the accepted baseline and a separate development branch to the user-specified repository without overwriting remote work or force-pushing. Complete regression and handoff, then stop; future scope requires an explicit user assignment.
- app/schemas/receipt.py is the sole implementation source for shared data structures; do not duplicate models.
- AIRTABLE_SCHEMA.md at the receipt-agent project root is the sole authority for Airtable mappings. Preserve the supplied v1.1 document unchanged; do not maintain competing copies.
- Interface changes must update PROJECT_SPEC.md, callers, and related checks together.
- API handles HTTP/authentication/parameters; Service orchestrates business steps; Integration handles external services; Storage handles persistence. Routes must not contain model, SQL, or Airtable requests.
- Run slow synchronous operations from async flows with asyncio.to_thread. Do not introduce microservices, queues, or multi-Agent orchestration.
- Only use user-provided development PDFs in tests/fixtures/development/pdfs/ and expected answers in tests/fixtures/development/expected/. Do not request, read, or copy evaluator_private or held-out answers. Never translate original receipts or edit expected answers.
- Do not fabricate successful extraction, storage, synchronization, or notification. Unimplemented interfaces must fail explicitly.
- Keep secrets out of source code, logs, frontend assets, Git, and images. Run only checks relevant to the current phase.
- Update TASKS.md at handoff with executed commands, actual results, checks not run, blockers, and next-phase tasks.
