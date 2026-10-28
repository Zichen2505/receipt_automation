"""Explicit offline Docker verification; never copied into the production image.

Only the supplied development A.pdf is admitted. Containers have no network;
HTTP checks run inside them over loopback. No host credentials are forwarded.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
KEY = "offline-docker-verification-key"
RECORD_ID = "recOfflineDocker"


def offline_app():
    """Inject only through the existing service dependency, outside app/."""
    import asyncio
    import httpx
    import openai
    from app.integrations import extractor as model_extractor
    from app.dependencies import get_receipt_service
    from app.integrations.airtable import AirtableClient
    from app.main import app
    from app.schemas.receipt import ReceiptData
    from app.services.receipt_service import ReceiptService

    def reject(*args, **kwargs):
        raise RuntimeError("Real model construction is forbidden in Docker acceptance")

    openai.OpenAI = openai.AsyncOpenAI = reject
    model_extractor.AsyncOpenAI = reject
    data_dir = Path(os.environ["DATA_DIR"])

    def event(value):
        with (data_dir / "offline-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value) + "\n")

    async def extract(content, filename):
        await asyncio.to_thread(event, "synthetic_extraction")
        return ReceiptData(
            merchant="Synthetic Docker Store", date="2026-10-28", currency="USD",
            total="12.30", items=[dict(description="Synthetic item", quantity="2",
                                       unit_price="6.15", amount="12.30")])

    def transport(request):
        event("simulated_airtable_" + request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"records": []})
        assert request.method == "POST"
        fields = json.loads(request.content)["records"][0]["fields"]
        return httpx.Response(200, json={"records": [{"id": RECORD_ID, "fields": fields}]})

    service = ReceiptService(data_dir, extractor=extract, airtable=AirtableClient(
        token="offline-only-token", base_id="appOfflineDocker", table_id="tblOfflineDocker",
        transport=httpx.MockTransport(transport)))
    app.dependency_overrides[get_receipt_service] = lambda: service
    return app


def check_inside(phase):
    import hashlib
    import sqlite3
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    base = "http://127.0.0.1:" + os.environ["PORT"]
    directory = Path(os.environ["DATA_DIR"])

    def request(path, body=None, headers=None):
        try:
            with urlopen(Request(base + path, data=body, headers=headers or {}), timeout=10) as response:
                return response.status, response.read()
        except HTTPError as response:
            with response:
                return response.code, response.read()

    assert os.getuid() == 10001
    for path, marker in (("/", b'upload-form'), ("/web/upload.js", b'/api/v1/receipts'),
                         ("/web/style.css", b'focus-visible'), ("/health", b'"ok"')):
        code, body = request(path)
        assert code == 200 and marker in body, path
        assert KEY.encode() not in body
    headers = {"X-API-Key": KEY}
    for endpoint in ("/api/v1/receipts/missing", "/api/v1/receipts"):
        body = b"" if endpoint.endswith("receipts") else None
        assert request(endpoint, body)[0] == 401
        assert request(endpoint, body, {"X-API-Key": "wrong"})[0] == 401
    assert request("/api/v1/receipts/missing", headers=headers)[0] == 404
    assert request("/api/v1/receipts/missing/export?format=json", headers=headers)[0] == 501
    probe = directory / "verification-write-probe"
    probe.write_bytes(b"isolated-volume-write")
    assert probe.read_bytes() == b"isolated-volume-write"
    probe.unlink()
    assert (directory / "receipts.sqlite3").is_file()
    if phase == "production":
        assert not (directory / "offline-events.jsonl").exists()
        assert not Path("/app/.env").exists()
        assert not Path("/app/scripts").exists()
        assert not Path("/app/tests").exists()
        return

    pdf = Path("/verification/A.pdf").read_bytes()
    boundary = "receipt-offline-docker-boundary"
    upload = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="A.pdf"'
              '\r\nContent-Type: application/pdf\r\n\r\n').encode() + pdf + f'\r\n--{boundary}--\r\n'.encode()
    upload_headers = {**headers, "Content-Type": "multipart/form-data; boundary=" + boundary}
    expected_path = directory / "offline-response.json"
    if phase == "restart":
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        assert json.loads(request("/api/v1/receipts/" + expected["receipt_id"], headers=headers)[1]) == expected
    code, body = request("/api/v1/receipts", upload, upload_headers)
    assert code == 200
    result = json.loads(body)
    assert result["status"] == "saved" and result["validation"]["passed"] is True
    assert result["sync"] == {"status": "synced", "record_id": RECORD_ID}
    assert result["data"]["merchant"] == "Synthetic Docker Store"
    assert result["data"]["total"] == "12.30"
    if phase == "restart":
        assert result == expected
    else:
        with expected_path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream)
    assert request("/api/v1/receipts", upload, upload_headers) == (code, body)
    assert json.loads(request("/api/v1/receipts/" + result["receipt_id"], headers=headers)[1]) == result
    events = (directory / "offline-events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in events] == [
        "synthetic_extraction", "simulated_airtable_GET", "simulated_airtable_POST"]
    connection = sqlite3.connect(directory / "receipts.sqlite3")
    try:
        rows = connection.execute("SELECT pdf_sha256, original_pdf_ref, response_json, metadata_json FROM receipts").fetchall()
    finally:
        connection.close()
    assert len(rows) == 1
    digest, reference, stored, metadata = rows[0]
    assert digest == hashlib.sha256(pdf).hexdigest()
    assert (directory / reference).read_bytes() == pdf
    assert json.loads(stored) == result
    assert json.loads(metadata)["extraction"]["raw_output"]


def run_host():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    evidence = ROOT / "data/docker" / run_id
    evidence.mkdir(parents=True)
    store = evidence / "store"
    store.mkdir()
    name = "receipt-offline-" + uuid4().hex[:12]
    image = name + ":verification"
    active = False
    stages = []

    def docker(*args, capture=False, required=True):
        with (evidence / "console.txt").open("a", encoding="utf-8") as log:
            result = subprocess.run(["docker", *args], cwd=ROOT, stdout=subprocess.PIPE if capture else log,
                                    stderr=log, text=True)
        if required and result.returncode:
            raise RuntimeError("Docker command failed: " + args[0])
        return result

    status = "failed"
    error = None
    try:
        try:
            available = docker("info", "--format", "{{.OSType}}", capture=True, required=False)
        except FileNotFoundError:
            available = None
        if available is None or available.returncode:
            status = "not_run_docker_unavailable"
            return 2
        assert available.stdout.strip() == "linux", "Linux Docker Engine is required"
        docker("build", "--tag", image, ".")
        stages.append("image_build")
        print("Docker image built", flush=True)
        pdf = ROOT / "tests/fixtures/development/pdfs/A.pdf"
        if not pdf.is_file():
            raise RuntimeError("The supplied development A.pdf is required; no PDF is fabricated")
        mount = ["--mount", f"type=bind,source={store},target=/app/data"]
        # Ownership is changed only on this newly created isolated store.
        docker("run", "--rm", "--network", "none", "--user", "0:0", *mount, image,
               "python", "-c", "import os; os.chown('/app/data',10001,10001)")
        for phase in ("production", "simulated", "restart"):
            command = ["run", "--detach", "--name", name, "--network", "none", *mount,
                       "--mount", f"type=bind,source={Path(__file__).resolve()},target=/verification/docker_acceptance.py,readonly",
                       "--mount", f"type=bind,source={pdf},target=/verification/A.pdf,readonly",
                       "--env", "APP_API_KEY=" + KEY, "--env", "PORT=8765", "--env", "PYTHONPATH=/app", image]
            if phase == "simulated":
                command += ["python", "/verification/docker_acceptance.py", "--inside-server"]
            docker(*command)
            active = True
            deadline = time.monotonic() + 30
            while True:
                ready = docker("exec", name, "python", "-c",
                               "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=1).close()",
                               required=False)
                if ready.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Container readiness timed out")
                time.sleep(.2)
            docker("exec", name, "python", "/verification/docker_acceptance.py", "--inside-check", phase)
            docker("stop", "--time", "30", name)
            exit_code = docker("inspect", "--format", "{{.State.ExitCode}}", name, capture=True)
            assert exit_code.stdout.strip() == "0", "Container did not shut down gracefully"
            docker("rm", name)
            active = False
            stages.append(phase)
            print("Docker phase passed: " + phase, flush=True)
        status = "passed"
        return 0
    except Exception as exception:
        error = type(exception).__name__ + ": " + str(exception)
        return 1
    finally:
        if active:
            docker("stop", "--time", "30", name, required=False)
            docker("rm", name, required=False)
        record = {"status": status, "completed_stages": stages, "error": error,
                  "real_model_requests": 0, "real_airtable_requests": 0,
                  "evidence": evidence.relative_to(ROOT).as_posix()}
        (evidence / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside-server", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--inside-check", choices=("production", "simulated", "restart"), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.inside_server:
        import uvicorn
        uvicorn.run(offline_app(), host="0.0.0.0", port=int(os.environ["PORT"]), workers=1, access_log=False)
    elif arguments.inside_check:
        check_inside(arguments.inside_check)
    else:
        raise SystemExit(run_host())
