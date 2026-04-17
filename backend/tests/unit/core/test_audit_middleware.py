"""
守護 P2 #17 audit middleware：

- `_match_audit_rule` 精準：sensitive paths 命中、健康檢查/讀取不命中
- `AuditLoggingMiddleware` 只針對 allowlist 觸發 `_persist_audit_entry`
- persist 失敗不影響 response
- UUID resource_id 從路徑抓出

FastAPI TestClient + 將 `_persist_audit_entry` patch 成收集器，不連真 DB。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import middleware as mw
from app.models.enums import AuditAction


# ──────────────────────────────────────────────────────────
# _match_audit_rule 直接測
# ──────────────────────────────────────────────────────────

def test_match_login():
    out = mw._match_audit_rule("POST", "/api/v1/auth/login")
    assert out is not None
    assert out[0] == AuditAction.LOGIN
    assert out[1] == "user"
    assert out[2] is None


def test_match_session_delete_extracts_uuid():
    sid = str(uuid.uuid4())
    out = mw._match_audit_rule("DELETE", f"/api/v1/sessions/{sid}")
    assert out is not None
    assert out[0] == AuditAction.DELETE
    assert out[1] == "session"
    assert out[2] == sid


def test_match_red_flag_acknowledge():
    aid = str(uuid.uuid4())
    out = mw._match_audit_rule("POST", f"/api/v1/red-flag-alerts/{aid}/acknowledge")
    assert out is not None
    assert out[0] == AuditAction.ACKNOWLEDGE
    assert out[2] == aid


def test_match_soap_review():
    rid = str(uuid.uuid4())
    out = mw._match_audit_rule("PUT", f"/api/v1/soap-reports/{rid}")
    assert out is not None
    assert out[0] == AuditAction.REVIEW


def test_health_never_matches():
    assert mw._match_audit_rule("GET", "/api/v1/health") is None
    assert mw._match_audit_rule("POST", "/api/v1/health") is None


def test_get_session_not_audited():
    """讀取請求（GET）不落 audit，避免洪水。"""
    sid = str(uuid.uuid4())
    assert mw._match_audit_rule("GET", f"/api/v1/sessions/{sid}") is None


def test_non_api_path_not_matched():
    assert mw._match_audit_rule("POST", "/docs") is None
    assert mw._match_audit_rule("POST", "/metrics") is None


# ──────────────────────────────────────────────────────────
# Middleware 整合測試（FastAPI TestClient）
# ──────────────────────────────────────────────────────────

@pytest.fixture
def captured_audit(monkeypatch):
    """攔截 `_persist_audit_entry` 呼叫，收進 list。"""
    calls: list[dict[str, Any]] = []

    async def _fake_persist(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(mw, "_persist_audit_entry", _fake_persist)
    return calls


@pytest.fixture
def app_with_audit():
    app = FastAPI()
    app.add_middleware(mw.AuditLoggingMiddleware)

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/sessions/anything")
    async def read_session():
        return {"ok": True}

    return app


def test_middleware_triggers_persist_on_login(app_with_audit, captured_audit):
    client = TestClient(app_with_audit)
    resp = client.post("/api/v1/auth/login", headers={"user-agent": "ua-test"})
    assert resp.status_code == 200
    # fire-and-forget task 已被 create；讓 event loop 跑一下
    # TestClient 會在每個 request 結束時結束事件迴圈，asyncio.create_task 在同一個 loop
    # 已排程並執行。捕獲可能 0 或 1（視 loop 政策）
    # 保守：額外跑一輪 event loop 讓 fire-and-forget 完成
    async def _drain():
        await asyncio.sleep(0)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drain())
    finally:
        loop.close()

    # TestClient 每 request 都有自己的 loop；create_task 會在 request 的 loop 裡跑完
    assert len(captured_audit) == 1
    entry = captured_audit[0]
    assert entry["action"] == AuditAction.LOGIN
    assert entry["resource_type"] == "user"
    assert entry["resource_id"] is None
    assert entry["user_agent"] == "ua-test"
    assert entry["details"]["method"] == "POST"
    assert entry["details"]["path"] == "/api/v1/auth/login"
    assert entry["details"]["status_code"] == 200


def test_middleware_skips_health(app_with_audit, captured_audit):
    client = TestClient(app_with_audit)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert captured_audit == []


def test_middleware_skips_reads(app_with_audit, captured_audit):
    client = TestClient(app_with_audit)
    resp = client.get("/api/v1/sessions/anything")
    assert resp.status_code == 200
    assert captured_audit == []


def test_middleware_records_failures_too(app_with_audit, captured_audit):
    """4xx / 5xx 也要審計（含 details.status_code）。"""
    app = app_with_audit

    @app.post("/api/v1/sessions")
    async def fail():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="nope")

    client = TestClient(app)
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 403
    assert len(captured_audit) == 1
    assert captured_audit[0]["action"] == AuditAction.CREATE
    assert captured_audit[0]["details"]["status_code"] == 403


def test_persist_exception_does_not_break_response(app_with_audit, monkeypatch):
    """persist 失敗應該只 log，不讓 API 回 500。"""
    async def _boom(**_):
        raise RuntimeError("db down")

    monkeypatch.setattr(mw, "_persist_audit_entry", _boom)

    client = TestClient(app_with_audit)
    resp = client.post("/api/v1/auth/login")
    assert resp.status_code == 200, "persist 失敗不該影響 response"
