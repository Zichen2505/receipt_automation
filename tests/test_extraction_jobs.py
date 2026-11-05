"""Durable extraction contract with real SQLite, fictional PDFs and injected execution."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from pypdf import PdfWriter
import pytest

from app.config import Settings
from app.contracts import ExtractionConflictError, ReceiptStorageError
from app.integrations import extractor
from app.integrations.airtable import AirtableClient
from app.main import app
from app.schemas.receipt import ExtractionJobResponse, ReceiptData
from app.services.extraction_jobs import ExtractionJobService
from app.storage import extraction_jobs as store, files, repository

KEY = "synthetic-extraction-credential"
SCOPE = "fictional-expense-backend"
BASE = "/api/v1/extractions"
PRIVATE = "synthetic-diagnostic-path-and-secret-98342"


def pdf(pages=1, *, label="fictional", encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": label})
    if encrypted:
        writer.encrypt("fictional-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def data(**changes):
    values = dict(merchant="Fictional Stationery", date="2026-10-01", receipt_number="F-123",
        currency="CAD", total="12.30", subtotal="12.30", tax=None, tip=None, discount="-0.00",
        items=[dict(description="Fictional pen", quantity="1.000", unit_price="2.30", amount="2.30"),
               dict(description="Fictional notebook", quantity=None, unit_price=None, amount="10.00")])
    values.update(changes)
    return ReceiptData.model_validate(values)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    variables = {"APP_API_KEY": "synthetic-legacy-credential", "MODEL_API_KEY": "synthetic-model-credential",
        "MODEL_NAME": "fictional-model-v1", "DATA_DIR": str(tmp_path), "EXTRACTION_JOBS_ENABLED": "true",
        "EXTRACTION_API_KEY": KEY, "EXTRACTION_INTEGRATION_SCOPE": SCOPE,
        "EXTRACTION_SHUTDOWN_GRACE_SECONDS": "0.05"}
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    for name in ("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID", "MAX_UPLOAD_BYTES", "MAX_PDF_PAGES",
                 "EXTRACTION_MAX_ACTIVE_JOBS", "EXTRACTION_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)

    async def forbidden(*args, **kwargs):
        pytest.fail("Extraction jobs must never enter Airtable")

    monkeypatch.setattr(AirtableClient, "sync_receipt", forbidden)
    return Settings.from_env()


@asynccontextmanager
async def api(injected=None):
    async with app.router.lifespan_context(app):
        calls = []

        async def substitute(content, filename):
            calls.append((content, filename))
            return await injected(content, filename) if injected else data()

        app.state.extraction_service.extractor = substitute
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            yield client, app.state.extraction_service, calls


def headers(identifier=None, key=KEY):
    result = {"X-API-Key": key}
    if identifier is not None:
        result["Idempotency-Key"] = identifier
    return result


async def post(client, identifier, content=None, **kwargs):
    return await client.post(BASE, headers=headers(identifier),
        files={"file": ("../../untrusted-name.pdf", pdf() if content is None else content, "application/pdf")}, **kwargs)


async def query(client, identifier):
    return await client.get(f"{BASE}/{identifier}", headers=headers())


async def terminal(client, identifier):
    async def wait():
        while True:
            response = await query(client, identifier)
            assert response.status_code == 200
            if response.json()["status"] not in {"queued", "processing"}:
                return response.json()
            await asyncio.sleep(0.01)
    return await asyncio.wait_for(wait(), timeout=4)


def test_concurrent_http_idempotency_nonblocking_query_and_lost_response(configured):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(*args):
            entered.set()
            await release.wait()
            return data()

        async with api(blocked) as (client, service, calls):
            identifier, content = str(uuid4()), pdf()
            accepted = await asyncio.gather(*(post(client, identifier, content) for _ in range(16)))
            assert all(response.status_code == 202 for response in accepted)
            await asyncio.wait_for(entered.wait(), 1)
            # The known client ID recovers even if every POST response was lost.
            active = await asyncio.wait_for(query(client, identifier), 0.5)
            assert active.json()["status"] == "processing" and active.json()["data"] is None
            assert active.json()["request_id"] == identifier
            assert (await post(client, identifier, pdf(label="different"))).status_code == 409
            assert len(calls) == 1 and calls[0] == (content, "receipt.pdf")
            release.set()
            result = await terminal(client, identifier)
            assert result["status"] == "completed" and result["validation"] == {"passed": True, "issues": []}
            assert result["data"] == data(discount="0.00").model_dump(mode="json")
            assert result["error"] is None
            assert set(result) == {"request_id", "status", "created_at", "updated_at", "data", "validation", "error", "extraction_version"}
            duplicate = await post(client, identifier, content)
            assert duplicate.status_code == 200 and duplicate.json() == result
            assert duplicate.headers["cache-control"] == "no-store"
            record = store.get(identifier, scope=SCOPE, db_path=service.db_path)
            assert json.loads(record.metadata.extraction.raw_output) == data().model_dump(mode="json")
            assert store.read_input(record, data_dir=service.data_dir) == content
            assert record.pdf_sha256 == hashlib.sha256(content).hexdigest()
            assert PRIVATE not in json.dumps(result) and "raw_output" not in json.dumps(result)
            with repository.connection(service.db_path) as db:
                assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
            with repository.connection(configured.data_dir / "receipts.sqlite3") as db:
                assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0
    asyncio.run(run())


@pytest.mark.parametrize("key", [None, "incorrect", "synthetic-legacy-credential", "\u6d4b\u8bd5"])
def test_dedicated_authentication(configured, key):
    async def run():
        async with api() as (client, _, calls):
            request_headers = {} if key is None else {"X-API-Key": key.encode("utf-8")}
            for method, path in (("GET", f"{BASE}/{uuid4()}"), ("POST", BASE)):
                response = await client.request(method, path, headers=request_headers)
                assert response.status_code == 401
            # New key never grants access to legacy receipts.
            assert (await client.get("/api/v1/receipts/missing", headers=headers())).status_code == 401
            assert calls == []
    asyncio.run(run())


@pytest.mark.parametrize("identifier", [None, "not-a-uuid", str(uuid4()).upper(), uuid4().hex, "{00000000-0000-0000-0000-000000000000}"])
def test_invalid_idempotency_key(configured, identifier):
    async def run():
        async with api() as (client, _, calls):
            assert (await post(client, identifier)).status_code == 400
            assert calls == []
    asyncio.run(run())


@pytest.mark.parametrize("content,media,status,code", [
    (b"", "application/pdf", 400, "empty_file"), (b"not PDF", "application/pdf", 415, "unsupported_media_type"),
    (b"%PDF-invalid", "application/pdf", 422, "invalid_pdf"), (pdf(), "text/plain", 415, "unsupported_media_type"),
    (pdf(0), "application/pdf", 422, "invalid_pdf"), (pdf(encrypted=True), "application/pdf", 422, "encrypted_pdf")])
def test_invalid_files(configured, content, media, status, code):
    async def run():
        async with api() as (client, _, calls):
            result = await client.post(BASE, headers=headers(str(uuid4())), files={"file": ("x.pdf", content, media)})
            assert result.status_code == status and result.json()["detail"]["code"] == code
            assert calls == []
    asyncio.run(run())


def test_file_page_body_and_exact_form_limits(configured):
    async def run():
        async with api() as (client, _, calls):
            content = pdf(2)
            app.state.settings = replace(app.state.settings, max_upload_bytes=len(content), max_pdf_pages=2)
            assert (await post(client, str(uuid4()), content)).status_code == 202
            app.state.settings = replace(app.state.settings, max_upload_bytes=len(content)-1)
            assert (await post(client, str(uuid4()), content)).json()["detail"]["code"] == "file_too_large"
            app.state.settings = replace(app.state.settings, max_upload_bytes=10_000, max_pdf_pages=1)
            assert (await post(client, str(uuid4()), content)).json()["detail"]["code"] == "too_many_pages"
            app.state.settings = replace(app.state.settings, max_upload_bytes=32)
            async def chunks():
                yield b'--x\r\nContent-Disposition: form-data; name="padding"\r\n\r\n'
                for _ in range(10):
                    yield b"x" * 8192
                yield b'\r\n--x--\r\n'
            response = await client.post(BASE, headers={**headers(str(uuid4())), "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": "1"}, content=chunks())
            assert response.status_code == 413 and response.json()["detail"]["code"] == "request_too_large"
            app.state.settings = replace(app.state.settings, max_upload_bytes=10_000)
            for fields in ([('file', ('a.pdf', pdf())), ('file', ('b.pdf', pdf()))],
                           [('file', ('a.pdf', pdf())), ('employee_id', (None, 'untrusted'))]):
                assert (await client.post(BASE, headers=headers(str(uuid4())), files=fields)).status_code == 422
            assert len(calls) <= 1
    asyncio.run(run())


@pytest.mark.parametrize("kind,status", [("review", "needs_review"), ("failure", "failed")])
def test_terminal_truthful_results_and_no_retries(configured, kind, status):
    async def substitute(*args):
        if kind == "failure":
            raise RuntimeError(PRIVATE)
        return data(currency=None)

    async def run():
        async with api(substitute) as (client, _, calls):
            identifier, content = str(uuid4()), pdf()
            assert (await post(client, identifier, content)).status_code == 202
            result = await terminal(client, identifier)
            assert result["status"] == status
            if kind == "review":
                assert result["data"]["currency"] is None and not result["validation"]["passed"]
                assert result["validation"]["issues"] == [{"code": "missing_currency", "field": "currency", "message": "Required field currency is missing"}]
            else:
                assert result["data"] is None and result["validation"] is None
                assert result["error"]["code"] == "extraction_failed"
            assert PRIVATE not in json.dumps(result)
            assert (await post(client, identifier, content)).json() == result
            assert len(calls) == 1
    asyncio.run(run())


def test_capacity_and_concurrency_bounds(configured, monkeypatch):
    monkeypatch.setenv("EXTRACTION_MAX_ACTIVE_JOBS", "3")
    monkeypatch.setenv("EXTRACTION_CONCURRENCY", "2")
    async def run():
        release = asyncio.Event()
        count = 0
        async def blocked(*args):
            nonlocal count
            count += 1
            await release.wait()
            return data()
        async with api(blocked) as (client, _, calls):
            ids = [str(uuid4()) for _ in range(4)]
            responses = await asyncio.gather(*(post(client, identifier) for identifier in ids))
            assert sorted(r.status_code for r in responses) == [202, 202, 202, 429]
            await asyncio.sleep(0.1)
            assert count == 2 and len(calls) == 2
            known = ids[next(i for i, r in enumerate(responses) if r.status_code == 202)]
            assert (await post(client, known)).status_code == 202
            release.set()
            for identifier, response in zip(ids, responses):
                if response.status_code == 202:
                    await terminal(client, identifier)
            assert count == 3
    asyncio.run(run())


def prepared(settings):
    service = ExtractionJobService(settings, extractor=AsyncMock(return_value=data()))
    store.initialize(db_path=service.db_path, data_dir=service.data_dir, scope=SCOPE)
    config = extractor.configuration_snapshot(settings.model_name)
    return service, config


def reserve(service, config, content, identifier=None):
    return store.reserve(identifier or str(uuid4()), hashlib.sha256(content).hexdigest(), config,
        scope=SCOPE, capacity=32, db_path=service.db_path)


def queue(service, config, content, identifier=None):
    record, _ = reserve(service, config, content, identifier)
    reference = files.save_original_pdf(content, record.input_id, data_dir=service.data_dir)
    return store.ready(record.response.request_id, reference, scope=SCOPE, db_path=service.db_path, data_dir=service.data_dir)


def test_atomic_sqlite_concurrent_claims_and_terminal_guard(configured):
    service, config = prepared(configured)
    identifier, content = str(uuid4()), pdf()
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: reserve(service, config, content, identifier), range(20)))
    assert sum(owner for _, owner in results) == 1
    assert len({record.input_id for record, _ in results}) == 1
    with pytest.raises(ExtractionConflictError):
        reserve(service, config, pdf(label="changed"), identifier)
    record = results[0][0]
    store.mark_unknown(record, "test_interruption")
    store.finish(record, db_path=service.db_path)
    with pytest.raises(ReceiptStorageError):
        store.finish(record, db_path=service.db_path)


@pytest.mark.parametrize("point", ["missing", "partial", "renamed"])
def test_interrupted_acceptance_never_executes_incomplete_input(configured, point):
    service, config = prepared(configured)
    record, _ = reserve(service, config, pdf())
    if point == "renamed":
        files.save_original_pdf(pdf(), record.input_id, data_dir=service.data_dir)
    elif point == "partial":
        directory = service.data_dir / "originals"
        directory.mkdir(exist_ok=True)
        (directory / f".{record.input_id}.tmp").write_bytes(b"partial")
    async def run():
        await service.start()
        try:
            result = await service.get(record.response.request_id)
            assert result.status == "unknown" and result.error.code == "interrupted_acceptance"
            assert (await service.submit(record.response.request_id, pdf())).status == "unknown"
            service.extractor.assert_not_awaited()
            recovered = store.get(record.response.request_id, scope=SCOPE, db_path=service.db_path)
            assert (recovered.original_pdf_ref is not None) == (point == "renamed")
            if point == "partial":
                assert (directory / f".{record.input_id}.tmp").read_bytes() == b"partial"
        finally:
            await service.close()
    asyncio.run(run())


@pytest.mark.parametrize("point", ["write", "ready"])
def test_acceptance_storage_errors_are_sanitized_and_reserved(configured, monkeypatch, point):
    async def run():
        async with api() as (client, service, calls):
            target, name = (files, "save_original_pdf") if point == "write" else (store, "ready")
            def fail(*args, **kwargs):
                raise OSError(PRIVATE)
            monkeypatch.setattr(target, name, fail)
            identifier = str(uuid4())
            response = await post(client, identifier)
            assert response.status_code == 503 and PRIVATE not in response.text
            result = (await query(client, identifier)).json()
            assert result["status"] == "unknown" and result["data"] is None
            assert (await post(client, identifier)).status_code == 200
            assert calls == []
    asyncio.run(run())


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_queued_integrity_rechecked_before_execution(configured, damage):
    service, config = prepared(configured)
    record = queue(service, config, pdf())
    path = service.data_dir / record.original_pdf_ref
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")
    async def run():
        await service.start()
        try:
            result = await service.get(record.response.request_id)
            assert result.status == "unknown" and result.error.code == "input_unavailable"
            service.extractor.assert_not_awaited()
        finally:
            await service.close()
    asyncio.run(run())


def test_new_process_recovers_queued_and_marks_processing_unknown(configured):
    service, config = prepared(configured)
    uncertain = queue(service, config, pdf(label="uncertain"))
    claimed = store.claim_next(scope=SCOPE, db_path=service.db_path)
    assert claimed.response.request_id == uncertain.response.request_id
    queued = queue(service, config, pdf())
    code = '''
import asyncio, json, sys
from app.config import Settings
from app.schemas.receipt import ReceiptData
from app.services.extraction_jobs import ExtractionJobService
async def run():
    calls = []
    async def extract(content, name):
        calls.append(name)
        return ReceiptData(merchant="Fictional restart", date="2026-10-01", currency="CAD", total="12.30", items=None)
    service = ExtractionJobService(Settings.from_env(), extractor=extract)
    await service.start()
    try:
        for _ in range(200):
            result = await service.get(sys.argv[1])
            if result.status == "completed": break
            await asyncio.sleep(0.01)
        uncertain = await service.get(sys.argv[2])
        print(json.dumps({"result": result.model_dump(mode="json"), "uncertain": uncertain.model_dump(mode="json"), "calls": calls}))
    finally:
        await service.close()
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, queued.response.request_id, uncertain.response.request_id],
                            capture_output=True, text=True, timeout=15, env=dict(os.environ))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "completed"
    assert payload["result"]["data"]["total"] == "12.30" and payload["result"]["data"]["items"] is None
    assert payload["uncertain"]["status"] == "unknown"
    assert payload["uncertain"]["error"]["code"] == "interrupted_processing"
    assert payload["calls"] == ["receipt.pdf"]
    assert payload["result"]["extraction_version"] == config.version.model_dump(mode="json")


def test_shutdown_interruption_is_unknown_without_reexecution(configured):
    async def run():
        entered = asyncio.Event()
        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        async with api(blocked) as (client, service, calls):
            identifier = str(uuid4())
            await post(client, identifier)
            await asyncio.wait_for(entered.wait(), 1)
        record = store.get(identifier, scope=SCOPE, db_path=service.db_path)
        assert record.response.status == "unknown" and record.response.data is None
        replacement = ExtractionJobService(configured, extractor=AsyncMock(return_value=data()))
        await replacement.start()
        try:
            assert (await replacement.submit(identifier, pdf())).status == "unknown"
            replacement.extractor.assert_not_awaited()
        finally:
            await replacement.close()
        assert len(calls) == 1
    asyncio.run(run())


def test_worker_claim_failure_does_not_stop_future_jobs(configured, monkeypatch):
    original = store.claim_next
    attempts = 0
    def flaky(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(PRIVATE)
        return original(**kwargs)
    monkeypatch.setattr(store, "claim_next", flaky)
    async def run():
        async with api() as (client, _, calls):
            identifier = str(uuid4())
            await post(client, identifier)
            assert (await terminal(client, identifier))["status"] == "completed"
            assert len(calls) == 1 and attempts >= 2
    asyncio.run(run())


def test_persisted_configuration_survives_defaults_and_result_reload(configured, monkeypatch):
    service, config = prepared(configured)
    record = queue(service, config, pdf())
    selected = []
    async def configured_extract(content, configuration):
        selected.append(configuration)
        return data(discount="0.00"), extractor.ExtractionMetadata(raw_output=PRIVATE)
    monkeypatch.setattr(extractor, "extract_configured", configured_extract)
    async def run():
        replacement = ExtractionJobService(replace(configured, model_name="fictional-model-v2"))
        await replacement.start()
        try:
            for _ in range(200):
                result = await replacement.get(record.response.request_id)
                if result.status == "completed":
                    break
                await asyncio.sleep(0.01)
            assert result.status == "completed" and result.data == data(discount="0.00")
            assert selected == [config]
            assert result.extraction_version == config.version
        finally:
            await replacement.close()
        loaded = store.get(record.response.request_id, scope=SCOPE, db_path=service.db_path)
        assert loaded.response.model_dump_json() == result.model_dump_json()
        assert loaded.metadata.extraction.raw_output == PRIVATE
    asyncio.run(run())


def test_frozen_configuration_is_passed_to_sdk_without_environment_override(configured, monkeypatch):
    config = extractor.configuration_snapshot("persisted-model")
    monkeypatch.setenv("MODEL_NAME", "later-default")
    response = SimpleNamespace(status="completed", output_text=data().model_dump_json())
    create = AsyncMock(return_value=response)
    manager = AsyncMock()
    manager.__aenter__.return_value = SimpleNamespace(responses=SimpleNamespace(create=create))
    client_factory = lambda **kwargs: manager
    monkeypatch.setattr(extractor, "AsyncOpenAI", client_factory)
    asyncio.run(extractor.extract_configured(pdf(), config))
    payload = create.call_args.kwargs
    assert payload["model"] == "persisted-model" and payload["instructions"] == config.prompt
    assert payload["text"]["format"]["schema"] == config.output_schema
    assert payload["store"] is False and payload["max_output_tokens"] == 4096


def test_invalid_structured_output_evidence_stays_internal(configured, monkeypatch):
    request = AsyncMock(return_value=SimpleNamespace(status="completed", output_text=PRIVATE,
                                                     model="fictional-provider-model", id="fictional-response-id"))
    monkeypatch.setattr(extractor, "request_extraction", request)
    async def run():
        async with api() as (client, service, calls):
            service.extractor = None
            identifier = str(uuid4())
            await post(client, identifier)
            result = await terminal(client, identifier)
            assert result["status"] == "failed" and result["error"]["code"] == "extraction_failed"
            assert PRIVATE not in json.dumps(result) and "fictional-response-id" not in json.dumps(result)
            record = store.get(identifier, scope=SCOPE, db_path=service.db_path)
            assert record.metadata.extraction.raw_output == PRIVATE
            assert record.metadata.extraction.response_id == "fictional-response-id"
            assert record.metadata.extraction.model == "fictional-provider-model"
            assert (await post(client, identifier)).json() == result
            request.assert_awaited_once()
            assert calls == []
    asyncio.run(run())


def test_scope_binding_rotation_and_no_hash_sharing(configured):
    async def run():
        async with api() as (client, service, calls):
            first, second = str(uuid4()), str(uuid4())
            content = pdf()
            await post(client, first, content)
            one = await terminal(client, first)
            await post(client, second, content)
            two = await terminal(client, second)
            assert one["request_id"] != two["request_id"] and len(calls) == 2
            app.state.settings = replace(app.state.settings, extraction_api_key="rotated-synthetic-key")
            assert (await query(client, first)).status_code == 401
            result = await client.get(f"{BASE}/{first}", headers=headers(key="rotated-synthetic-key"))
            assert result.json() == one
        wrong_scope = ExtractionJobService(replace(configured, extraction_integration_scope="different-integration"))
        with pytest.raises(ReceiptStorageError):
            await wrong_scope.start()
    asyncio.run(run())


@pytest.mark.parametrize("name,value", [("EXTRACTION_API_KEY", ""), ("EXTRACTION_API_KEY", "synthetic-legacy-credential"),
    ("EXTRACTION_INTEGRATION_SCOPE", ""), ("MODEL_API_KEY", ""), ("MODEL_NAME", ""),
    ("EXTRACTION_MAX_ACTIVE_JOBS", "0"), ("EXTRACTION_CONCURRENCY", "bad"),
    ("EXTRACTION_CONCURRENCY", "33"), ("EXTRACTION_SHUTDOWN_GRACE_SECONDS", "nan"),
    ("EXTRACTION_JOBS_ENABLED", "yes")])
def test_opt_in_configuration_fails_closed(configured, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_disabled_feature_preserves_legacy_startup(configured, monkeypatch):
    monkeypatch.setenv("EXTRACTION_JOBS_ENABLED", "false")
    for name in ("MODEL_API_KEY", "MODEL_NAME", "EXTRACTION_API_KEY", "EXTRACTION_INTEGRATION_SCOPE"):
        monkeypatch.delenv(name)
    async def run():
        async with app.router.lifespan_context(app):
            assert app.state.extraction_service is None
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
                assert (await client.get("/health")).status_code == 200
                assert (await query(client, str(uuid4()))).status_code == 503
                assert (await client.get("/api/v1/receipts/missing/export", headers={"X-API-Key": "synthetic-legacy-credential"})).status_code == 501
    asyncio.run(run())


def test_query_404_cannot_rule_out_pending_acceptance_and_disconnected_post(configured, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    original = files.save_original_pdf
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(files, "save_original_pdf", blocked)
    async def run():
        async with api() as (client, _, calls):
            identifier = str(uuid4())
            posting = asyncio.create_task(post(client, identifier))
            assert await asyncio.to_thread(entered.wait, 1)
            # This is an unpublished reservation; the same POST can still commit.
            assert (await query(client, identifier)).status_code == 404
            posting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await posting
            release.set()
            for _ in range(200):
                if (await query(client, identifier)).status_code == 200:
                    break
                await asyncio.sleep(0.01)
            assert (await terminal(client, identifier))["status"] == "completed"
            assert len(calls) == 1
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_result_storage_failure_keeps_evidence_and_worker_progress(configured, monkeypatch):
    original = store.finish
    failures = 0
    def fail_completed(record, **kwargs):
        nonlocal failures
        if record.phase == "completed" and failures == 0:
            failures += 1
            raise OSError(PRIVATE)
        return original(record, **kwargs)
    monkeypatch.setattr(store, "finish", fail_completed)
    async def run():
        async with api() as (client, service, calls):
            first, second = str(uuid4()), str(uuid4())
            await post(client, first)
            result = await terminal(client, first)
            assert result["status"] == "unknown" and result["data"] is None
            assert result["error"]["code"] == "result_storage_failure"
            record = store.get(first, scope=SCOPE, db_path=service.db_path)
            assert record.metadata.extraction.raw_output == data().model_dump_json()
            assert (await post(client, first)).json() == result
            await post(client, second)
            assert (await terminal(client, second))["status"] == "completed"
            assert len(calls) == 2
    asyncio.run(run())


def test_incompatible_pipeline_is_unknown_instead_of_reinterpreted(configured):
    service, config = prepared(configured)
    config.version.pipeline_sha256 = "0" * 64
    record = queue(service, config, pdf())
    async def run():
        await service.start()
        try:
            for _ in range(200):
                result = await service.get(record.response.request_id)
                if result.status == "unknown":
                    break
                await asyncio.sleep(0.01)
            assert result.status == "unknown" and result.error.code == "pipeline_version_unavailable"
            assert result.extraction_version.pipeline_sha256 == "0" * 64
            service.extractor.assert_not_awaited()
        finally:
            await service.close()
    asyncio.run(run())


def test_storage_query_errors_and_schema_migration_fail_closed(configured, monkeypatch):
    async def run():
        async with api() as (client, service, _):
            def fail(*args, **kwargs):
                raise OSError(PRIVATE)
            monkeypatch.setattr(store, "get", fail)
            response = await query(client, str(uuid4()))
            assert response.status_code == 503 and PRIVATE not in response.text
        with repository.connection(service.db_path) as db:
            db.execute("PRAGMA user_version=99")
        replacement = ExtractionJobService(configured)
        with pytest.raises(ReceiptStorageError):
            await replacement.start()
    asyncio.run(run())
