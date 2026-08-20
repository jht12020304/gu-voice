"""
SO-2（後端半邊）：`POST /api/v1/sessions/{session_id}/reports/generate` 的
request contract 回歸守護。

原始缺陷：`GenerateReportRequest.session_id` 是**必填**，而場次已經在 path
param 上。前端「重新產生」只送 `{"regenerate": true}`（或不送 body）就會被
pydantic 擋成 422 —— regenerate 整條路徑形同不存在。

此檔以 schema 驗證 + 直接呼叫 router handler（不起 DB / HTTP server）守住：
1. body 不帶 session_id 也要能通過驗證
2. body 可以整個省略
3. body 若還帶 session_id（舊 client）一律忽略，**以 path param 為準**
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.routers import reports as reports_router
from app.schemas.report import GenerateReportRequest


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 1. schema：session_id 不再必填
# ──────────────────────────────────────────────────────

def test_regenerate_only_body_validates():
    """前端實際會送的 payload —— 以前這行會 raise ValidationError（→ 422）。"""
    payload = GenerateReportRequest.model_validate({"regenerate": True})
    assert payload.regenerate is True
    assert payload.session_id is None


def test_empty_body_validates_with_regenerate_default_false():
    payload = GenerateReportRequest.model_validate({})
    assert payload.regenerate is False
    assert payload.session_id is None
    assert payload.additional_notes is None


def test_legacy_body_with_session_id_still_validates():
    """回溯相容：舊 client 仍可送 session_id（值會被 handler 忽略）。"""
    sid = uuid.uuid4()
    payload = GenerateReportRequest.model_validate({"session_id": str(sid)})
    assert payload.session_id == sid


def test_session_id_must_still_be_a_uuid_when_present():
    with pytest.raises(ValidationError):
        GenerateReportRequest.model_validate({"session_id": "not-a-uuid"})


# ──────────────────────────────────────────────────────
# 2. handler：path param 為權威來源
# ──────────────────────────────────────────────────────

def _patch_service(monkeypatch):
    mock = AsyncMock(return_value=SimpleNamespace(id="report"))
    monkeypatch.setattr(reports_router.report_service, "generate_report", mock)
    return mock


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def test_handler_without_body_defaults_to_no_regenerate(monkeypatch):
    mock = _patch_service(monkeypatch)
    session_id = uuid.uuid4()
    user = _user()

    _run(
        reports_router.generate_report(
            session_id=session_id, payload=None, db=None, current_user=user
        )
    )

    kwargs = mock.await_args.kwargs
    assert kwargs["session_id"] == session_id
    assert kwargs["regenerate"] is False
    assert kwargs["requested_by"] == user.id


def test_handler_with_regenerate_only_body_passes_flag_through(monkeypatch):
    """「不帶 session_id 呼叫 generate 端點，regenerate 應生效」。"""
    mock = _patch_service(monkeypatch)
    session_id = uuid.uuid4()

    _run(
        reports_router.generate_report(
            session_id=session_id,
            payload=GenerateReportRequest.model_validate({"regenerate": True}),
            db=None,
            current_user=_user(),
        )
    )

    kwargs = mock.await_args.kwargs
    assert kwargs["session_id"] == session_id
    assert kwargs["regenerate"] is True


def test_handler_ignores_body_session_id_and_uses_path_param(monkeypatch):
    """body 指向另一場次時不得越權——一律用 path param。"""
    mock = _patch_service(monkeypatch)
    path_session = uuid.uuid4()
    other_session = uuid.uuid4()

    _run(
        reports_router.generate_report(
            session_id=path_session,
            payload=GenerateReportRequest.model_validate(
                {"session_id": str(other_session), "regenerate": True}
            ),
            db=None,
            current_user=_user(),
        )
    )

    assert mock.await_args.kwargs["session_id"] == path_session


def test_handler_forwards_additional_notes(monkeypatch):
    mock = _patch_service(monkeypatch)

    _run(
        reports_router.generate_report(
            session_id=uuid.uuid4(),
            payload=GenerateReportRequest.model_validate(
                {"additional_notes": "請補充夜尿頻率"}
            ),
            db=None,
            current_user=_user(),
        )
    )

    assert mock.await_args.kwargs["additional_notes"] == "請補充夜尿頻率"


def test_generate_route_body_is_optional_in_openapi():
    """FastAPI 必須把 body 標成非必填（否則不送 body 仍是 422）。"""
    route = next(
        r
        for r in reports_router.router.routes
        if getattr(r, "path", None)
        == "/api/v1/sessions/{session_id}/reports/generate"
    )
    assert route.body_field is not None
    assert route.body_field.required is False
