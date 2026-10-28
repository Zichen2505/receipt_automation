"""Real Chromium interaction with simulated API states and injected integrations.

Only the supplied development A.pdf is selected; all returned receipt data is
explicitly synthetic. No expected answers, dotenv or external service is read.
"""

import json
import os
from pathlib import Path
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.dependencies import get_receipt_service
from app.integrations.airtable import AirtableClient
from app.main import app
from app.schemas.receipt import ReceiptData, ReceiptResponse, SyncResult, ValidationResult, NotificationResult
from app.services.receipt_service import ReceiptService


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tests/fixtures/development/pdfs/A.pdf"
KEY = "offline-browser-access-key"


def mock_response(status="saved", sync="synced"):
    return ReceiptResponse(
        receipt_id="00000000-0000-4000-8000-000000000123", status=status,
        data=ReceiptData(merchant="Synthetic Browser Shop", date="2026-10-28", currency="USD", total="12.30",
                         items=[{"description": "Synthetic line", "quantity": "2", "unit_price": "6.15", "amount": "12.30"}]),
        validation=ValidationResult(passed=status == "saved", issues=[]),
        sync=SyncResult(status=sync, record_id="recBrowserMock" if sync == "synced" else None),
        notification=NotificationResult(status="not_sent"),
    ).model_dump(mode="json")


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api", reason="Browser checks require the pinned development dependency")
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel=os.getenv("RECEIPT_BROWSER_CHANNEL", "chrome"), headless=True,
                                             args=["--disable-background-networking", "--disable-component-update"])
        except playwright.Error as error:
            if "not found" in str(error) or "doesn't exist" in str(error):
                pytest.skip("Installed Chrome/Chromium is unavailable; browser checks were not run")
            raise
        yield browser
        browser.close()


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "startup"))
    for name in ("MODEL_API_KEY", "MODEL_NAME", "AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID"):
        monkeypatch.delenv(name, raising=False)
    extracted, simulated_http = [], []

    async def extract(content, filename):
        extracted.append((content, filename))
        return ReceiptData.model_validate(mock_response()["data"])

    def transport(request):
        simulated_http.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"records": []})
        assert request.method == "POST"
        return httpx.Response(200, json={"records": [{"id": "recBrowserMock", "fields": json.loads(request.content)["records"][0]["fields"]}]})

    service = ReceiptService(tmp_path / "store", extractor=extract, airtable=AirtableClient(
        token="offline-only-token", base_id="appBrowserMock", table_id="tblBrowserMock", transport=httpx.MockTransport(transport)))
    app.dependency_overrides[get_receipt_service] = lambda: service
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    runner = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=runner.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not runner.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert runner.started, "Offline UI server did not start"
        yield base, extracted, simulated_http
    finally:
        runner.should_exit = True
        thread.join(timeout=10)
        listener.close()
        app.dependency_overrides.clear()
        assert not thread.is_alive(), "Offline UI server did not stop"


@pytest.fixture
def page(browser, server):
    base = server[0]
    context = browser.new_context(service_workers="block")
    context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
    page = context.new_page()
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.goto(base + "/")
    yield page
    context.close()
    assert failures == []


def select_pdf(page):
    if not PDF.is_file():
        pytest.skip("The user-provided development A.pdf is unavailable; no substitute PDF was fabricated")
    page.locator("#access-key").fill(KEY)
    with page.expect_file_chooser() as chooser:
        page.locator("#pdf-file").click()
    chooser.value.set_files(PDF)
    assert page.locator("#pdf-file").evaluate("element => element.files[0].name") == "A.pdf"


def submit(page):
    select_pdf(page)
    page.locator("#upload-button").click()
    page.locator("#upload-form[aria-busy='false']").wait_for()


def install_mock(page, body, status=200):
    requests = []

    def respond(route):
        requests.append(route.request)
        route.fulfill(status=status, json=body)

    page.route("**/api/v1/receipts", respond)
    return requests


def test_actual_file_selection_upload_and_render(page, server):
    requests = []
    page.on("request", lambda request: requests.append(request) if request.url.endswith("/api/v1/receipts") else None)
    submit(page)
    assert page.locator("#result").is_visible()
    assert page.locator("#local-status").inner_text() == "Saved locally · validation passed"
    assert page.locator("#sync-status").inner_text() == "Synced to Airtable"
    assert page.locator("#receipt-details").inner_text().find("Synthetic Browser Shop") >= 0
    assert "2026-10-28" in page.locator("#receipt-details").inner_text()
    assert "USD" in page.locator("#receipt-details").inner_text()
    assert "12.30" in page.locator("#receipt-details").inner_text()
    assert page.locator("#items tr").count() == 1
    assert page.locator("#items td").all_text_contents() == ["Synthetic line", "2", "6.15", "12.30"]
    assert server[1] == [(PDF.read_bytes(), "A.pdf")]
    assert server[2] == ["GET", "POST"]
    assert len(requests) == 1
    assert requests[0].headers["x-api-key"] == KEY
    assert KEY not in requests[0].url and KEY.encode() not in requests[0].post_data_buffer
    assert requests[0].headers["content-type"].startswith("multipart/form-data; boundary=")
    assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
    assert KEY not in page.content()
    assert page.locator("#error-area").is_hidden()
    evidence = os.getenv("RECEIPT_OFFLINE_AUDIT_LOG")
    if evidence:
        page.screenshot(path=str(Path(evidence).parent / "browser-synced-desktop.png"), full_page=True)
        with (Path(evidence).parent / "browser.json").open("x", encoding="utf-8") as output:
            json.dump({"engine": "Installed Chrome, headless", "version": page.context.browser.version,
                       "extractor": "injected synthetic data", "airtable": "HTTPX MockTransport"}, output, indent=2)


@pytest.mark.parametrize("sync,label", [
    ("synced", "Synced to Airtable"), ("failed", "Sync failed"), ("unknown", "Sync outcome unknown"),
    ("not_configured", "Airtable is not configured"), ("pending", "Sync pending"), ("skipped", "Sync skipped"),
])
def test_sync_states_are_separate(page, sync, label):
    requests = install_mock(page, mock_response(sync=sync))
    submit(page)
    assert label in page.locator("#sync-status").inner_text()
    assert "Saved locally" in page.locator("#local-status").inner_text()
    assert (page.locator("#sync-status").get_attribute("data-tone") == "success") is (sync == "synced")
    page.wait_for_timeout(250)
    assert len(requests) == 1


def test_needs_review_null_zero_and_safe_text(page):
    body = mock_response(status="needs_review", sync="skipped")
    attack = '<img src=x onerror="window.receiptInjected=true">'
    body["data"].update(merchant=attack, currency=None, total="0.00", tip=None)
    body["data"]["items"][0]["description"] = attack
    body["validation"]["issues"] = [{"code": "missing_currency", "field": "currency", "message": attack}]
    install_mock(page, body)
    submit(page)
    assert "needs review" in page.locator("#local-status").inner_text()
    assert "Review required" in page.locator("#validation-status").inner_text()
    assert "missing_currency" in page.locator("#validation-issues").inner_text()
    assert attack in page.locator("#receipt-details").inner_text()
    assert attack in page.locator("#items").inner_text()
    assert attack in page.locator("#validation-issues").inner_text()
    assert "Unknown" in page.locator("#receipt-details").inner_text()
    assert "0.00" in page.locator("#receipt-details").inner_text()
    assert page.locator("#result img, #result script").count() == 0
    assert page.evaluate("window.receiptInjected === undefined")


@pytest.mark.parametrize("status,code,label", [
    (401, "unauthorized", "Access denied"), (400, "empty_file", "empty"),
    (415, "unsupported_media_type", "supported PDF"), (422, "invalid_pdf", "unreadable"),
    (422, "encrypted_pdf", "Encrypted"), (413, "file_too_large", "upload size limit"),
    (413, "too_many_pages", "page limit"), (413, "request_too_large", "size limit"),
    (504, "processing_timeout", "outcome is unknown"),
    (503, "storage_unavailable", "outcome is unknown"), (500, "internal_error", "outcome is unknown"),
])
def test_http_errors(page, status, code, label):
    requests = install_mock(page, {"detail": {"code": code, "outcome": "unknown" if status >= 500 else None}}, status)
    submit(page)
    assert label in page.locator("#error-message").inner_text()
    assert page.locator("#result").is_hidden()
    assert page.locator("#upload-button").is_enabled()
    page.wait_for_timeout(200)
    assert len(requests) == 1


def test_known_502_keeps_stored_failure_id(page):
    body = mock_response(status="failed", sync="skipped")
    body["data"] = None
    install_mock(page, body, 502)
    submit(page)
    assert body["receipt_id"] in page.locator("#receipt-id").inner_text()
    assert "Processing failed" in page.locator("#local-status").inner_text()
    assert "stored failure" in page.locator("#error-message").inner_text()
    assert "validation did not establish" in page.locator("#validation-status").inner_text()


def test_pending_blocks_duplicate_then_clears_stale_result(page):
    requests = install_mock(page, mock_response())
    submit(page)
    page.unroute("**/api/v1/receipts")
    pending = []
    page.route("**/api/v1/receipts", lambda route: pending.append(route))
    page.locator("#upload-button").click()
    page.locator("#upload-form[aria-busy='true']").wait_for()
    assert page.locator("#waiting").is_visible()
    assert page.locator("#upload-button").is_disabled()
    assert page.locator("#access-key").is_disabled()
    assert page.locator("#pdf-file").is_disabled()
    assert page.locator("#result").is_hidden()
    page.locator("#upload-form").evaluate("form => form.dispatchEvent(new Event('submit', {cancelable: true}))")
    page.wait_for_timeout(200)
    assert len(pending) == 1 and len(requests) == 1
    pending[0].fulfill(status=401, json={"detail": {"code": "unauthorized"}})
    page.locator("#upload-button:enabled").wait_for()
    assert "Access denied" in page.locator("#error-message").inner_text()
    assert page.locator("#result").is_hidden()


@pytest.mark.parametrize("failure", ["network", "browser_timeout", "bad_json", "wrong_shape"])
def test_uncertain_transport_and_response(page, failure):
    requests = []

    def respond(route):
        requests.append(route.request)
        if failure == "network":
            route.abort("connectionreset")
        elif failure == "bad_json":
            route.fulfill(status=200, content_type="text/html", body="<html>unexpected proxy response</html>")
        elif failure == "wrong_shape":
            route.fulfill(status=200, json={"message": "unexpected"})

    page.route("**/api/v1/receipts", respond)
    select_pdf(page)
    if failure == "browser_timeout":
        page.clock.install()
    page.locator("#upload-button").click()
    if failure == "browser_timeout":
        page.locator("#upload-form[aria-busy='true']").wait_for()
        page.clock.fast_forward(180001)
    page.locator("#upload-button:enabled").wait_for()
    assert "outcome is unknown" in page.locator("#error-message").inner_text()
    if failure == "browser_timeout":
        assert "timed out" in page.locator("#error-message").inner_text()
    assert page.locator("#result").is_hidden()
    assert len(requests) == 1


def test_required_inputs_and_mobile_layout(page):
    requests = install_mock(page, mock_response())
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#upload-button").click()
    assert requests == []
    submit(page)
    assert page.locator("#result").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.reload()
    assert page.locator("#access-key").input_value() == ""
    assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
