"""Offline tests for stopping rules and exact comparison; no fixture reads."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import phase2_extract_a, phase2_probe
from scripts.phase2_compare_a import compare_fields


def test_failed_probe_records_safe_error_and_sends_one_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key-do-not-log")
    monkeypatch.setenv("MODEL_NAME", "configured-model")
    create = AsyncMock(side_effect=RuntimeError("synthetic-key-do-not-log"))
    manager = AsyncMock()
    manager.__aenter__.return_value = SimpleNamespace(responses=SimpleNamespace(create=create))
    captured = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        return manager

    monkeypatch.setattr(phase2_probe, "AsyncOpenAI", make_client)
    monkeypatch.setattr(phase2_probe, "PROJECT_ROOT", tmp_path)
    assert asyncio.run(phase2_probe.probe(tmp_path)) is False
    create.assert_awaited_once()
    assert captured["max_retries"] == 0
    artifact = (tmp_path / "text_probe.json").read_text(encoding="utf-8")
    assert "synthetic-key-do-not-log" not in artifact
    result = json.loads(artifact)
    assert result["pdf_attempted"] is False
    assert result["expected_read"] is False
    assert result["usage"] is None


def test_failed_probe_prevents_pdf_request(monkeypatch, tmp_path):
    monkeypatch.setattr(phase2_extract_a, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(phase2_extract_a, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MODEL_NAME", "configured-model")
    request = AsyncMock()
    monkeypatch.setattr(phase2_extract_a, "request_extraction", request)
    run_dir = tmp_path / "data" / "phase2" / "synthetic"
    run_dir.mkdir(parents=True)
    (run_dir / "text_probe.json").write_text(json.dumps({"outcome": "failed", "model": "configured-model"}))
    with pytest.raises(ValueError, match="successful text probe"):
        asyncio.run(phase2_extract_a.run(run_dir))
    request.assert_not_awaited()
    assert not (run_dir / "pdf_attempt.json").exists()


def test_comparison_distinguishes_missing_null_decimal_strings_and_item_count():
    fields = compare_fields({"total": "1.2", "items": [], "tax": None},
                            {"total": "1.20", "items": [{"amount": "1.20"}], "tip": None})
    differences = {field["field"] for field in fields if not field["matched"]}
    assert differences == {"data.total", "data.items.length", "data.items[0]", "data.tax", "data.tip"}
