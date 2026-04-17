"""
守護 P2 #19 SecurityHeadersMiddleware：

- API 路徑回齊 5 個核心安全 header
- /docs /openapi.json 走寬鬆集合（避免打壞 Swagger UI）
- 上游已設的 header 不被覆寫（setdefault 行為）
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import SecurityHeadersMiddleware


@pytest.fixture(scope="module")
def real_client() -> TestClient:
    from app.main import app
    return TestClient(app)


def test_api_path_has_all_core_headers(real_client: TestClient):
    resp = real_client.get("/api/v1/health")
    h = resp.headers
    assert "max-age=31536000" in h["strict-transport-security"]
    assert "includeSubDomains" in h["strict-transport-security"]
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "strict-origin" in h["referrer-policy"]
    assert "microphone=(self)" in h["permissions-policy"]


def test_docs_path_has_relaxed_headers(real_client: TestClient):
    resp = real_client.get("/openapi.json")
    h = resp.headers
    # 仍然要有 HSTS + nosniff
    assert "max-age=" in h["strict-transport-security"]
    assert h["x-content-type-options"] == "nosniff"
    # 不該有 X-Frame-Options: DENY（會打壞 Swagger embed 行為）
    assert h.get("x-frame-options") is None


def test_setdefault_does_not_overwrite_upstream_header():
    """若上游路由自己設了 X-Frame-Options 就留著，不覆寫。"""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/test")
    async def handler():
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    client = TestClient(app)
    resp = client.get("/api/test")
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    # 沒設過的還是會套 default
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_error_response_also_has_headers(real_client: TestClient):
    """4xx 也要帶安全 header（避免任何路徑漏掉）。"""
    resp = real_client.get("/api/v1/this-path-does-not-exist")
    assert resp.status_code == 404
    assert resp.headers.get("x-content-type-options") == "nosniff"
