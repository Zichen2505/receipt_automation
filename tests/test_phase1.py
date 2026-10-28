"""Phase 1 checks using synthetic contracts and unchanged development fixtures."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.integrations.airtable import map_receipt_fields
from app.main import app
from app.schemas.receipt import (
    NotificationResult, ReceiptData, ReceiptResponse, SyncResult, ValidationResult,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", "phase1-test-only-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        yield client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("key", [None, "wrong-key", "\u9519\u8bef\u5bc6\u94a5"])
@pytest.mark.parametrize("method,path", [
    ("post", "/api/v1/receipts"),
    ("get", "/api/v1/receipts/missing"),
    ("get", "/api/v1/receipts/missing/export?format=json"),
])
def test_authentication(client, key, method, path):
    # Non-ASCII headers require raw bytes in HTTP clients.
    headers = {} if key is None else {b"X-API-Key": key.encode("utf-8")}
    kwargs = {"files": {"file": ("synthetic.pdf", b"%PDF-contract-only")}} if method == "post" else {}
    response = client.request(method, path, headers=headers, **kwargs)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/receipts/missing/export?format=json"),
    ("get", "/api/v1/receipts/missing/export?format=csv"),
])
def test_authenticated_stubs(client, method, path):
    kwargs = {"files": {"file": ("synthetic.pdf", b"%PDF-contract-only")}} if method == "post" else {}
    response = client.request(method, path, headers={"X-API-Key": "phase1-test-only-key"}, **kwargs)
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "not_implemented"


def test_parameters(client):
    headers = {"X-API-Key": "phase1-test-only-key"}
    assert client.post("/api/v1/receipts", headers=headers).status_code == 422
    assert client.get("/api/v1/receipts/id/export?format=xml", headers=headers).status_code == 422


def synthetic_receipt():
    return ReceiptResponse(
        receipt_id="synthetic-backend-id", status="saved",
        data=ReceiptData(merchant="Synthetic Merchant", date="2026-10-23", receipt_number="merchant-123",
                         currency="USD", total="12.30", tax="0.30",
                         items=[{"description": "Synthetic item", "quantity": "2", "unit_price": "6.00", "amount": "12.00"}]),
        validation=ValidationResult(passed=True, issues=[]),
        sync=SyncResult(status="not_configured"),
        notification=NotificationResult(status="not_sent"),
    )


def test_schema_and_airtable_contract():
    receipt = synthetic_receipt()
    assert isinstance(receipt.data.total, Decimal)
    serialized = json.loads(receipt.model_dump_json())
    assert serialized["data"]["total"] == "12.30"
    assert serialized["data"]["date"] == "2026-10-23"
    assert serialized["data"]["subtotal"] is None
    assert ReceiptResponse.model_validate_json(receipt.model_dump_json()) == receipt
    fields = map_receipt_fields(receipt)
    assert set(fields) == {"Vendor", "Date", "Amount", "Currency", "RawJSON", "ReceiptID"}
    assert fields["Vendor"] == "Synthetic Merchant"
    assert fields["Date"] == "2026-10-23"
    assert fields["Amount"] == 12.3 and isinstance(fields["Amount"], float)
    assert fields["Currency"] == "USD"
    assert fields["ReceiptID"] == "synthetic-backend-id"
    assert json.loads(fields["RawJSON"]) == serialized["data"]
    assert json.loads(fields["RawJSON"])["items"][0]["amount"] == "12.00"
    receipt.data.total = None
    assert map_receipt_fields(receipt)["Amount"] is None
    for status, passed in [("needs_review", False), ("processing", True), ("failed", True), ("saved", False)]:
        receipt.status = status
        receipt.validation.passed = passed
        with pytest.raises(ValueError):
            map_receipt_fields(receipt)


def test_unknown_values_and_invalid_amounts():
    assert all(value is None for value in ReceiptData().model_dump().values())
    for amount in ["NaN", "Infinity", "-Infinity"]:
        with pytest.raises(ValidationError):
            ReceiptData(total=amount)


def test_import_without_config_and_startup_rejection(monkeypatch, tmp_path):
    env = dict(os.environ)
    env.pop("APP_API_KEY", None)
    result = subprocess.run([sys.executable, "-c", "import app.main"], env=env, capture_output=True, timeout=10)
    assert result.returncode == 0
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="APP_API_KEY"):
        with TestClient(app):
            pass


def test_real_uvicorn_startup(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, APP_API_KEY="phase1-process-test-key", DATA_DIR=str(tmp_path), PORT=str(port))
    process = subprocess.Popen([sys.executable, "-m", "app.main"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail("Uvicorn exited before startup")
                try:
                    response = client.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
                    assert response.status_code == 200
                    break
                except httpx.TransportError:
                    time.sleep(0.05)
            else:
                pytest.fail("Uvicorn startup timed out")
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_development_schema_compatibility():
    folder = Path(__file__).parent / "fixtures" / "development"
    # Read only the authorized development directories; preserve all fixture bytes.
    samples = sorted((folder / "expected").glob("*.json"))
    if not samples:
        pytest.skip("Development expected JSON is missing; fixture compatibility is unverified")
    pdfs = {path.name for path in (folder / "pdfs").glob("*.pdf")}
    referenced_pdfs = set()
    for sample in samples:
        content = json.loads(sample.read_text(encoding="utf-8-sig"))
        assert set(content) == {"case_id", "expected_status", "expected_issue_codes", "data", "pdf_file", "page_count"}
        data = ReceiptData.model_validate(content["data"])
        assert data.model_dump(mode="json") == content["data"]
        assert content["case_id"] == sample.stem
        assert content["pdf_file"] == sample.stem + ".pdf"
        assert content["pdf_file"] in pdfs
        assert content["expected_status"] in {"processing", "saved", "needs_review", "failed"}
        assert isinstance(content["expected_issue_codes"], list)
        assert all(isinstance(code, str) for code in content["expected_issue_codes"])
        referenced_pdfs.add(content["pdf_file"])
    assert referenced_pdfs == pdfs
