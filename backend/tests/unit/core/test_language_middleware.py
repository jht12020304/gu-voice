"""守護 LanguageMiddleware：確保每個請求都能把語言寫到 `request.state.language`。

驗收條件：
- Accept-Language header → state.language
- X-Language header 優先於 Accept-Language
- ?lng= query 優先於 headers
- 未帶任何 header → DEFAULT_LANGUAGE
- response 必帶 Content-Language header
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.language_middleware import LanguageMiddleware


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LanguageMiddleware)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, str]:
        return {"language": request.state.language}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_accept_language_header_populates_state(client: TestClient):
    resp = client.get("/probe", headers={"Accept-Language": "en-US,zh-TW;q=0.8"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "en-US"
    assert resp.headers["Content-Language"] == "en-US"


def test_x_language_header_overrides_accept_language(client: TestClient):
    resp = client.get(
        "/probe",
        headers={
            "Accept-Language": "en-US",
            "X-Language": "zh-TW",
        },
    )
    assert resp.json()["language"] == "zh-TW"


def test_lng_query_param_overrides_headers(client: TestClient):
    resp = client.get(
        "/probe?lng=ja-JP",
        headers={"Accept-Language": "en-US", "X-Language": "zh-TW"},
    )
    assert resp.json()["language"] == "ja-JP"


def test_no_hint_falls_back_to_default(client: TestClient):
    resp = client.get("/probe")
    assert resp.json()["language"] == settings.DEFAULT_LANGUAGE
    assert resp.headers["Content-Language"] == settings.DEFAULT_LANGUAGE


def test_unsupported_lng_query_falls_through(client: TestClient):
    """`?lng=fr-FR` 不在 SUPPORTED → 退 Accept-Language。"""
    resp = client.get(
        "/probe?lng=fr-FR",
        headers={"Accept-Language": "en-US"},
    )
    assert resp.json()["language"] == "en-US"
