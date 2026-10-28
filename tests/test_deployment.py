"""Exercise the explicit Docker substitute and unavailable-engine reporting offline."""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_receipt_service
from app.main import app
from scripts import docker_acceptance


def test_docker_unavailable_does_not_report_acceptance(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(docker_acceptance, "ROOT", tmp_path)
    commands = []

    def unavailable(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(docker_acceptance.subprocess, "run", unavailable)
    assert docker_acceptance.run_host() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not_run_docker_unavailable"
    assert result["completed_stages"] == []
    assert len(commands) == 1 and commands[0][1] == "info"


def test_explicit_docker_substitute_persists_for_production_restart(monkeypatch, tmp_path):
    pdf_path = Path(__file__).resolve().parents[1] / "tests/fixtures/development/pdfs/A.pdf"
    if not pdf_path.is_file():
        pytest.skip("The supplied development A.pdf is absent; no replacement PDF is generated")
    pdf = pdf_path.read_bytes()
    import openai
    from app.integrations import extractor
    # Register restoration before the standalone verification helper installs guards.
    monkeypatch.setattr(openai, "OpenAI", openai.OpenAI)
    monkeypatch.setattr(openai, "AsyncOpenAI", openai.AsyncOpenAI)
    monkeypatch.setattr(extractor, "AsyncOpenAI", extractor.AsyncOpenAI)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_API_KEY", docker_acceptance.KEY)
    for name in ("MODEL_API_KEY", "MODEL_NAME", "AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID"):
        monkeypatch.delenv(name, raising=False)
    headers = {"X-API-Key": docker_acceptance.KEY}
    try:
        with TestClient(docker_acceptance.offline_app()) as client:
            first = client.post("/api/v1/receipts", headers=headers, files={"file": ("A.pdf", pdf, "application/pdf")})
            assert first.status_code == 200
            result = first.json()
            assert result["status"] == "saved" and result["validation"]["passed"]
            assert result["sync"] == {"status": "synced", "record_id": docker_acceptance.RECORD_ID}
            assert result["data"]["total"] == "12.30"
            assert client.get("/api/v1/receipts/" + result["receipt_id"], headers=headers).json() == result
        app.dependency_overrides.clear()
        with TestClient(app) as client:
            assert app.state.receipt_service.extractor is None
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/api/v1/receipts/" + result["receipt_id"], headers=headers).json() == result
            assert client.post("/api/v1/receipts", headers=headers,
                               files={"file": ("A.pdf", pdf, "application/pdf")}).json() == result
        events = [json.loads(line) for line in (tmp_path / "offline-events.jsonl").read_text().splitlines()]
        assert events == ["synthetic_extraction", "simulated_airtable_GET", "simulated_airtable_POST"]
        assert (tmp_path / "originals" / (result["receipt_id"] + ".pdf")).read_bytes() == pdf
    finally:
        app.dependency_overrides.pop(get_receipt_service, None)
