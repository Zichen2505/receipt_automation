"""Additional deadline oracles; original contract assertions remain unchanged."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from app.integrations.airtable import AirtableClient
from app.main import app
from app.schemas.receipt import ReceiptData
from app.services.receipt_service import ReceiptService
from app.storage import repository


class TimeoutContract(unittest.IsolatedAsyncioTestCase):
    async def test_post_total_deadline_leaves_unknown(self):
        with tempfile.TemporaryDirectory(prefix="sync-deadline-") as directory:
            calls = []
            async def respond(request):
                calls.append(request.method)
                if request.method == "GET":
                    return httpx.Response(200, json={"records": []})
                await asyncio.Event().wait()
                raise AssertionError("Deadline must cancel this transport")
            async def extract(*args):
                return ReceiptData(merchant="Deadline Shop", date="2026-10-25", currency="USD", total="1.00")
            adapter = AirtableClient(token="deadline-only-token", base_id="appDeadline", table_id="Receipts",
                                     timeout_seconds=0.01, transport=httpx.MockTransport(respond))
            service = ReceiptService(Path(directory), extractor=extract, airtable=adapter)
            result = await asyncio.wait_for(service.process_receipt(b"%PDF-deadline", "deadline.pdf"), 5)
            self.assertEqual(result.status, "saved")
            self.assertEqual(result.sync.status, "unknown")
            self.assertEqual(calls, ["GET", "POST"])
            self.assertEqual(await service.get_receipt(result.receipt_id), result)

    async def test_http_retry_timeout_continues_to_persisted_success(self):
        with tempfile.TemporaryDirectory(prefix="sync-http-timeout-") as directory:
            entered, release = asyncio.Event(), asyncio.Event()
            extraction_calls = []
            async def extract(*args):
                extraction_calls.append(1)
                return ReceiptData(merchant="Wait Shop", date="2026-10-25", currency="USD", total="2.00")
            seed = ReceiptService(Path(directory), extractor=extract)
            saved = await seed.process_receipt(b"%PDF-wait", "wait.pdf")
            async def respond(request):
                if request.method == "GET":
                    return httpx.Response(200, json={"records": []})
                import json
                fields = json.loads(request.content)["records"][0]["fields"]
                entered.set()
                await release.wait()
                return httpx.Response(200, json={"records": [{"id": "recAfterWait", "fields": fields}]})
            environment = {"APP_API_KEY": "wait-contract-key", "DATA_DIR": directory,
                           "HTTP_WAIT_TIMEOUT_SECONDS": "0.05"}
            with patch.dict("os.environ", environment, clear=False):
                async with app.router.lifespan_context(app):
                    app.state.receipt_service.airtable = AirtableClient(
                        token="wait-only-token", base_id="appWait", table_id="Receipts",
                        transport=httpx.MockTransport(respond))
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        task = asyncio.create_task(client.post(f"/api/v1/receipts/{saved.receipt_id}/sync",
                                                             headers={"X-API-Key": "wait-contract-key"}))
                        try:
                            await asyncio.wait_for(entered.wait(), 5)
                            response = await asyncio.wait_for(task, 5)
                            self.assertEqual(response.status_code, 504)
                            self.assertEqual(response.json()["detail"]["code"], "sync_timeout")
                            self.assertEqual(response.json()["detail"]["outcome"], "unknown")
                            snapshot = repository.get_record(saved.receipt_id, db_path=seed.db_path).response
                            self.assertEqual((snapshot.status, snapshot.sync.status), ("saved", "unknown"))
                            self.assertTrue(app.state.http_tasks)
                        finally:
                            release.set()
                            await asyncio.wait_for(asyncio.gather(*tuple(app.state.http_tasks)), 5)
                        app.state.settings = replace(app.state.settings, http_wait_timeout_seconds=5)
                        response = await client.get(f"/api/v1/receipts/{saved.receipt_id}",
                                                    headers={"X-API-Key": "wait-contract-key"})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["sync"], {"status": "synced", "record_id": "recAfterWait"})
                        self.assertEqual(extraction_calls, [1])
