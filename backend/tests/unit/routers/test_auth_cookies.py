"""
M-22 + 雙路徑 refresh 守護：refresh token httpOnly cookie + double-submit CSRF，
外加跨站部署後備的 body 路徑（cookie 送不出去時 token 放 body、免 CSRF）。

設計重點（對齊 router 層行為，不碰 service 安全語意）：
- /auth/login 成功 → 以 Set-Cookie 下發 httpOnly refresh cookie 與非 httpOnly CSRF
  cookie；body 同時回傳 refresh_token（雙路徑：跨站部署前端存 localStorage）。
- /auth/refresh cookie 路徑 → 要求 X-CSRF-Token 與 csrf cookie 相符（缺 / 不符 → 403），
  旋轉 cookie；cookie 在場時帶 body token 也不得繞過 CSRF（防降級）。
- /auth/refresh body 路徑（無 refresh cookie）→ 免 CSRF（token 由 JS 顯式提交，
  無 CSRF 攻擊面），仍照常旋轉並下發 cookie。
- /auth/logout 同樣分路：有 refresh cookie 必驗 CSRF；純 body 路徑免驗。

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


def test_login_sets_refresh_and_csrf_cookies_and_returns_body_refresh(client):
    resp = _login(client)
    assert resp.status_code == 200

    body = resp.json()
    assert body["access_token"] == "access-A"
    # 雙路徑：body 恢復回傳 refresh_token（跨站部署前端存 localStorage 用）
    assert body["refresh_token"] == "refresh-A"

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

    # 3) header 與 cookie 相符 → 200，旋轉 cookie，body 含新 refresh_token（雙路徑）
    resp_ok = client.post(
        "/api/v1/auth/refresh",
        headers={settings.CSRF_HEADER_NAME: csrf_value},
    )
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["access_token"] == "access-from-refresh-A"
    assert body["refresh_token"] == "refresh-B"
    # 新的 refresh / csrf cookie 已下發
    assert settings.REFRESH_COOKIE_NAME in resp_ok.cookies
    assert settings.CSRF_COOKIE_NAME in resp_ok.cookies


def test_register_sets_cookies_and_returns_body_refresh(client):
    """註冊也以 httpOnly cookie 下發 refresh + CSRF，body 同時回傳 refresh_token。"""
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
    assert body["refresh_token"] == "refresh-R"

    assert settings.REFRESH_COOKIE_NAME in resp.cookies
    assert settings.CSRF_COOKIE_NAME in resp.cookies
    raw = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in raw


def test_refresh_without_cookie_returns_401_even_with_csrf(client):
    """無 refresh cookie 走 body 路徑、body 亦無 refresh_token → 401。"""
    # 手動塞一組相符的 csrf cookie/header，但沒有 refresh cookie 也沒有 body token
    client.cookies.set(settings.CSRF_COOKIE_NAME, "match-me")
    resp = client.post(
        "/api/v1/auth/refresh",
        headers={settings.CSRF_HEADER_NAME: "match-me"},
    )
    assert resp.status_code == 401


def test_refresh_body_path_without_any_cookie_skips_csrf(client):
    """body 路徑（跨站部署後備）：無任何 cookie、無 CSRF header → 仍可換發。

    token 由 JS 顯式放入 body，攻擊者無法跨站取得，無 CSRF 攻擊面（見
    routers/auth.py 的豁免理由），故免 double-submit。cookie 下發不分路徑。
    """
    assert not client.cookies  # 全新 client：未 login、無任何 cookie
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-A"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["access_token"] == "access-from-refresh-A"
    assert body["refresh_token"] == "refresh-B"
    # 回應仍下發 refresh + CSRF cookie（同站客戶端可就地升級回 cookie 路徑）
    assert settings.REFRESH_COOKIE_NAME in resp.cookies
    assert settings.CSRF_COOKIE_NAME in resp.cookies


def test_refresh_cookie_path_not_relaxed_by_body(client):
    """cookie 在場就必驗 CSRF：帶合法 body token 也不得繞過（防降級攻擊）。"""
    _login(client)  # 取得 refresh + csrf cookie

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh-A"},  # 合法 token 放 body，但缺 CSRF header
    )
    assert resp.status_code == 403


def test_refresh_without_credentials_skips_rate_limit(client, monkeypatch):
    """F7 #2：完全無憑證（無 cookie、body 也無 refresh_token）→ 401，且不消耗
    per-IP rate limit 額度（快速拒絕要在 enforce_refresh_ip_rate_limit 之前）。
    """
    import app.core.rate_limit as rl

    calls: list[tuple] = []

    async def _spy(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(rl, "enforce_refresh_ip_rate_limit", _spy)

    assert not client.cookies
    resp = client.post("/api/v1/auth/refresh")  # 無 cookie、無 body
    assert resp.status_code == 401
    assert calls == []

    # body 存在但沒有 refresh_token 欄位，一樣算無憑證
    resp2 = client.post("/api/v1/auth/refresh", json={})
    assert resp2.status_code == 401
    assert calls == []


def test_refresh_with_body_credentials_still_consumes_rate_limit(client, monkeypatch):
    """有憑證（body 路徑）→ 照舊先扣 per-IP 額度，防暴力語意不變。"""
    import app.core.rate_limit as rl

    calls: list[tuple] = []

    async def _spy(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(rl, "enforce_refresh_ip_rate_limit", _spy)

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-A"})
    assert resp.status_code == 200
    assert len(calls) == 1


def test_refresh_with_cookie_credentials_still_consumes_rate_limit(client, monkeypatch):
    """有憑證（cookie 路徑，即便最終因缺 CSRF 而 403）→ 照舊先扣額度。"""
    import app.core.rate_limit as rl

    calls: list[tuple] = []

    async def _spy(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(rl, "enforce_refresh_ip_rate_limit", _spy)

    _login(client)  # 取得 refresh cookie，但這次不帶 X-CSRF-Token
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 403  # CSRF 缺漏被擋下
    assert len(calls) == 1  # 但額度仍先被消耗（cookie 在場即視為「有憑證」）


def test_refresh_rate_limited_takes_precedence_over_csrf_when_credentials_present(client, monkeypatch):
    """有憑證但已超過 rate limit → 429，且發生在 CSRF 檢查之前（維持既有防暴力順序）。"""
    from app.core.exceptions import RateLimitExceededException
    import app.core.rate_limit as rl

    async def _always_limited(*args, **kwargs):
        raise RateLimitExceededException(
            message="errors.login_ip_rate_limited",
            details={"retry_after": 5, "scope": "refresh_ip"},
            message_kwargs={"retry_after": 5},
        )

    monkeypatch.setattr(rl, "enforce_refresh_ip_rate_limit", _always_limited)

    _login(client)  # 取得 refresh + csrf cookie，但這次不帶 X-CSRF-Token
    resp = client.post("/api/v1/auth/refresh")  # cookie 在場，缺 CSRF header
    assert resp.status_code == 429  # 429（rate limit）先於 403（CSRF）


def test_logout_body_path_skips_csrf(client):
    """/auth/logout 分路：純 body 路徑免 CSRF；有 refresh cookie 必驗 CSRF。

    本端點本身已由 Bearer access token（get_current_user）授權，這裡以
    dependency_overrides 塞 fake user，聚焦驗證 CSRF 分路行為。
    """
    from types import SimpleNamespace
    from uuid import UUID

    from app.core.dependencies import get_current_user
    from app.main import app

    fake_user = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        role="patient",
        preferred_language=None,
    )

    async def _fake_current_user():
        return fake_user

    app.dependency_overrides[get_current_user] = _fake_current_user
    try:
        # 1) 無任何 cookie、refresh token 放 body、無 CSRF header → 200
        assert not client.cookies
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer x"},
            json={"refresh_token": "refresh-A"},
        )
        assert resp.status_code == 200

        # 2) 對照組：有 refresh cookie 而缺 CSRF header → 403（cookie 路徑不放寬）
        client.cookies.set(settings.REFRESH_COOKIE_NAME, "refresh-A")
        resp_cookie = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer x"},
            json={"refresh_token": "refresh-A"},
        )
        assert resp_cookie.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
