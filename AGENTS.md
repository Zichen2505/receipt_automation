# Agent handoff rules

Before starting, every Agent must read PROJECT_SPEC.md, AIRTABLE_SCHEMA.md, TASKS.md, and app/schemas/receipt.py, then inspect existing files and workspace changes. Preserve existing work and unrelated content.

Communicate with the user in Chinese.
Write all project documentation, comments, docstrings, prompts, UI text, and handoff records in English.
Preserve original input documents and evaluation data unchanged.

- Current authorization: implement opt-in durable extraction jobs and their application integration contract on feature/extraction-jobs from reviewed chore/render-predeploy 4e5cad9ccbec0cc5261233f15a753e031e7c4d7b. This explicit assignment supersedes earlier restrictions on durable jobs only. Preserve legacy API/upload-page/Airtable behavior, AIRTABLE_SCHEMA.md v1.1, remote schema, independent assertions, original fixtures and evidence. Verify offline with generated fictional PDFs, injected extractors and simulated HTTP; no real model/Airtable request, notification, payment, company-record change, UI feature, Render change or deployment. Exports remain 501. Use a separate small persistent store and lifespan execution loop, one instance/process; no external queue or worker service. Run container checks only with a reachable Docker Engine and report unavailable checks as not run. Complete implementation, regression, English handoff and commit/push only feature/extraction-jobs without force, PR, merge or updates to main/baseline; then stop.
- app/schemas/receipt.py is the sole implementation source for shared data structures; do not duplicate models.
- AIRTABLE_SCHEMA.md at the receipt-agent project root is the sole authority for Airtable mappings. Preserve the supplied v1.1 document unchanged; do not maintain competing copies.
- Interface changes must update PROJECT_SPEC.md, callers, and related checks together.
- API handles HTTP/authentication/parameters; Service orchestrates business steps; Integration handles external services; Storage handles persistence. Routes must not contain model, SQL, or Airtable requests.
- Run slow synchronous operations from async flows with asyncio.to_thread. Do not introduce microservices, external queues, or multi-Agent orchestration. The authorized extraction-job loop stays in the existing process.
- Use only user-provided development PDFs in tests/fixtures/development/pdfs/ and expected answers in tests/fixtures/development/expected/ for real-document checks. Generated fictional PDFs are authorized for extraction-job offline tests. Do not request, read, or copy evaluator_private or held-out answers. Never translate original receipts or edit expected answers.
- Do not fabricate successful extraction, storage, synchronization, or notification. Unimplemented interfaces must fail explicitly.
- Keep secrets out of source code, logs, frontend assets, Git, and images. Run only checks relevant to the current phase.
- Update TASKS.md at handoff with executed commands, actual results, checks not run, blockers, and next-phase tasks.
