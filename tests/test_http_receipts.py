"""Offline HTTP acceptance with valid in-memory synthetic PDFs and injected extractors."""

import asyncio
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import httpx
from pypdf import PdfWriter
import pytest

from app.config import Settings
from app.contracts import ReceiptStorageError
from app.dependencies import get_receipt_service
from app.integrations import extractor
from app.main import app
from app.schemas.receipt import ReceiptData
from app.services.receipt_service import ReceiptService
from app.storage import files, repository


KEY = "http-test-only-key"
HEADERS = {"X-API-Key": KEY}
PRIVATE_ERROR = "synthetic-private-error-never-echo-739"


def pdf(pages=1, *, encrypted=False, label="synthetic"):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": label})
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def receipt(**overrides):
    values = dict(merchant="Synthetic HTTP Stationery", date="2026-09-17", currency="CAD",
                  subtotal="21.40", discount="-1.40", tax="2.60", tip="0.00", total="22.60",
                  items=[dict(description="Synthetic supplies", quantity="2", unit_price="10.70", amount="21.40")])
    values.update(overrides)
    return ReceiptData.model_validate(values)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for name in ("MODEL_API_KEY", "MODEL_NAME", "MAX_UPLOAD_BYTES", "MAX_PDF_PAGES", "HTTP_WAIT_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    state = {"data": receipt()}

    async def substitute(content, filename):
        calls.append((content, filename))
        return state["data"]

    service = ReceiptService(tmp_path, extractor=substitute)
    app.dependency_overrides[get_receipt_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service, calls, state
    finally:
        app.dependency_overrides.clear()


def upload(client, content=None, **kwargs):
    return client.post("/api/v1/receipts", headers=HEADERS,
                       files={"file": (kwargs.get("filename", "synthetic.pdf"),
                                       pdf() if content is None else content,
                                       kwargs.get("media_type", "application/pdf"))})


def test_upload_query_and_duplicate_reuse_real_service(api):
    client, service, calls, state = api
    content = pdf()
    original_data = state["data"].model_dump_json()
    response = upload(client, content, filename="../../untrusted.pdf")
    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "saved" and saved["validation"] == {"passed": True, "issues": []}
    assert saved["data"]["discount"] == "1.40" and saved["data"]["total"] == "22.60"
    assert saved["sync"]["status"] == "skipped" and saved["notification"]["status"] == "not_sent"
    assert set(saved) == {"receipt_id", "status", "data", "validation", "sync", "notification"}
    assert client.get(f"/api/v1/receipts/{saved['receipt_id']}", headers=HEADERS).json() == saved
    assert upload(client, content, filename="renamed.pdf").json() == saved
    assert len(calls) == 1 and calls[0] == (content, "../../untrusted.pdf")
    assert state["data"].model_dump_json() == original_data
    record = repository.get_record(saved["receipt_id"], db_path=service.db_path)
    assert (service.data_dir / record.original_pdf_ref).read_bytes() == content
    assert json.loads(record.metadata.extraction.raw_output) == json.loads(original_data)


def test_distinct_files_same_name_are_separate(api):
    client, _, calls, _ = api
    first = upload(client, pdf(label="first"), filename="same.pdf").json()
    second = upload(client, pdf(label="second"), filename="same.pdf").json()
    assert first["receipt_id"] != second["receipt_id"]
    assert len(calls) == 2


@pytest.mark.parametrize("overrides,code", [({"currency": None}, "missing_currency"), ({"total": "22.61"}, "total_mismatch")])
def test_business_review_is_http_200_and_persisted(api, overrides, code):
    client, _, calls, state = api
    state["data"] = receipt(**overrides)
    result = upload(client)
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "needs_review" and not body["validation"]["passed"]
    assert code in {issue["code"] for issue in body["validation"]["issues"]}
    assert client.get(f"/api/v1/receipts/{body['receipt_id']}", headers=HEADERS).json() == body
    assert len(calls) == 1


@pytest.mark.parametrize("key", [None, "wrong-key"])
@pytest.mark.parametrize("method,path", [("post", "/api/v1/receipts"), ("get", "/api/v1/receipts/missing")])
def test_auth_remains_required(api, key, method, path):
    client, _, calls, _ = api
    kwargs = {"files": {"file": ("synthetic.pdf", pdf(), "application/pdf")}} if method == "post" else {}
    result = client.request(method, path, headers={} if key is None else {"X-API-Key": key}, **kwargs)
    assert result.status_code == 401 and result.json()["detail"]["code"] == "unauthorized"
    assert calls == []


def test_query_missing_is_404(api):
    client, _, calls, _ = api
    result = client.get("/api/v1/receipts/missing", headers=HEADERS)
    assert result.status_code == 404 and result.json()["detail"]["code"] == "not_found"
    assert calls == []


@pytest.mark.parametrize("content,media,status,code", [
    (b"", "application/pdf", 400, "empty_file"),
    (b"This is not a PDF", "application/pdf", 415, "unsupported_media_type"),
    (b"%PDF-1.7\nmalformed", "application/pdf", 422, "invalid_pdf"),
    (pdf(), "text/plain", 415, "unsupported_media_type"),
    (pdf(0), "application/pdf", 422, "invalid_pdf"),
    (pdf(encrypted=True), "application/pdf", 422, "encrypted_pdf"),
])
def test_invalid_upload_never_calls_service(api, content, media, status, code):
    client, service, calls, _ = api
    result = upload(client, content, media_type=media)
    assert result.status_code == status and result.json()["detail"]["code"] == code
    assert calls == []
    with repository.connection(service.db_path) as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_octet_stream_with_valid_pdf_does_not_depend_on_filename_suffix(api):
    client, _, calls, _ = api
    assert upload(client, filename="upload.bin", media_type="application/octet-stream").status_code == 200
    assert len(calls) == 1


def test_exact_byte_and_page_limits_are_inclusive(api):
    client, _, calls, _ = api
    content = pdf(2)
    app.state.settings = replace(app.state.settings, max_upload_bytes=len(content), max_pdf_pages=2)
    assert upload(client, content).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("kind,code", [("bytes", "file_too_large"), ("pages", "too_many_pages")])
def test_configured_file_limits_reject_before_extraction(api, kind, code):
    client, _, calls, _ = api
    content = pdf(2)
    changes = {"max_upload_bytes": len(content) - 1} if kind == "bytes" else {"max_pdf_pages": 1}
    app.state.settings = replace(app.state.settings, **changes)
    result = upload(client, content)
    assert result.status_code == 413 and result.json()["detail"]["code"] == code
    assert calls == []


def test_multipart_envelope_limit_catches_body_before_spooling(api):
    client, _, calls, _ = api
    app.state.settings = replace(app.state.settings, max_upload_bytes=512)
    result = upload(client, b"%PDF-" + b"x" * 70000)
    assert result.status_code == 413 and result.json()["detail"]["code"] == "request_too_large"
    assert calls == []


def test_technical_extraction_failure_is_502_with_durable_queryable_id(api):
    client, service, calls, _ = api

    async def broken(*args):
        calls.append("broken")
        raise RuntimeError(PRIVATE_ERROR)

    service.extractor = broken
    first = upload(client)
    assert first.status_code == 502
    body = first.json()
    assert body["status"] == "failed" and not body["validation"]["passed"]
    assert body["validation"]["issues"] == []
    assert PRIVATE_ERROR not in first.text
    assert upload(client).json() == body
    query = client.get(f"/api/v1/receipts/{body['receipt_id']}", headers=HEADERS)
    assert query.status_code == 200 and query.json() == body
    assert calls == ["broken"]


def test_original_storage_failure_is_durable_502_without_extraction(api, monkeypatch):
    client, _, calls, _ = api

    def broken(*args, **kwargs):
        raise OSError(PRIVATE_ERROR)

    monkeypatch.setattr(files, "save_original_pdf", broken)
    result = upload(client)
    assert result.status_code == 502 and result.json()["status"] == "failed"
    assert PRIVATE_ERROR not in result.text and calls == []


def test_uncommittable_storage_is_sanitized_503_and_next_query_recovers(api, monkeypatch):
    client, service, calls, _ = api

    def broken(*args, **kwargs):
        raise OSError(PRIVATE_ERROR)

    with monkeypatch.context() as injected:
        injected.setattr(repository, "save_receipt", broken)
        result = upload(client)
    assert result.status_code == 503 and result.json()["detail"]["code"] == "storage_unavailable"
    assert result.json()["detail"]["outcome"] == "unknown" and PRIVATE_ERROR not in result.text
    with repository.connection(service.db_path) as db:
        receipt_id = db.execute("SELECT receipt_id FROM receipts").fetchone()[0]
    query = client.get(f"/api/v1/receipts/{receipt_id}", headers=HEADERS)
    assert query.status_code == 200 and query.json()["status"] == "failed"
    assert upload(client).status_code == 502 and len(calls) == 1


@pytest.mark.parametrize("error,status,code", [(ReceiptStorageError(PRIVATE_ERROR), 503, "storage_unavailable"),
                                               (RuntimeError(PRIVATE_ERROR), 500, "internal_error")])
def test_query_errors_are_sanitized(api, monkeypatch, error, status, code):
    client, service, _, _ = api
    monkeypatch.setattr(service, "get_receipt", AsyncMock(side_effect=error))
    result = client.get("/api/v1/receipts/synthetic", headers=HEADERS)
    assert result.status_code == status and result.json()["detail"]["code"] == code
    assert result.json()["detail"]["outcome"] == "unknown" and PRIVATE_ERROR not in result.text


def test_default_http_service_uses_production_metadata_adapter_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    request = AsyncMock(return_value=SimpleNamespace(status="completed", output_text=receipt().model_dump_json()))
    monkeypatch.setattr(extractor, "request_extraction", request)
    with TestClient(app) as client:
        assert app.state.receipt_service.extractor is None
        result = upload(client)
    assert result.status_code == 200 and result.json()["status"] == "saved"
    request.assert_awaited_once()


def test_processing_and_query_timeouts_preserve_owner_until_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HTTP_WAIT_TIMEOUT_SECONDS", "0.03")

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def gated(content, filename):
            calls.append(filename)
            entered.set()
            await release.wait()
            return receipt()

        async with app.router.lifespan_context(app):
            service = ReceiptService(tmp_path, extractor=gated)
            app.state.receipt_service = service
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                request = asyncio.create_task(client.post("/api/v1/receipts", headers=HEADERS,
                    files={"file": ("slow.pdf", pdf(), "application/pdf")}))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    timed_out = await asyncio.wait_for(request, 5)
                    assert timed_out.status_code == 504
                    assert timed_out.json()["detail"]["code"] == "processing_timeout"
                    assert timed_out.json()["detail"]["outcome"] == "unknown"
                    assert "status" not in timed_out.json()
                    assert app.state.http_tasks
                    with repository.connection(service.db_path) as db:
                        receipt_id, status = db.execute("SELECT receipt_id,status FROM receipts").fetchone()
                    assert status == "processing"
                    query = await client.get(f"/api/v1/receipts/{receipt_id}", headers=HEADERS)
                    assert query.status_code == 504 and query.json()["detail"]["code"] == "query_timeout"
                    duplicate = await client.post("/api/v1/receipts", headers=HEADERS,
                        files={"file": ("duplicate.pdf", pdf(), "application/pdf")})
                    assert duplicate.status_code == 504 and len(calls) == 1
                finally:
                    release.set()
                    await asyncio.wait_for(asyncio.gather(*tuple(app.state.http_tasks)), 5)
                result = await client.get(f"/api/v1/receipts/{receipt_id}", headers=HEADERS)
                assert result.status_code == 200 and result.json()["status"] == "saved"
                assert len(calls) == 1
                assert not app.state.http_tasks

    asyncio.run(scenario())


def test_disconnected_http_request_does_not_cancel_processing(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def gated(*args):
            entered.set()
            await release.wait()
            return receipt()

        async with app.router.lifespan_context(app):
            app.state.receipt_service = ReceiptService(tmp_path, extractor=gated)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                task = asyncio.create_task(client.post("/api/v1/receipts", headers=HEADERS,
                    files={"file": ("disconnect.pdf", pdf(), "application/pdf")}))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    assert app.state.http_tasks
                finally:
                    release.set()
                    await asyncio.wait_for(asyncio.gather(*tuple(app.state.http_tasks)), 5)
                result = await client.post("/api/v1/receipts", headers=HEADERS,
                    files={"file": ("after-disconnect.pdf", pdf(), "application/pdf")})
                assert result.status_code == 200 and result.json()["status"] == "saved"

    asyncio.run(scenario())


@pytest.mark.parametrize("name,value", [("MAX_UPLOAD_BYTES", "0"), ("MAX_UPLOAD_BYTES", "invalid"),
                                       ("MAX_PDF_PAGES", "-1"), ("MAX_PDF_PAGES", "1.5"),
                                       ("HTTP_WAIT_TIMEOUT_SECONDS", "0"), ("HTTP_WAIT_TIMEOUT_SECONDS", "nan"),
                                       ("HTTP_WAIT_TIMEOUT_SECONDS", "inf")])
def test_invalid_limits_fail_configuration_without_echoing_values(monkeypatch, name, value):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_explicit_local_dotenv_does_not_override_environment_or_interpolate(monkeypatch, tmp_path):
    from app import main
    env_file = tmp_path / ".env"
    env_file.write_text("APP_API_KEY=synthetic-file-key\nPORT=8765\nMODEL_NAME=${NOT_EXPANDED}\n", encoding="utf-8")
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setattr("sys.argv", ["app.main", "--env-file", str(env_file)])
    # Uvicorn.run is synchronous; a normal spy prevents creating a server.
    from unittest.mock import Mock
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    main.run()
    assert Settings.from_env().app_api_key == KEY
    assert Settings.from_env().model_name == "${NOT_EXPANDED}"
    assert run.call_args.kwargs["port"] == 8765


def test_default_runner_never_loads_dotenv(monkeypatch):
    from app import main
    from unittest.mock import Mock
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setattr("sys.argv", ["app.main"])
    load = Mock(side_effect=AssertionError("Implicit dotenv access"))
    monkeypatch.setattr("dotenv.load_dotenv", load)
    monkeypatch.setattr("uvicorn.run", Mock())
    main.run()
    load.assert_not_called()


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_streamed_multipart_overflow_closes_spooled_files_without_trusting_length(monkeypatch, tmp_path, declared_length):
    import starlette.formparsers
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(1024 * 1024))
    opened = []
    actual = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        file = actual(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)

    async def scenario():
        async def forbidden(*args):
            pytest.fail("Overflow must be rejected before extraction")

        async def chunks():
            yield (b'--synthetic-boundary\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\n'
                   b'Content-Type: application/pdf\r\n\r\n%PDF-1.7\n' + b"x" * (1024 * 1024 + 4096))
            yield b"x" * 70000
            yield b"\r\n--synthetic-boundary--\r\n"

        async with app.router.lifespan_context(app):
            app.state.receipt_service = ReceiptService(tmp_path, extractor=forbidden)
            headers = dict(HEADERS, **{"Content-Type": "multipart/form-data; boundary=synthetic-boundary"})
            if declared_length is not None:
                headers["Content-Length"] = declared_length
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/receipts", headers=headers, content=chunks())
            assert response.status_code == 413 and response.json()["detail"]["code"] == "request_too_large"
            assert opened and all(file.closed for file in opened)

    asyncio.run(scenario())


@pytest.mark.parametrize("uncommittable", [False, True])
def test_detached_failure_after_timeout_is_never_reported_as_premature_terminal(monkeypatch, tmp_path, uncommittable):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HTTP_WAIT_TIMEOUT_SECONDS", "0.03")

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def broken(*args):
            entered.set()
            await release.wait()
            raise RuntimeError(PRIVATE_ERROR)

        def no_commit(*args, **kwargs):
            raise OSError(PRIVATE_ERROR)

        async with app.router.lifespan_context(app):
            service = ReceiptService(tmp_path, extractor=broken)
            app.state.receipt_service = service
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                with monkeypatch.context() as injection:
                    if uncommittable:
                        injection.setattr(repository, "save_receipt", no_commit)
                    try:
                        response = await client.post("/api/v1/receipts", headers=HEADERS,
                            files={"file": ("slow-failure.pdf", pdf(), "application/pdf")})
                        assert response.status_code == 504 and response.json()["detail"]["outcome"] == "unknown"
                        # The HTTP deadline can expire before the claim reaches disk.
                        await asyncio.wait_for(entered.wait(), 5)
                        with repository.connection(service.db_path) as db:
                            receipt_id, status = db.execute("SELECT receipt_id,status FROM receipts").fetchone()
                        assert status == "processing"
                    finally:
                        release.set()
                        pending = tuple(app.state.http_tasks)
                        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 5)
                # Query completion is a separate assertion, with a normal query budget.
                app.state.settings = replace(app.state.settings, http_wait_timeout_seconds=5)
                result = await client.get(f"/api/v1/receipts/{receipt_id}", headers=HEADERS)
                assert result.status_code == 200 and result.json()["status"] == "failed"
                assert PRIVATE_ERROR not in result.text

    asyncio.run(scenario())


def test_graceful_shutdown_waits_for_timed_out_processing(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HTTP_WAIT_TIMEOUT_SECONDS", "0.03")

    async def scenario():
        release = asyncio.Event()

        async def gated(*args):
            await release.wait()
            return receipt()

        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        app.state.receipt_service = ReceiptService(tmp_path, extractor=gated)
        shutdown = None
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/receipts", headers=HEADERS,
                    files={"file": ("shutdown.pdf", pdf(), "application/pdf")})
            assert response.status_code == 504
            shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
            await asyncio.sleep(0)
            assert not shutdown.done()
        finally:
            release.set()
            if shutdown is None:
                await lifespan.__aexit__(None, None, None)
            else:
                await asyncio.wait_for(shutdown, 5)
        with repository.connection(tmp_path / "receipts.sqlite3") as db:
            assert db.execute("SELECT status FROM receipts").fetchone()[0] == "saved"

    asyncio.run(scenario())
