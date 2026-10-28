"""Literal contract oracles, no mapper-generated expectations or prior data."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from pypdf import PdfWriter

from app.integrations.airtable import AirtableClient
from app.main import app
from app.schemas.receipt import ReceiptData, ReceiptResponse, SyncResult, ValidationResult, NotificationResult
from app.services.receipt_service import ReceiptService
from app.storage import repository


LITERAL_DATA = {
    "merchant": "Contract Paper Store", "date": "2026-10-24", "receipt_number": None,
    "currency": "CAD", "total": "9.50", "subtotal": None, "tax": None,
    "tip": None, "discount": None,
    "items": [{"description": "Contract paper", "quantity": "1.5", "unit_price": "6.00", "amount": "9.00"}],
}


def expected_fields(receipt_id):
    return {"Vendor": "Contract Paper Store", "Date": "2026-10-24", "Amount": 9.5,
            "Currency": "CAD", "ReceiptID": receipt_id, "RawJSON": json.dumps(LITERAL_DATA)}


class ContractAcceptance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="airtable-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []
        self.remote_records = []
        self.create_mode = "success"
        self.read_error = False
        self.extractions = 0

        async def extract(*args):
            self.extractions += 1
            return ReceiptData(**LITERAL_DATA)

        def respond(request):
            self.requests.append(request)
            if request.method == "GET":
                self.assertIn("ReceiptID", request.url.params["filterByFormula"])
                if self.read_error:
                    raise httpx.ReadTimeout("Private contract detail", request=request)
                return httpx.Response(200, json={"records": self.remote_records})
            self.assertEqual(request.method, "POST")
            body = json.loads(request.content)
            self.assertEqual(set(body), {"records", "typecast"})
            self.assertFalse(body["typecast"])
            self.assertEqual(len(body["records"]), 1)
            fields = body["records"][0]["fields"]
            expected = expected_fields(fields["ReceiptID"])
            self.assertEqual(set(fields), set(expected))
            self.assertIsInstance(fields["Amount"], (int, float))
            self.assertEqual(json.loads(fields["RawJSON"]), LITERAL_DATA)
            self.assertEqual({k: v for k, v in fields.items() if k != "RawJSON"},
                             {k: v for k, v in expected.items() if k != "RawJSON"})
            local = repository.get_record(fields["ReceiptID"], db_path=self.service.db_path)
            self.assertEqual(local.response.status, "saved")
            self.assertTrue(local.response.validation.passed)
            self.assertEqual(local.response.sync.status, "unknown")
            self.assertEqual((self.root / local.original_pdf_ref).read_bytes(), b"%PDF-contract-sync")
            if self.create_mode == "reject":
                return httpx.Response(422, json={"error": "Private contract detail"})
            record = {"id": "recContract", "fields": expected_fields(fields["ReceiptID"])}
            if self.create_mode != "lost_absent":
                self.remote_records.append(record)
            if self.create_mode.startswith("lost"):
                raise httpx.ReadTimeout("Private contract detail", request=request)
            return httpx.Response(200, json={"records": [record]})

        self.adapter = AirtableClient(token="contract-only-token", base_id="appContract", table_id="Receipts",
                                     transport=httpx.MockTransport(respond))
        self.service = ReceiptService(self.root, extractor=extract, airtable=self.adapter)

    async def upload(self):
        return await self.service.process_receipt(b"%PDF-contract-sync", "contract.pdf")

    def posts(self):
        return sum(r.method == "POST" for r in self.requests)

    async def test_exact_contract_and_duplicate_reuse(self):
        results = await asyncio.gather(*(self.upload() for _ in range(7)))
        self.assertEqual(self.extractions, 1)
        self.assertEqual(self.posts(), 1)
        self.assertTrue(all(result == results[0] for result in results))
        result = results[0]
        self.assertEqual(result.sync, SyncResult(status="synced", record_id="recContract"))
        self.assertEqual(await self.service.retry_sync(result.receipt_id), result)
        self.assertEqual(await self.service.get_receipt(result.receipt_id), result)
        self.assertEqual(len(self.requests), 2)

    async def test_unconfigured_then_retry_without_model(self):
        self.service.airtable = AirtableClient(token="", base_id="appContract", table_id="Receipts")
        result = await self.upload()
        self.assertEqual(result.sync.status, "not_configured")
        self.assertEqual(self.requests, [])
        self.service.airtable = self.adapter
        result = await self.service.retry_sync(result.receipt_id)
        self.assertEqual(result.sync.status, "synced")
        self.assertEqual(self.extractions, 1)

    async def test_review_never_syncs(self):
        async def review(*args):
            return ReceiptData(**{**LITERAL_DATA, "currency": None})
        self.service.extractor = review
        result = await self.upload()
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(await self.service.retry_sync(result.receipt_id), result)
        self.assertEqual(self.requests, [])

    async def test_failed_never_syncs(self):
        async def failure(*args):
            raise RuntimeError("Private contract detail")
        self.service.extractor = failure
        result = await self.upload()
        self.assertEqual(result.status, "failed")
        self.assertEqual(await self.service.retry_sync(result.receipt_id), result)
        self.assertEqual(self.requests, [])

    async def test_adapter_rejects_saved_with_failed_validation(self):
        snapshot = ReceiptResponse(receipt_id="contract-id", status="saved", data=ReceiptData(**LITERAL_DATA),
                                   validation=ValidationResult(passed=False, issues=[]),
                                   sync=SyncResult(status="skipped"), notification=NotificationResult(status="not_sent"))
        async def forbidden():
            self.fail("Ineligible receipt must not cross the write barrier")
        result = await self.adapter.sync_receipt(snapshot, allow_create=True, before_create=forbidden)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(self.requests, [])

    async def test_rejection_preserves_evidence_and_retry(self):
        self.create_mode = "reject"
        result = await self.upload()
        self.assertEqual((result.status, result.sync.status), ("saved", "failed"))
        before = repository.get_record(result.receipt_id, db_path=self.service.db_path)
        self.create_mode = "success"
        result = await self.service.retry_sync(result.receipt_id)
        after = repository.get_record(result.receipt_id, db_path=self.service.db_path)
        self.assertEqual(result.sync.status, "synced")
        self.assertEqual(before.metadata, after.metadata)
        self.assertEqual(before.original_pdf_ref, after.original_pdf_ref)
        self.assertEqual(before.response.data, after.response.data)
        self.assertEqual(self.extractions, 1)

    async def test_lost_response_can_reconcile_without_second_create(self):
        self.create_mode = "lost_committed"
        result = await self.upload()
        self.assertEqual((result.status, result.sync.status), ("saved", "unknown"))
        self.read_error = True
        self.assertEqual((await self.service.retry_sync(result.receipt_id)).sync.status, "unknown")
        self.read_error = False
        result = await self.service.retry_sync(result.receipt_id)
        self.assertEqual(result.sync, SyncResult(status="synced", record_id="recContract"))
        self.assertEqual(self.posts(), 1)
        self.assertEqual(self.extractions, 1)

    async def test_absent_result_after_timeout_never_recreates(self):
        self.create_mode = "lost_absent"
        result = await self.upload()
        self.assertEqual(result.sync.status, "unknown")
        self.create_mode = "success"
        for _ in range(3):
            self.assertEqual((await self.service.retry_sync(result.receipt_id)).sync.status, "unknown")
        self.assertEqual(self.posts(), 1)

    async def test_existing_receipt_id_is_reused(self):
        self.service.airtable = None
        result = await self.upload()
        self.remote_records = [{"id": "recExisting", "fields": expected_fields(result.receipt_id)}]
        self.service.airtable = self.adapter
        result = await self.service.retry_sync(result.receipt_id)
        self.assertEqual(result.sync, SyncResult(status="synced", record_id="recExisting"))
        self.assertEqual(self.posts(), 0)

    async def test_duplicate_remote_ids_are_unknown(self):
        self.service.airtable = None
        result = await self.upload()
        self.remote_records = [{"id": "recFirst", "fields": expected_fields(result.receipt_id)},
                               {"id": "recSecond", "fields": expected_fields(result.receipt_id)}]
        self.service.airtable = self.adapter
        result = await self.service.retry_sync(result.receipt_id)
        self.assertEqual(result.sync.status, "unknown")
        self.assertIsNone(result.sync.record_id)
        self.assertEqual(self.posts(), 0)

    async def test_conflicting_remote_content_is_unknown(self):
        self.service.airtable = None
        result = await self.upload()
        fields = expected_fields(result.receipt_id)
        fields["RawJSON"] = json.dumps({**LITERAL_DATA, "items": None})
        self.remote_records = [{"id": "recConflict", "fields": fields}]
        self.service.airtable = self.adapter
        result = await self.service.retry_sync(result.receipt_id)
        self.assertEqual(result.sync.status, "unknown")
        self.assertEqual(self.posts(), 0)

    async def test_pending_recovers_as_unknown_without_creation(self):
        self.service.airtable = None
        result = await self.upload()
        repository.update_sync(result.receipt_id, SyncResult(status="pending"), db_path=self.service.db_path)
        repository.initialize_database(db_path=self.service.db_path, data_dir=self.root)
        result = await self.service.get_receipt(result.receipt_id)
        self.assertEqual((result.status, result.sync.status), ("saved", "unknown"))
        self.service.airtable = self.adapter
        self.assertEqual((await self.service.retry_sync(result.receipt_id)).sync.status, "unknown")
        self.assertEqual(self.posts(), 0)


class HttpContract(unittest.TestCase):
    def test_production_upload_retry_query_and_export(self):
        with tempfile.TemporaryDirectory(prefix="airtable-http-contract-") as directory:
            requests = []
            model_calls = []
            def respond(request):
                requests.append(request)
                if request.method == "GET":
                    return httpx.Response(200, json={"records": []})
                fields = json.loads(request.content)["records"][0]["fields"]
                return httpx.Response(200, json={"records": [{"id": "recHTTPContract", "fields": fields}]})
            async def extract(*args):
                from app.schemas.receipt import ExtractionMetadata
                model_calls.append(1)
                return ReceiptData(**LITERAL_DATA), ExtractionMetadata()
            def configured_client(**kwargs):
                return AirtableClient(**kwargs, transport=httpx.MockTransport(respond))
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            content = BytesIO()
            writer.write(content)
            headers = {"X-API-Key": "contract-http-key"}
            environment = {"APP_API_KEY": "contract-http-key", "DATA_DIR": directory,
                           "AIRTABLE_TOKEN": "contract-only-token", "AIRTABLE_BASE_ID": "appContract",
                           "AIRTABLE_TABLE_ID": "Receipts"}
            with patch.dict("os.environ", environment, clear=False), patch("app.main.AirtableClient", configured_client), \
                    patch("app.integrations.extractor.extract_with_metadata", extract), TestClient(app) as client:
                result = client.post("/api/v1/receipts", headers=headers,
                                     files={"file": ("contract.pdf", content.getvalue(), "application/pdf")})
                self.assertEqual(result.status_code, 200)
                result = result.json()
                self.assertEqual(result["sync"], {"status": "synced", "record_id": "recHTTPContract"})
                receipt_id = result["receipt_id"]
                self.assertEqual(client.post(f"/api/v1/receipts/{receipt_id}/sync").status_code, 401)
                self.assertEqual(client.post(f"/api/v1/receipts/{receipt_id}/sync", headers=headers).json(), result)
                self.assertEqual(client.get(f"/api/v1/receipts/{receipt_id}", headers=headers).json(), result)
                self.assertEqual(client.get(f"/api/v1/receipts/{receipt_id}/export", headers=headers).status_code, 501)
                self.assertEqual(len(requests), 2)
                self.assertEqual(model_calls, [1])
