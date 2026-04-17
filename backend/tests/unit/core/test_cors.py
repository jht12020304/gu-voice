"""
守護 P2 #18 CORS 設定：

- preflight（OPTIONS）回 Access-Control-Allow-Methods 明確列表，不是 "*"
- 允許的 header 僅限精確白名單
- expose_headers 包含 X-Request-ID（前端要讀 request_id）
- 未列在 CORS_ORIGINS 的 origin 發 preflight：不回 Access-Control-Allow-Origin
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 延後 import 避免 test collection 時就啟動 FastAPI
    from app.main import app
    return TestClient(app)


def test_preflight_exposes_explicit_methods(client: TestClient):
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code in (200, 204)
    methods = resp.headers.get("access-control-allow-methods", "")
    # 必須精確列舉，不能是 "*"
    assert methods != "*"
    for m in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        assert m in methods


def test_preflight_headers_explicit_whitelist(client: TestClient):
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-request-id",
        },
    )
    allow_h = resp.headers.get("access-control-allow-headers", "").lower()
    assert allow_h != "*"
    assert "authorization" in allow_h
    assert "content-type" in allow_h
    assert "x-request-id" in allow_h


def test_preflight_does_not_allow_arbitrary_header(client: TestClient):
    """奇怪的自訂 header 不可被列進 Allow-Headers。"""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-leak-me-anywhere",
        },
    )
    allow_h = resp.headers.get("access-control-allow-headers", "").lower()
    assert "x-leak-me-anywhere" not in allow_h


def test_expose_request_id_header(client: TestClient):
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"},
    )
    expose = resp.headers.get("access-control-expose-headers", "").lower()
    assert "x-request-id" in expose


def test_disallowed_origin_not_echoed(client: TestClient):
    """未在 allowlist 的 origin 不該被 echo 到 Access-Control-Allow-Origin。"""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    origin_echo = resp.headers.get("access-control-allow-origin", "")
    assert origin_echo != "http://evil.example.com"


def test_preflight_max_age_set(client: TestClient):
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    max_age = resp.headers.get("access-control-max-age")
    assert max_age is not None
    assert int(max_age) >= 60  # 至少 1 分鐘 cache
