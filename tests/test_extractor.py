"""Offline SDK-boundary tests; no development answers or network access."""
import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.integrations import extractor
from app.schemas.receipt import ReceiptData


def test_strict_schema_comes_from_shared_models():
    schema = extractor.receipt_output_schema()
    assert set(schema["required"]) == set(ReceiptData.model_fields)
    assert schema["additionalProperties"] is False
    item = schema["$defs"]["ReceiptItem"]
    assert item["required"] == list(item["properties"])
    assert item["additionalProperties"] is False
    assert schema["properties"]["total"]["anyOf"][0]["type"] == "string"


def test_extract_uses_explicit_credentials_pdf_and_no_retries(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-model-key")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("MODEL_NAME", "configured-model")
    response = SimpleNamespace(status="completed", output_text=ReceiptData(total="1.20").model_dump_json())
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    manager = AsyncMock()
    manager.__aenter__.return_value = client
    captured = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        return manager

    monkeypatch.setattr(extractor, "AsyncOpenAI", make_client)
    data = asyncio.run(extractor.extract(b"%PDF-synthetic", "synthetic.pdf"))
    assert data.total == ReceiptData(total="1.20").total
    assert captured["api_key"] == "synthetic-model-key"
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 120.0
    create.assert_awaited_once()
    payload = create.call_args.kwargs
    assert payload["model"] == "configured-model"
    assert payload["store"] is False
    file_input = payload["input"][0]["content"][0]
    assert base64.b64decode(file_input["file_data"].split(",", 1)[1]) == b"%PDF-synthetic"


def test_missing_model_key_never_falls_back_to_openai_api_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("MODEL_NAME", "configured-model")
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        asyncio.run(extractor.extract(b"%PDF-synthetic", "synthetic.pdf"))


@pytest.mark.parametrize("status,text", [("incomplete", "{}"), ("completed", "")])
def test_incomplete_output_is_not_success(status, text):
    with pytest.raises(ValueError, match="did not complete"):
        extractor.parse_extraction(SimpleNamespace(status=status, output_text=text))


def test_invalid_model_data_rejected():
    with pytest.raises(ValidationError):
        extractor.parse_extraction(SimpleNamespace(status="completed", output_text='{"total":"NaN"}'))
