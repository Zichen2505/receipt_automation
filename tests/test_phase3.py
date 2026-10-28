"""Offline workflow tests using prior real outputs only as injected test substitutes."""
import asyncio
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.contracts import ReceiptStorageError
from app.integrations.extractor import normalize_receipt_data, parse_extraction_with_metadata
from app.schemas.receipt import ReceiptData
from app.services.receipt_service import ReceiptService
from app.services.validation import validate_receipt
from app.storage import files, repository

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/development"
HISTORY_A = ROOT / "data/phase2/20261023T222741Z_0d6db5ab"
HISTORY_BCDF = ROOT / "data/phase2b/20261023T224454Z_695f2d59"


def historical_raw(case):
    directory = HISTORY_A if case == "A" else HISTORY_BCDF / case
    return (directory / "raw_output.txt").read_text(encoding="utf-8")


def synthetic(**overrides):
    values = dict(merchant="Synthetic", date="2026-10-24", currency="USD", total="10.00",
                  subtotal="10.00", tax="0.00", tip="0.00", discount="0.00",
                  items=[dict(description="Item", quantity="2", unit_price="5.00", amount="10.00")])
    values.update(overrides)
    return ReceiptData.model_validate(values)


@pytest.mark.parametrize("discount", ["7.10", "-7.10", "0", "-0.00", None])
def test_discount_normalization_is_audited_and_idempotent(discount):
    original = synthetic(discount=discount, tax="-1.00", total="-2.00")
    data, events = normalize_receipt_data(original)
    again, _ = normalize_receipt_data(data)
    assert data == again
    assert data.discount == (None if discount is None else Decimal(discount).copy_abs())
    assert events[0].original_value == original.discount
    assert events[0].normalized_value == data.discount
    assert events[0].reason
    assert data.tax == original.tax == Decimal("-1.00")
    assert data.total == original.total == Decimal("-2.00")
    assert original.discount == (None if discount is None else Decimal(discount))


def test_real_d_adaptation_preserves_other_fields_and_raw_evidence():
    raw = historical_raw("D")
    response = SimpleNamespace(status="completed", output_text=raw)
    data, metadata = parse_extraction_with_metadata(response)
    original = ReceiptData.model_validate_json(raw)
    assert data.discount == Decimal("7.10")
    assert data.model_dump(exclude={"discount"}) == original.model_dump(exclude={"discount"})
    assert metadata.raw_output == raw
    assert metadata.normalizations[0].original_value == Decimal("-7.10")
    assert metadata.normalizations[0].reason == "negative_discount_converted_to_positive_magnitude"
    assert parse_extraction_with_metadata(response) == (data, metadata)


@pytest.mark.parametrize("field", ["merchant", "date", "currency", "total"])
def test_missing_required_fields_have_specific_codes(field):
    result = validate_receipt(synthetic(**{field: None}))
    assert not result.passed
    assert "missing_" + field in {issue.code for issue in result.issues}


@pytest.mark.parametrize("overrides,code", [
    ({"items": [{"quantity": "2", "unit_price": "4.00", "amount": "10.00"}]}, "item_amount_mismatch"),
    ({"subtotal": "11.00", "total": "11.00"}, "subtotal_mismatch"),
    ({"total": "10.01"}, "total_mismatch"),
    ({"tax": "0.001"}, "invalid_amount_precision"),
])
def test_exact_amount_conflicts_are_rejected(overrides, code):
    data = synthetic(**overrides)
    before = data.model_dump_json()
    assert code in {issue.code for issue in validate_receipt(data).issues}
    assert data.model_dump_json() == before


def test_decimal_exactness_and_unknown_formula_components():
    assert validate_receipt(synthetic(subtotal="0.10", tax="0.20", total="0.30", items=None)).passed
    data = synthetic(subtotal=None, discount=None, tip=None, tax=None, total="999.99",
                     items=[{"quantity": None, "unit_price": "1.00", "amount": "20.00"}])
    assert validate_receipt(data).passed
    assert data.discount is None


def test_real_output_workflow_all_five_and_process_restart(tmp_path):
    pdfs = {case: (FIXTURES / "pdfs" / f"{case}.pdf").read_bytes() for case in "ABCDF"}
    by_hash = {hashlib.sha256(value).hexdigest(): case for case, value in pdfs.items()}
    calls = []

    async def substitute(pdf, filename):
        case = by_hash[hashlib.sha256(pdf).hexdigest()]
        calls.append(case)
        return ReceiptData.model_validate_json(historical_raw(case))

    async def scenario():
        service = ReceiptService(tmp_path, extractor=substitute)
        responses = {}
        for case in "ABCDF":
            response = await service.process_receipt(pdfs[case], "../../untrusted.pdf")
            assert response.status == ("needs_review" if case == "F" else "saved")
            expected = json.loads((FIXTURES / "expected" / f"{case}.json").read_text(encoding="utf-8"))
            assert response.data.model_dump(mode="json") == expected["data"]
            if case == "F":
                assert [issue.code for issue in response.validation.issues] == ["missing_currency"]
            assert response.sync.status == "skipped"
            assert response.notification.status == "not_sent"
            record = repository.get_record(response.receipt_id, db_path=service.db_path)
            assert record.pdf_sha256 == hashlib.sha256(pdfs[case]).hexdigest()
            assert (tmp_path / record.original_pdf_ref).read_bytes() == pdfs[case]
            assert record.metadata.extraction.raw_output
            if case == "D":
                assert record.metadata.extraction.normalizations[0].original_value == Decimal("-7.10")
            responses[case] = response
        assert len({response.receipt_id for response in responses.values()}) == 5
        another = ReceiptService(tmp_path, extractor=substitute)
        assert await another.process_receipt(pdfs["D"], "renamed.pdf") == responses["D"]
        assert await another.get_receipt(responses["A"].receipt_id) == responses["A"]
        assert await another.get_receipt("not-present") is None
        return responses

    responses = asyncio.run(scenario())
    assert calls == list("ABCDF")
    # A new interpreter initializes storage and reads the same persisted record, without a model call.
    code = ("import asyncio,sys; from pathlib import Path; "
            "from app.services.receipt_service import ReceiptService; "
            "r=asyncio.run(ReceiptService(Path(sys.argv[1])).get_receipt(sys.argv[2])); print(r.model_dump_json())")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path), responses["D"].receipt_id],
                            capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(result.stdout) == responses["D"].model_dump(mode="json")
    assert all(path.read_bytes() in pdfs.values() for path in (tmp_path / "originals").glob("*.pdf"))


def test_concurrent_duplicates_across_instances_call_model_once(tmp_path):
    calls = []

    async def substitute(pdf, filename):
        calls.append(filename)
        await asyncio.sleep(0.02)
        return synthetic()

    async def scenario():
        instances = [ReceiptService(tmp_path, extractor=substitute) for _ in range(3)]
        results = await asyncio.gather(*(instances[i % 3].process_receipt(b"%PDF-synthetic", str(i)) for i in range(20)))
        assert all(response.status == "saved" for response in results)
        assert len({response.receipt_id for response in results}) == 1
        record = repository.get_record(results[0].receipt_id, db_path=instances[0].db_path)
        with pytest.raises(ReceiptStorageError, match="overwrite"):
            repository.save_receipt(results[0], db_path=instances[0].db_path,
                                    original_pdf_ref=record.original_pdf_ref, metadata=record.metadata)

    asyncio.run(scenario())
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "receipts.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


def test_database_unique_hash_constraint_under_thread_contention(tmp_path):
    path = tmp_path / "receipts.sqlite3"
    repository.initialize_database(db_path=path, data_dir=tmp_path)

    async def scenario():
        results = await asyncio.gather(*(asyncio.to_thread(repository.claim_receipt, str(uuid4()), "a" * 64, db_path=path) for _ in range(12)))
        assert sum(owner for record, owner in results) == 1
        assert len({record.response.receipt_id for record, owner in results}) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("with_original", [False, True])
def test_startup_recovers_interrupted_processing_without_model_retry(tmp_path, with_original):
    pdf = b"%PDF-crash"
    path = tmp_path / "receipts.sqlite3"
    repository.initialize_database(db_path=path, data_dir=tmp_path)
    record, _ = repository.claim_receipt(str(uuid4()), hashlib.sha256(pdf).hexdigest(), db_path=path)
    if with_original:
        files.save_original_pdf(pdf, record.response.receipt_id, data_dir=tmp_path)
        # Simulate a crash between atomic PDF replacement and attaching its DB reference.

    async def forbidden(*args):
        pytest.fail("Recovery must not call a model")

    async def scenario():
        service = ReceiptService(tmp_path, extractor=forbidden)
        await service.start()
        result = await service.process_receipt(pdf, "ignored.pdf")
        assert result.receipt_id == record.response.receipt_id
        assert result.status == "failed"
        recovered = repository.get_record(result.receipt_id, db_path=path)
        assert recovered.metadata.failure_code == "interrupted_processing"
        assert recovered.metadata.recovery_reason
        assert bool(recovered.original_pdf_ref) is with_original

    asyncio.run(scenario())


def test_model_failure_is_durable_failed_without_retry(tmp_path):
    calls = []

    async def broken(*args):
        calls.append(1)
        raise RuntimeError("synthetic-secret-must-not-be-recorded")

    async def scenario():
        service = ReceiptService(tmp_path, extractor=broken)
        result = await service.process_receipt(b"%PDF-broken", "test.pdf")
        assert result.status == "failed" and not result.validation.passed
        assert await service.process_receipt(b"%PDF-broken", "again.pdf") == result
        record = repository.get_record(result.receipt_id, db_path=service.db_path)
        assert record.metadata.failure_code == "extraction_failed"
        assert "synthetic-secret" not in record.model_dump_json()

    asyncio.run(scenario())
    assert len(calls) == 1


def test_original_save_failure_does_not_call_extractor(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("synthetic disk failure")

    async def forbidden(*args):
        pytest.fail("Model called after original save failure")

    monkeypatch.setattr(files, "save_original_pdf", broken)

    async def scenario():
        result = await ReceiptService(tmp_path, extractor=forbidden).process_receipt(b"%PDF-test", "x.pdf")
        assert result.status == "failed" and not result.validation.passed

    asyncio.run(scenario())


def test_final_storage_failure_never_returns_success(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic commit failure")

    async def substitute(*args):
        return synthetic()

    monkeypatch.setattr(repository, "save_receipt", broken)
    with pytest.raises(ReceiptStorageError, match="could not be committed"):
        asyncio.run(ReceiptService(tmp_path, extractor=substitute).process_receipt(b"%PDF-test", "x.pdf"))
    # A later startup can recover the reserved record after the failing operation is restored.
    monkeypatch.undo()
    async def query_after_restart():
        service = ReceiptService(tmp_path, extractor=substitute)
        await service.start()
        result = await service.process_receipt(b"%PDF-test", "x.pdf")
        assert result.status == "failed"
    asyncio.run(query_after_restart())


def test_synthetic_total_conflict_becomes_needs_review(tmp_path):
    async def substitute(*args):
        return synthetic(total="10.01")

    result = asyncio.run(ReceiptService(tmp_path, extractor=substitute).process_receipt(b"%PDF-conflict", "x.pdf"))
    assert result.status == "needs_review"
    assert result.data.total == Decimal("10.01")
    assert "total_mismatch" in {issue.code for issue in result.validation.issues}


def test_caller_cancellation_does_not_release_model_ownership(tmp_path):
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def substitute(*args):
            calls.append(1)
            started.set()
            await finish.wait()
            return synthetic()
        service = ReceiptService(tmp_path, extractor=substitute)
        task = asyncio.create_task(service.process_receipt(b"%PDF-cancel", "x.pdf"))
        await started.wait()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await service.process_receipt(b"%PDF-cancel", "again.pdf")
        assert result.status == "saved" and len(calls) == 1
    asyncio.run(scenario())


def test_atomic_original_paths_and_no_overwrite(tmp_path):
    identifier = str(uuid4())
    reference = files.save_original_pdf(b"%PDF-one", identifier, data_dir=tmp_path)
    assert (tmp_path / reference).read_bytes() == b"%PDF-one"
    assert not list((tmp_path / "originals").glob("*.tmp"))
    with pytest.raises(FileExistsError):
        files.save_original_pdf(b"%PDF-two", identifier, data_dir=tmp_path)
    with pytest.raises(ValueError):
        files.save_original_pdf(b"%PDF-one", "../../escape", data_dir=tmp_path)


def test_atomic_replace_failure_cleans_only_its_temporary_file(tmp_path, monkeypatch):
    identifier = str(uuid4())
    def broken(*args):
        raise OSError("synthetic replace failure")
    monkeypatch.setattr(files.os, "replace", broken)
    with pytest.raises(OSError):
        files.save_original_pdf(b"%PDF-one", identifier, data_dir=tmp_path)
    assert not list((tmp_path / "originals").iterdir())


def test_default_service_uses_metadata_adapter_without_network(tmp_path, monkeypatch):
    from app.integrations import extractor
    async def fake_request(*args):
        return SimpleNamespace(status="completed", output_text=historical_raw("D"))
    monkeypatch.setattr(extractor, "request_extraction", fake_request)
    async def scenario():
        service = ReceiptService(tmp_path)
        response = await service.process_receipt((FIXTURES / "pdfs/D.pdf").read_bytes(), "D.pdf")
        assert response.status == "saved"
        record = repository.get_record(response.receipt_id, db_path=service.db_path)
        assert record.metadata.extraction.normalizations[0].original_value == Decimal("-7.10")
        assert record.metadata.extraction.normalizations[0].normalized_value == Decimal("7.10")
        assert record.metadata.extraction.elapsed_seconds is not None
    asyncio.run(scenario())


def test_one_commit_failure_can_record_durable_failed(tmp_path, monkeypatch):
    original = repository.save_receipt
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("synthetic first commit failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "save_receipt", fail_once)
    async def substitute(*args):
        return synthetic()
    async def scenario():
        service = ReceiptService(tmp_path, extractor=substitute)
        response = await service.process_receipt(b"%PDF-commit", "x.pdf")
        assert response.status == "failed" and not response.validation.passed
        assert (await service.get_receipt(response.receipt_id)).status == "failed"
        assert repository.get_record(response.receipt_id, db_path=service.db_path).metadata.failure_code == "result_save_failed"
    asyncio.run(scenario())


def test_failure_commit_recovery_on_same_event_loop(tmp_path, monkeypatch):
    original = repository.save_receipt
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic commit failure")
    async def substitute(*args):
        return synthetic()
    async def scenario():
        service = ReceiptService(tmp_path, extractor=substitute)
        monkeypatch.setattr(repository, "save_receipt", broken)
        with pytest.raises(ReceiptStorageError):
            await service.process_receipt(b"%PDF-same-loop-failure", "x.pdf")
        monkeypatch.setattr(repository, "save_receipt", original)
        response = await service.process_receipt(b"%PDF-same-loop-failure", "again.pdf")
        assert response.status == "failed"
        assert repository.get_record(response.receipt_id, db_path=service.db_path).metadata.failure_code == "interrupted_processing"
    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["merchant", "currency"])
def test_blank_required_text_is_missing(field):
    assert "missing_" + field in {issue.code for issue in validate_receipt(synthetic(**{field: "  "})).issues}
