"""Independent service, persistence, failure and restart acceptance cases."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from app.contracts import ReceiptStorageError
from app.schemas.receipt import ProcessingMetadata
from app.services import receipt_service as service_module
from app.services.receipt_service import ReceiptService
from app.storage import files, repository
from test_contract import complete


HERE = Path(__file__).resolve().parent
PAYLOAD = b"Independent offline byte payload 83; no PDF interpretation is claimed.\x00\xff"
FAULT_DETAIL = "SYNTHETIC-PRIVATE-FAILURE-DETAIL-482"


class WorkflowContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="receipt-independent-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "receipts.sqlite3"
        self.old_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = str(self.root)
        self.addCleanup(self.restore_environment)
        self.calls = []
        self.raw = complete(discount="-6.40")

        async def substitute(pdf_bytes, filename):
            self.calls.append((pdf_bytes, filename))
            return self.raw

        self.substitute = substitute
        self.service = ReceiptService(self.root, extractor=substitute)

    def restore_environment(self):
        if self.old_data_dir is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.old_data_dir

    async def record(self, receipt_id):
        return await asyncio.to_thread(repository.get_record, receipt_id, db_path=self.db)

    async def all_ids(self):
        def read():
            with closing(sqlite3.connect(self.db)) as db:
                return [row[0] for row in db.execute("SELECT receipt_id FROM receipts")]
        return await asyncio.to_thread(read)

    def deferred(self, response):
        self.assertEqual(response.sync.status, "skipped")
        self.assertIsNone(response.sync.record_id)
        self.assertEqual(response.notification.status, "not_sent")
        self.assertIsNone(response.notification.event_id)

    async def assert_failed(self, response):
        self.assertEqual(response.status, "failed")
        self.assertFalse(response.validation.passed)
        self.assertEqual(response.validation.issues, [])
        self.deferred(response)
        record = await self.record(response.receipt_id)
        self.assertEqual(record.response, response)
        self.assertTrue(record.metadata.failure_code.strip())
        self.assertNotIn(FAULT_DETAIL, record.model_dump_json())
        return record

    async def child(self, mode, receipt_id, payload=PAYLOAD):
        command = [sys.executable, "-B", str(HERE / "run.py"), "--worker", mode,
                   str(self.root), receipt_id, payload.hex()]
        result = await asyncio.to_thread(subprocess.run, command, capture_output=True,
                                         text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["guard_violations"], [])
        self.assertEqual(value["extractor_calls"], 0)
        return value

    async def seed_interruption(self, original_state):
        await asyncio.to_thread(repository.initialize_database, db_path=self.db, data_dir=self.root)
        receipt_id = str(uuid4())
        record, owner = await asyncio.to_thread(repository.claim_receipt, receipt_id,
                                               hashlib.sha256(PAYLOAD).hexdigest(), db_path=self.db)
        self.assertTrue(owner)
        if original_state != "absent":
            reference = await asyncio.to_thread(files.save_original_pdf, PAYLOAD, receipt_id, data_dir=self.root)
            if original_state == "attached":
                await asyncio.to_thread(repository.attach_original, receipt_id, reference, db_path=self.db)
            elif original_state == "corrupt":
                (self.root / reference).write_bytes(b"Deliberately corrupt synthetic original")
        return record

    async def test_saved_query_audit_original_and_input_immutability(self):
        before = self.raw.model_dump_json()
        filename = "../../untrusted-upload-name.pdf"
        response = await self.service.process_receipt(PAYLOAD, filename)
        self.assertEqual(response.status, "saved")
        self.assertTrue(response.validation.passed)
        self.assertEqual(response.validation.issues, [])
        self.deferred(response)
        self.assertEqual(self.calls, [(PAYLOAD, filename)])
        self.assertEqual(self.raw.model_dump_json(), before)
        self.assertEqual(response.data, complete())
        self.assertEqual(str(UUID(response.receipt_id)), response.receipt_id)
        self.assertNotEqual(response.receipt_id, response.data.receipt_number)
        record = await self.record(response.receipt_id)
        self.assertEqual(record.response, response)
        self.assertEqual(record.pdf_sha256, hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual(record.original_pdf_ref, f"originals/{response.receipt_id}.pdf")
        self.assertEqual((self.root / record.original_pdf_ref).read_bytes(), PAYLOAD)
        self.assertTrue((self.root / record.original_pdf_ref).resolve().is_relative_to(self.root))
        self.assertEqual(json.loads(record.metadata.extraction.raw_output), json.loads(before))
        event = record.metadata.extraction.normalizations[0]
        self.assertEqual(str(event.original_value), "-6.40")
        self.assertEqual(str(event.normalized_value), "6.40")
        self.assertTrue(event.reason.strip())
        self.assertIsNone(record.metadata.failure_code)
        self.assertIsNone(record.metadata.recovery_reason)
        for timestamp in (record.created_at, record.updated_at):
            self.assertEqual(datetime.fromisoformat(timestamp).utcoffset(), timedelta(0))
        self.assertGreaterEqual(record.updated_at, record.created_at)
        queried = await self.service.get_receipt(response.receipt_id)
        self.assertEqual(queried, response)
        self.assertEqual(set(queried.model_dump()),
                         {"receipt_id", "status", "data", "validation", "sync", "notification"})
        # Returned objects must not rewrite persisted snapshots.
        queried.data.merchant = "Changed only in caller memory"
        response.data.total = None
        self.assertEqual((await self.service.get_receipt(record.response.receipt_id)), record.response)

    async def test_unknown_query_returns_none(self):
        self.assertIsNone(await self.service.get_receipt(str(uuid4())))

    async def test_business_conflict_is_stored_needs_review_with_printed_total(self):
        self.raw = complete(total="83.30", discount="-6.40")
        response = await self.service.process_receipt(PAYLOAD, "conflict.pdf")
        self.assertEqual(response.status, "needs_review")
        self.assertFalse(response.validation.passed)
        self.assertEqual([(i.code, i.field) for i in response.validation.issues], [("total_mismatch", "total")])
        self.assertEqual(str(response.data.total), "83.30")
        self.deferred(response)
        record = await self.record(response.receipt_id)
        self.assertEqual(record.response, response)
        self.assertEqual((self.root / record.original_pdf_ref).read_bytes(), PAYLOAD)

    async def test_missing_required_field_is_stored_without_guessing(self):
        self.raw = complete(currency=None)
        response = await self.service.process_receipt(PAYLOAD, "unknown-currency.pdf")
        self.assertEqual(response.status, "needs_review")
        self.assertIsNone(response.data.currency)
        self.assertEqual([(i.code, i.field) for i in response.validation.issues], [("missing_currency", "currency")])
        self.assertEqual((await self.record(response.receipt_id)).response, response)

    async def test_optional_nulls_can_be_saved_without_invented_zero(self):
        self.raw = complete(discount=None, tax=None, tip=None, items=None)
        response = await self.service.process_receipt(PAYLOAD, "unknown-components.pdf")
        self.assertEqual(response.status, "saved")
        for field in ("discount", "tax", "tip", "items"):
            self.assertIsNone(getattr(response.data, field))
        self.assertIsNone((await self.record(response.receipt_id)).metadata.extraction.normalizations[0].original_value)

    async def test_duplicate_bytes_with_different_name_reuse_complete_snapshot(self):
        first = await self.service.process_receipt(PAYLOAD, "first-name.pdf")
        second = await self.service.process_receipt(PAYLOAD, "renamed.pdf")
        self.assertEqual(second, first)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(await self.all_ids(), [first.receipt_id])
        self.assertEqual(len(list((self.root / "originals").iterdir())), 1)

    async def test_distinct_bytes_same_filename_get_distinct_records(self):
        first = await self.service.process_receipt(PAYLOAD, "same.pdf")
        different = PAYLOAD + b"second independent content"
        second = await self.service.process_receipt(different, "same.pdf")
        self.assertNotEqual(first.receipt_id, second.receipt_id)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(set(await self.all_ids()), {first.receipt_id, second.receipt_id})
        for response, original in ((first, PAYLOAD), (second, different)):
            record = await self.record(response.receipt_id)
            self.assertEqual((self.root / record.original_pdf_ref).read_bytes(), original)
            self.assertEqual(record.pdf_sha256, hashlib.sha256(original).hexdigest())

    async def test_concurrent_duplicate_requests_across_instances_have_one_owner(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def gated(pdf_bytes, filename):
            nonlocal calls
            calls += 1
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
            return self.raw

        services = [ReceiptService(self.root / ".", extractor=gated) for _ in range(4)]
        tasks = [asyncio.create_task(services[i % 4].process_receipt(PAYLOAD, f"duplicate-{i}.pdf"))
                 for i in range(17)]
        try:
            await asyncio.wait_for(entered.wait(), 10)
        finally:
            release.set()
        responses = await asyncio.wait_for(asyncio.gather(*tasks), 20)
        self.assertEqual(calls, 1)
        self.assertTrue(all(r == responses[0] for r in responses))
        self.assertEqual(responses[0].status, "saved")
        self.assertEqual(await self.all_ids(), [responses[0].receipt_id])

    async def test_claim_and_original_are_committed_before_awaiting_extractor(self):
        async def checking(pdf_bytes, filename):
            def inspect():
                with closing(sqlite3.connect(self.db, timeout=1)) as db:
                    # This must succeed while extraction is active: no write transaction is held.
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT receipt_id,status,pdf_sha256,original_pdf_ref FROM receipts").fetchone()
                    db.rollback()
                    return row
            row = await asyncio.to_thread(inspect)
            self.assertEqual(row[1], "processing")
            self.assertEqual(row[2], hashlib.sha256(PAYLOAD).hexdigest())
            self.assertEqual((self.root / row[3]).read_bytes(), PAYLOAD)
            return self.raw

        response = await ReceiptService(self.root, extractor=checking).process_receipt(PAYLOAD, "ordering.pdf")
        self.assertEqual(response.status, "saved")

    async def test_storage_and_validation_execute_away_from_event_loop_thread(self):
        loop_thread = threading.get_ident()
        seen = []

        def observe(name, actual):
            def wrapped(*args, **kwargs):
                seen.append((name, threading.get_ident()))
                return actual(*args, **kwargs)
            return wrapped

        from contextlib import ExitStack
        with ExitStack() as patches:
            for module, name in ((repository, "initialize_database"), (repository, "claim_receipt"),
                                 (files, "save_original_pdf"), (repository, "attach_original"),
                                 (repository, "save_receipt"), (repository, "get_receipt"),
                                 (service_module, "validate_receipt")):
                patches.enter_context(patch.object(module, name, observe(name, getattr(module, name))))
            response = await self.service.process_receipt(PAYLOAD, "threads.pdf")
            await self.service.get_receipt(response.receipt_id)
        self.assertEqual(response.status, "saved")
        self.assertEqual(len(seen), 7)
        self.assertTrue(all(thread != loop_thread for _, thread in seen), seen)

    async def test_terminal_response_cannot_be_overwritten(self):
        response = await self.service.process_receipt(PAYLOAD, "terminal.pdf")
        before = await self.record(response.receipt_id)
        altered = response.model_copy(deep=True)
        altered.data.merchant = "Forbidden replacement"
        with self.assertRaises(Exception):
            await asyncio.to_thread(repository.save_receipt, altered, db_path=self.db,
                                    original_pdf_ref=before.original_pdf_ref, metadata=ProcessingMetadata())
        self.assertEqual(await self.record(response.receipt_id), before)

    async def test_extractor_failure_is_sanitized_persisted_and_never_retried(self):
        calls = 0

        async def failing(pdf_bytes, filename):
            nonlocal calls
            calls += 1
            raise RuntimeError(FAULT_DETAIL)

        service = ReceiptService(self.root, extractor=failing)
        response = await service.process_receipt(PAYLOAD, "failure.pdf")
        record = await self.assert_failed(response)
        self.assertEqual((self.root / record.original_pdf_ref).read_bytes(), PAYLOAD)
        self.assertEqual(await service.process_receipt(PAYLOAD, "retry-forbidden.pdf"), response)
        self.assertEqual(calls, 1)

    async def test_validation_execution_failure_is_technical_failure(self):
        with patch.object(service_module, "validate_receipt", side_effect=RuntimeError(FAULT_DETAIL)):
            response = await self.service.process_receipt(PAYLOAD, "validation-failure.pdf")
        await self.assert_failed(response)

    async def test_original_save_failure_does_not_extract_or_claim_original(self):
        with patch.object(files, "save_original_pdf", side_effect=OSError(FAULT_DETAIL)):
            response = await self.service.process_receipt(PAYLOAD, "original-failure.pdf")
        record = await self.assert_failed(response)
        self.assertEqual(self.calls, [])
        self.assertIsNone(record.original_pdf_ref)
        self.assertEqual(await self.service.process_receipt(PAYLOAD, "duplicate-failure.pdf"), response)
        self.assertEqual(self.calls, [])

    async def test_terminal_commit_failure_falls_back_to_durable_failed(self):
        original_save = repository.save_receipt

        def fault(receipt, **kwargs):
            if receipt.status == "saved":
                raise OSError(FAULT_DETAIL)
            return original_save(receipt, **kwargs)

        with patch.object(repository, "save_receipt", side_effect=fault):
            response = await self.service.process_receipt(PAYLOAD, "commit-failure.pdf")
        await self.assert_failed(response)
        self.assertEqual(len(self.calls), 1)

    async def test_permanent_commit_failure_raises_then_recovers_before_next_operation(self):
        with patch.object(repository, "save_receipt", side_effect=OSError(FAULT_DETAIL)):
            with self.assertRaises(ReceiptStorageError) as caught:
                await self.service.process_receipt(PAYLOAD, "uncommittable.pdf")
        self.assertNotIn(FAULT_DETAIL, str(caught.exception))
        receipt_id, = await self.all_ids()
        self.assertEqual((await self.record(receipt_id)).response.status, "processing")
        recovered = await self.service.get_receipt(receipt_id)
        record = await self.assert_failed(recovered)
        self.assertEqual(record.metadata.failure_code, "interrupted_processing")
        self.assertTrue(record.metadata.recovery_reason.strip())
        self.assertEqual(await self.service.process_receipt(PAYLOAD, "no-retry.pdf"), recovered)
        self.assertEqual(len(self.calls), 1)

    async def test_reservation_failure_raises_sanitized_storage_error(self):
        with patch.object(repository, "claim_receipt", side_effect=OSError(FAULT_DETAIL)):
            with self.assertRaises(ReceiptStorageError) as caught:
                await self.service.process_receipt(PAYLOAD, "claim-failure.pdf")
        self.assertNotIn(FAULT_DETAIL, str(caught.exception))
        self.assertEqual(self.calls, [])

    async def test_unresolved_owner_is_error_without_extraction(self):
        await self.service.start()
        await asyncio.to_thread(repository.claim_receipt, str(uuid4()),
                                hashlib.sha256(PAYLOAD).hexdigest(), db_path=self.db)
        with self.assertRaises(ReceiptStorageError):
            await self.service.process_receipt(PAYLOAD, "unresolved.pdf")
        self.assertEqual(self.calls, [])

    async def test_normal_caller_cancellation_finishes_owned_work(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def gated(pdf_bytes, filename):
            nonlocal calls
            calls += 1
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
            return self.raw

        service = ReceiptService(self.root, extractor=gated)
        task = asyncio.create_task(service.process_receipt(PAYLOAD, "cancel.pdf"))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        duplicate = await service.process_receipt(PAYLOAD, "after-cancel.pdf")
        self.assertEqual(duplicate.status, "saved")
        self.assertEqual(calls, 1)
        self.assertEqual((await self.record(duplicate.receipt_id)).response, duplicate)


def recovery_case(original_state):
    async def test(self):
        initial = await self.seed_interruption(original_state)
        orphan_dir = self.root / "originals"
        orphan_dir.mkdir(exist_ok=True)
        orphan = orphan_dir / f"{uuid4()}.pdf"
        temporary = orphan_dir / ".independent-crash-left.tmp"
        orphan.write_bytes(b"Independent unreferenced bytes")
        temporary.write_bytes(b"Independent interrupted temporary bytes")
        value = await self.child("resume", initial.response.receipt_id)
        record = value["record"]
        response = value["response"]
        self.assertEqual(response["status"], "failed")
        self.assertFalse(response["validation"]["passed"])
        self.assertEqual(response["validation"]["issues"], [])
        self.assertEqual(response["receipt_id"], initial.response.receipt_id)
        self.assertEqual(record["pdf_sha256"], initial.pdf_sha256)
        self.assertEqual(record["created_at"], initial.created_at)
        self.assertEqual(record["metadata"]["failure_code"], "interrupted_processing")
        self.assertTrue(record["metadata"]["recovery_reason"].strip())
        expected_ref = f"originals/{initial.response.receipt_id}.pdf" if original_state in {"matching", "attached"} else None
        self.assertEqual(record["original_pdf_ref"], expected_ref)
        self.assertEqual(response["sync"]["status"], "skipped")
        self.assertEqual(response["notification"]["status"], "not_sent")
        self.assertEqual(orphan.read_bytes(), b"Independent unreferenced bytes")
        self.assertEqual(temporary.read_bytes(), b"Independent interrupted temporary bytes")
        again = await self.child("resume", initial.response.receipt_id)
        self.assertEqual(again["record"], record)
    return test


for _state in ("absent", "matching", "attached", "corrupt"):
    setattr(WorkflowContract, f"test_fresh_process_recovery_{_state}", recovery_case(_state))


class SequentialRestartContract(unittest.TestCase):
    def test_saved_survives_fully_closed_loop_and_fresh_interpreter(self):
        with tempfile.TemporaryDirectory(prefix="receipt-independent-restart-") as directory:
            root = Path(directory)

            async def first_process():
                async def substitute(pdf_bytes, filename):
                    return complete(discount="-6.40")
                service = ReceiptService(root, extractor=substitute)
                response = await service.process_receipt(PAYLOAD, "before-restart.pdf")
                record = await asyncio.to_thread(repository.get_record, response.receipt_id,
                                                db_path=root / "receipts.sqlite3")
                return response, record

            response, record = asyncio.run(first_process())
            self.assertEqual(response.status, "saved")
            command = [sys.executable, "-B", str(HERE / "run.py"), "--worker", "query",
                       directory, response.receipt_id, PAYLOAD.hex()]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            restarted = json.loads(result.stdout)
            self.assertEqual(restarted["record"], record.model_dump(mode="json"))
            self.assertEqual(restarted["response"], response.model_dump(mode="json"))
            self.assertEqual(restarted["extractor_calls"], 0)
            self.assertEqual(restarted["guard_violations"], [])
            self.assertEqual((root / record.original_pdf_ref).read_bytes(), PAYLOAD)
            command[4] = "resume"
            duplicate = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
            repeated = json.loads(duplicate.stdout)
            self.assertEqual(repeated["response"], response.model_dump(mode="json"))
            self.assertEqual(repeated["extractor_calls"], 0)
            self.assertEqual(repeated["guard_violations"], [])
