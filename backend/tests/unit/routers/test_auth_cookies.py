"""
M-22 守護：refresh token httpOnly cookie 遷移 + double-submit CSRF。

設計重點（對齊 router 層行為，不碰 service 安全語意）：
- /auth/login 成功 → 以 Set-Cookie 下發 httpOnly refresh cookie 與非 httpOnly CSRF
  cookie；回應 body 不再含 refresh_token。
- /auth/refresh 成功 → 從 refresh cookie 讀 token，要求 X-CSRF-Token 與 csrf cookie
  相符，旋轉 cookie，body 不含 refresh_token。
- /auth/refresh 缺 CSRF header / 不符 → 403。
- /auth/logout 缺 CSRF → 403；帶 CSRF → 清除 refresh + csrf cookie。

純 router 測試：monkeypatch service 與 rate limit / redis，不起真 DB / Redis。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    from app.main import app
    from app.routers import auth as auth_router

    # TestClient 走 http://testserver；Secure cookie 不會被 jar 送回，故在測試環境
    # 關掉 Secure（等同本機 http 開發設定），讓 cookie round-trip 可被驗證。
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)

    # ── stub AuthService（router 仍以 dict 與之互動，service 簽名不變） ──
    async def _fake_login(db, email, password, client_ip=""):
        return {
            "access_token": "access-A",
            "refresh_token": "refresh-A",
            "token_type": "bearer",
            "expires_in": 900,
            "user": {
                "id": "00000000-0000-0000-0000-000000000001",
                "email": email,
                "name": "Tester",
                "role": "patient",
                "preferred_language": None,
            },
        }

    async def _fake_refresh(db, refresh_token):
        return {
            "access_token": f"access-from-{refresh_token}",
            "refresh_token": "refresh-B",
            "token_type": "bearer",
            "expires_in": 900,
        }

    async def _fake_logout(db, user_id, access_token, refresh_token=None):
        return None

    async def _fake_register(db, data, current_user=None):
        return {
            "access_token": "access-R",
            "refresh_token": "refresh-R",
            "token_type": "bearer",
            "expires_in": 900,
            "user": {
                "id": "00000000-0000-0000-0000-000000000002",
                "email": data.email,
                "name": data.name,
                "role": "patient",
                "preferred_language": None,
            },
        }

    monkeypatch.setattr(auth_router.auth_service, "login", _fake_login)
    monkeypatch.setattr(auth_router.auth_service, "refresh_token", _fake_refresh)
    monkeypatch.setattr(auth_router.auth_service, "logout", _fake_logout)
    monkeypatch.setattr(auth_router.auth_service, "register", _fake_register)

    # ── stub rate limit + redis（refresh / login 端點會碰） ──
    import app.core.rate_limit as rl

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(rl, "enforce_refresh_ip_rate_limit", _noop)
    monkeypatch.setattr(rl, "enforce_login_ip_rate_limit", _noop)
    monkeypatch.setattr(rl, "enforce_register_ip_rate_limit", _noop)

    async def _fake_get_redis():
        return object()

    import app.cache.redis_client as redis_client
    monkeypatch.setattr(redis_client, "get_redis", _fake_get_redis)

    return TestClient(app)


def _login(client: TestClient):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "tester@example.com", "password": "whatever"},
    )


def test_login_sets_refresh_and_csrf_cookies_and_omits_body_refresh(client):
    resp = _login(client)
    assert resp.status_code == 200

    body = resp.json()
    assert body["access_token"] == "access-A"
    # 安全目的：body 不再回傳 refresh_token
    assert "refresh_token" not in body

    cookies = resp.cookies
    assert settings.REFRESH_COOKIE_NAME in cookies
    assert settings.CSRF_COOKIE_NAME in cookies

    # refresh cookie 必須 httpOnly（前端不可讀）；Set-Cookie 標頭應含 HttpOnly。
    raw = resp.headers.get("set-cookie", "")
    assert settings.REFRESH_COOKIE_NAME in raw
    assert "HttpOnly" in raw


def test_refresh_requires_csrf_match(client):
    _login(client)  # 取得 refresh + csrf cookie（存於 client.cookies）

    csrf_value = client.cookies.get(settings.CSRF_COOKIE_NAME)
    assert csrf_value

    # 1) 缺 X-CSRF-Token header → 403
    resp_missing = client.post("/api/v1/auth/refresh")
    assert resp_missing.status_code == 403

    # 2) header 與 cookie 不符 → 403
    resp_mismatch = client.post(
        "/api/v1/auth/refresh",
        headers={settings.CSRF_HEADER_NAME: "wrong-value"},
    )
    assert resp_mismatch.status_code == 403

    # 3) header 與 cookie 相符 → 200，旋轉 cookie，body 不含 refresh_token
    resp_ok = client.post(
        "/api/v1/auth/refresh",
        headers={settings.CSRF_HEADER_NAME: csrf_value},
    )
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["access_token"] == "access-from-refresh-A"
    assert "refresh_token" not in body
    # 新的 refresh / csrf cookie 已下發
    assert settings.REFRESH_COOKIE_NAME in resp_ok.cookies
    assert settings.CSRF_COOKIE_NAME in resp_ok.cookies


def test_register_sets_cookies_and_omits_body_refresh(client):
    """M-22：註冊也以 httpOnly cookie 下發 refresh + CSRF，body 不含 refresh_token。"""
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newbie@example.com",
            "password": "Whatever123",
            "name": "Newbie",
            "role": "patient",
        },
    )
    assert resp.status_code == 201

    body = resp.json()
    assert body["access_token"] == "access-R"
    assert "refresh_token" not in body

    assert settings.REFRESH_COOKIE_NAME in resp.cookies
    assert settings.CSRF_COOKIE_NAME in resp.cookies
    raw = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in raw


def test_refresh_without_cookie_returns_401_even_with_csrf(client):
    """無 refresh cookie 且 body 未帶 → 401（CSRF 通過後才檢查 token 來源）。"""
    # 手動塞一組相符的 csrf cookie/header，但沒有 refresh cookie
    client.cookies.set(settings.CSRF_COOKIE_NAME, "match-me")
    resp = client.post(
        "/api/v1/auth/refresh",
        headers={settings.CSRF_HEADER_NAME: "match-me"},
    )
    assert resp.status_code == 401
