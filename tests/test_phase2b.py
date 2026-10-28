"""Offline checks for one-attempt execution, answer isolation, and Decimal comparison."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.receipt import ReceiptData
from scripts import phase2b_extract
from scripts.phase2b_compare import decimal_comparison


def test_decimal_formatting_is_separate_from_amount_errors():
    result = decimal_comparison({"total": "1.2", "tax": "0.10", "items": [{"quantity": "2.0"}]},
                                {"total": "1.20", "tax": "0.11", "items": [{"quantity": "2"}]})
    assert {field["field"] for field in result["format_only_differences"]} == {"data.total", "data.items[0].quantity"}
    assert {field["field"] for field in result["amount_errors"]} == {"data.tax"}
    assert len(result["value_differences"]) == 1
    assert result["exact_difference_count"] == 3


def test_unknown_currency_and_missing_fields_are_not_normalized():
    result = decimal_comparison({"currency": "USD", "tax": None}, {"currency": None, "tip": None})
    assert {field["field"] for field in result["value_differences"]} == {"data.currency", "data.tax", "data.tip"}
    assert not result["format_only_differences"]


def test_case_saves_evidence_without_reading_answers(monkeypatch, tmp_path):
    monkeypatch.setattr(phase2b_extract, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("MODEL_NAME", "synthetic-model")
    pdf_dir = tmp_path / "tests/fixtures/development/pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "B.pdf").write_bytes(b"%PDF-synthetic")
    run_dir = tmp_path / "data/phase2b/test"
    run_dir.mkdir(parents=True)
    response = SimpleNamespace(id="synthetic-response", status="completed", usage=None,
                               output_text=ReceiptData(total="1.20").model_dump_json())
    request = AsyncMock(return_value=response)
    monkeypatch.setattr(phase2b_extract, "request_extraction", request)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert "expected" not in path.parts
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = asyncio.run(phase2b_extract.extract_case("B", run_dir))
    assert result["outcome"] == "succeeded"
    assert result["expected_read"] is False
    assert result["max_retries"] == 0
    actual = run_dir / "B/actual.json"
    assert result["output_sha256"] == hashlib.sha256(actual.read_bytes()).hexdigest()
    assert (run_dir / "B/raw_output.txt").is_file()
    assert (run_dir / "B/extraction_metadata.json").is_file()
    request.assert_awaited_once_with(b"%PDF-synthetic", "B.pdf")
    with pytest.raises(FileExistsError):
        asyncio.run(phase2b_extract.extract_case("B", run_dir))
    request.assert_awaited_once()


@pytest.mark.parametrize("code,status", [("invalid_api_key", 401), ("insufficient_quota", 429), ("permission_denied", 403)])
def test_failure_stops_later_cases_without_probe_or_a(monkeypatch, tmp_path, code, status):
    monkeypatch.setattr(phase2b_extract, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(phase2b_extract, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(phase2b_extract, "sha256", lambda path: "synthetic-hash")
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key")
    monkeypatch.setenv("MODEL_NAME", "synthetic-model")
    extract_case = AsyncMock(return_value={"case_id": "B", "outcome": "failed", "error": {"code": code, "http_status": status}})
    monkeypatch.setattr(phase2b_extract, "extract_case", extract_case)
    assert asyncio.run(phase2b_extract.run()) is False
    extract_case.assert_awaited_once()
    assert extract_case.call_args.args[0] == "B"
    path = next((tmp_path / "data/phase2b").glob("*/extraction_summary.json"))
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["not_attempted"] == ["C", "D", "F"]
    assert summary["text_probe_executed"] is False
    assert summary["a_requested"] is False
