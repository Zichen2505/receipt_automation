"""Same-origin public assets preserve the authenticated business boundary."""

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.mark.parametrize("path,media,marker", [
    ("/", "text/html", "id=\"upload-form\""),
    ("/web/upload.js", "text/javascript", "/api/v1/receipts"),
    ("/web/style.css", "text/css", "focus-visible"),
])
def test_public_web_assets(monkeypatch, tmp_path, path, media, marker):
    monkeypatch.setenv("APP_API_KEY", "offline-web-route-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media)
        assert response.headers["cache-control"] == "no-store"
        assert "form-action 'none'" in response.headers["content-security-policy"]
        assert "connect-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert marker in response.text
        assert "offline-web-route-key" not in response.text
        assert client.get("/api/v1/receipts/missing").status_code == 401
        assert client.post("/api/v1/receipts/missing/sync").status_code == 401
        assert client.get("/api/v1/receipts/missing/export", headers={"X-API-Key": "offline-web-route-key"}).status_code == 501
        assert client.get("/web/../config.py").status_code == 404
