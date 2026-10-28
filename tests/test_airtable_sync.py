"""Offline sync regression using HTTP transports and isolated local stores."""
import asyncio
from io import BytesIO
import json
import sqlite3

from fastapi.testclient import TestClient
import httpx
from pypdf import PdfWriter
import pytest

from app.config import Settings
from app.contracts import ReceiptStorageError
from app.integrations.airtable import AirtableClient
from app.main import app
from app.schemas.receipt import ExtractionMetadata, ReceiptData, SyncResult
from app.services.receipt_service import ReceiptService
from app.storage import repository


def data(**changes):
    values = dict(merchant="Offline Sync Shop", date="2026-10-28", currency="USD", total="12.30",
                  items=[dict(description="Offline item", quantity="2", unit_price="6.00", amount="12.00")])
    values.update(changes)
    return ReceiptData(**values)


class Remote:
    def __init__(self):
        self.records = []
        self.requests = []
        self.write = "success"
        self.read = "success"
        self.db_path = None

    def __call__(self, request):
        self.requests.append(request)
        if self.db_path:
            with repository.connection(self.db_path) as db:
                rows = db.execute("SELECT * FROM receipts").fetchall()
            assert len(rows) == 1 and rows[0]["status"] == "saved"
            snapshot = json.loads(rows[0]["response_json"])
            assert snapshot["validation"]["passed"] is True
            if request.method == "POST":
                assert snapshot["sync"]["status"] == "unknown"
        if request.method == "GET":
            if self.read == "timeout":
                raise httpx.ReadTimeout("private synthetic detail", request=request)
            if self.read == "forbidden":
                return httpx.Response(403, json={"error": "private synthetic detail"})
            if self.read == "malformed":
                return httpx.Response(200, json={"records": None})
            return httpx.Response(200, json={"records": self.records})
        assert request.method == "POST"
        if self.write in {401, 403, 422, 429, 408, 500, 503}:
            return httpx.Response(self.write, json={"error": "private synthetic detail"})
        body = json.loads(request.content)
        assert body["typecast"] is False
        record = {"id": "recOffline123", "fields": body["records"][0]["fields"]}
        if self.write != "timeout_absent":
            self.records.append(record)
        if self.write in {"timeout_committed", "timeout_absent"}:
            raise httpx.ReadTimeout("private synthetic detail", request=request)
        if self.write == "broken_success":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json={"records": [record]})

    def client(self, **changes):
        args = dict(token="offline-only-token", base_id="appOffline", table_id="Receipts",
                    transport=httpx.MockTransport(self))
        args.update(changes)
        return AirtableClient(**args)


def test_success_mapping_persistence_and_concurrent_duplicates(tmp_path):
    async def scenario():
        remote = Remote()
        calls = []

        async def extract(*args):
            calls.append(args)
            return data()

        services = [ReceiptService(tmp_path, extractor=extract, airtable=remote.client()) for _ in range(3)]
        remote.db_path = services[0].db_path
        results = await asyncio.gather(*(services[i % 3].process_receipt(b"%PDF-offline", str(i)) for i in range(12)))
        first = results[0]
        assert all(result == first for result in results)
        assert len(calls) == 1 and [r.method for r in remote.requests] == ["GET", "POST"]
        assert first.status == "saved" and first.sync == SyncResult(status="synced", record_id="recOffline123")
        fields = remote.records[0]["fields"]
        assert set(fields) == {"Vendor", "Date", "Amount", "Currency", "RawJSON", "ReceiptID"}
        assert fields["ReceiptID"] == first.receipt_id
        assert fields["Vendor"] == "Offline Sync Shop" and fields["Date"] == "2026-10-28"
        assert fields["Amount"] == 12.3 and isinstance(fields["Amount"], float)
        assert fields["Currency"] == "USD"
        assert json.loads(fields["RawJSON"]) == data().model_dump(mode="json")
        assert json.loads(fields["RawJSON"])["tax"] is None
        assert remote.requests[0].url.params["filterByFormula"] == "{ReceiptID}='" + first.receipt_id + "'"
        assert str(remote.requests[0].url).startswith("https://api.airtable.com/v0/appOffline/Receipts?")
        assert await services[0].retry_sync(first.receipt_id) == first
        assert await services[0].get_receipt(first.receipt_id) == first
        return first
    first = asyncio.run(scenario())
    # A fresh event loop simulates sequential restart, with no network for confirmed records.
    async def restart():
        service = ReceiptService(tmp_path, airtable=Remote().client())
        assert await service.retry_sync(first.receipt_id) == first
    asyncio.run(restart())


@pytest.mark.parametrize("mode", ["review", "extract_failure", "original_failure", "commit_failure"])
def test_ineligible_or_unsaved_never_calls_remote(tmp_path, monkeypatch, mode):
    async def extract(*args):
        if mode == "extract_failure":
            raise RuntimeError("private synthetic detail")
        return data(currency=None) if mode == "review" else data()
    if mode in {"original_failure", "commit_failure"}:
        def broken(*args, **kwargs):
            raise OSError("private synthetic detail")
        if mode == "original_failure":
            monkeypatch.setattr("app.storage.files.save_original_pdf", broken)
        else:
            original = repository.save_receipt
            def reject_saved(receipt, **kwargs):
                if receipt.status == "saved":
                    broken()
                return original(receipt, **kwargs)
            monkeypatch.setattr(repository, "save_receipt", reject_saved)
    async def scenario():
        remote = Remote()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client())
        result = await service.process_receipt(b"%PDF-ineligible", "offline.pdf")
        assert result.status == ("needs_review" if mode == "review" else "failed")
        assert await service.retry_sync(result.receipt_id) == result
        assert remote.requests == [] and result.sync.status == "skipped"
    asyncio.run(scenario())


@pytest.mark.parametrize("missing", ["token", "base_id", "table_id"])
def test_not_configured_can_retry_without_model(tmp_path, missing):
    async def scenario():
        remote = Remote()
        calls = []
        async def extract(*args):
            calls.append(1)
            return data()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client(**{missing: ""}))
        response = await service.process_receipt(b"%PDF-unconfigured", "x.pdf")
        assert response.status == "saved" and response.sync.status == "not_configured"
        assert remote.requests == []
        service.airtable = remote.client()
        assert (await service.retry_sync(response.receipt_id)).sync.status == "synced"
        assert len(calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("status,expected", [(401, "failed"), (403, "failed"), (422, "failed"),
                                           (429, "failed"), (408, "unknown"), (500, "unknown"), (503, "unknown")])
def test_remote_errors_preserve_local_saved(tmp_path, status, expected):
    async def scenario():
        remote = Remote()
        remote.write = status
        async def extract(*args):
            return data()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client())
        result = await service.process_receipt(b"%PDF-error", "x.pdf")
        assert result.status == "saved" and result.validation.passed and result.sync.status == expected
        assert "private synthetic detail" not in result.model_dump_json()
        record = repository.get_record(result.receipt_id, db_path=service.db_path)
        assert (tmp_path / record.original_pdf_ref).read_bytes() == b"%PDF-error"
        assert record.response == result and record.metadata.failure_code is None
        remote.write = "success"
        retried = await service.retry_sync(result.receipt_id)
        assert retried.sync.status == ("synced" if expected == "failed" else "unknown")
        assert sum(r.method == "POST" for r in remote.requests) == (2 if expected == "failed" else 1)
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["timeout_committed", "timeout_absent", "broken_success"])
def test_unknown_reconciliation_never_recreates(tmp_path, mode):
    async def first_run():
        remote = Remote()
        remote.write = mode
        calls = []
        async def extract(*args):
            calls.append(1)
            return data()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client())
        response = await service.process_receipt(b"%PDF-unknown", "x.pdf")
        assert response.sync.status == "unknown" and response.status == "saved"
        record = repository.get_record(response.receipt_id, db_path=service.db_path)
        assert record.response == response
        return remote, response, calls
    remote, response, calls = asyncio.run(first_run())
    async def restart():
        async def forbidden(*args):
            raise AssertionError("Retry must not call the model")
        service = ReceiptService(tmp_path, extractor=forbidden, airtable=remote.client())
        remote.read = "timeout"
        assert (await service.retry_sync(response.receipt_id)).sync.status == "unknown"
        remote.read = "success"
        result = await service.process_receipt(b"%PDF-unknown", "renamed.pdf")
        assert result.sync.status == ("unknown" if mode == "timeout_absent" else "synced")
        assert sum(r.method == "POST" for r in remote.requests) == 1 and calls == [1]
    asyncio.run(restart())


@pytest.mark.parametrize("read", ["timeout", "forbidden", "malformed"])
def test_lookup_failure_prevents_create_and_is_retryable(tmp_path, read):
    async def scenario():
        remote = Remote()
        remote.read = read
        async def extract(*args):
            return data()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client())
        result = await service.process_receipt(b"%PDF-read-error", "x.pdf")
        assert result.sync.status == "failed" and len(remote.requests) == 1
        remote.read = "success"
        assert (await service.retry_sync(result.receipt_id)).sync.status == "synced"
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["pending", "unknown", "synced"])
def test_sync_storage_fault_never_reclassifies_local_result(tmp_path, monkeypatch, stage):
    async def scenario():
        remote = Remote()
        async def extract(*args):
            return data()
        service = ReceiptService(tmp_path, extractor=extract, airtable=remote.client())
        original = repository.update_sync
        def broken(receipt_id, sync, **kwargs):
            if sync.status == stage:
                raise sqlite3.OperationalError("private synthetic detail")
            return original(receipt_id, sync, **kwargs)
        monkeypatch.setattr(repository, "update_sync", broken)
        with pytest.raises(ReceiptStorageError, match="local receipt retained"):
            await service.process_receipt(b"%PDF-sync-storage", "x.pdf")
        with repository.connection(service.db_path) as db:
            row = db.execute("SELECT receipt_id FROM receipts").fetchone()
        record = repository.get_record(row[0], db_path=service.db_path)
        assert record.response.status == "saved" and record.response.validation.passed
        assert record.metadata.failure_code is None
        assert sum(r.method == "POST" for r in remote.requests) == (1 if stage == "synced" else 0)
        monkeypatch.setattr(repository, "update_sync", original)
        result = await service.retry_sync(row[0])
        assert result.sync.status == ("synced" if stage in {"pending", "synced"} else "unknown")
    asyncio.run(scenario())


def test_production_http_wiring_retry_and_auth(monkeypatch, tmp_path):
    remote = Remote()
    calls = []
    async def extract(*args):
        calls.append(1)
        return data(), ExtractionMetadata()
    monkeypatch.setattr("app.integrations.extractor.extract_with_metadata", extract)
    monkeypatch.setenv("APP_API_KEY", "offline-http-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for key in ("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID"):
        monkeypatch.delenv(key, raising=False)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    headers = {"X-API-Key": "offline-http-key"}
    with TestClient(app) as client:
        response = client.post("/api/v1/receipts", headers=headers,
                               files={"file": ("offline.pdf", buffer.getvalue(), "application/pdf")})
        assert response.status_code == 200 and response.json()["sync"]["status"] == "not_configured"
        receipt_id = response.json()["receipt_id"]
        assert client.post(f"/api/v1/receipts/{receipt_id}/sync").status_code == 401
        assert client.post("/api/v1/receipts/missing/sync", headers=headers).status_code == 404
        app.state.receipt_service.airtable = remote.client()
        result = client.post(f"/api/v1/receipts/{receipt_id}/sync", headers=headers)
        assert result.status_code == 200 and result.json()["sync"]["status"] == "synced"
        assert client.get(f"/api/v1/receipts/{receipt_id}", headers=headers).json() == result.json()
        assert client.get(f"/api/v1/receipts/{receipt_id}/export", headers=headers).status_code == 501
        assert calls == [1]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_airtable_timeout_configuration_rejects_invalid(monkeypatch, value):
    monkeypatch.setenv("APP_API_KEY", "offline-config-key")
    monkeypatch.setenv("AIRTABLE_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="AIRTABLE_TIMEOUT_SECONDS"):
        Settings.from_env()
