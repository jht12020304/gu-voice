"""
INFRA-1 資安回歸測試 — 全域未處理例外 handler 不得把內部細節回傳給 client。

背景：
    舊版 `unhandled_exception_handler` 把 `str(exc)` 直接放進回應的
    `error.details`，可能外洩 DB 連線字串 / 檔案路徑 / 內部 stack 訊息。
    修正後 client 只會看到 request_id，完整例外（含 traceback）僅記在
    伺服器 log 與 Sentry。

採 FastAPI TestClient + 臨時 app 做 integration-style 測試，與
tests/unit/middleware/test_i18n_error_handler.py 同風格。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import ErrorCode, register_exception_handlers

# 故意嵌入「像內部細節」的敏感字串，斷言它不會出現在 client 回應裡。
_LEAKY_SECRET = "postgresql://user:pw@db.internal:5432/secret_table"  # noqa: S105


def _build_crashing_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError(_LEAKY_SECRET)

    return app


def test_internal_detail_not_leaked_to_client():
    """str(exc) 內含的敏感字串不得出現在回應 body 任何位置。"""
    app = _build_crashing_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/crash")

    assert resp.status_code == 500
    raw_body = resp.text
    assert _LEAKY_SECRET not in raw_body, "內部例外字串外洩到 client 回應"

    err = resp.json()["error"]
    # details 改為只含 request_id 的安全物件，不再是 str(exc)。
    assert err["details"] == {"request_id": err["request_id"]}
    assert err["code"] == ErrorCode.INTERNAL_ERROR.value


def test_response_schema_preserved():
    """回應仍保留 {error:{code,message,details,request_id,timestamp}} 結構。"""
    app = _build_crashing_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        body = client.get("/crash").json()

    assert set(body.keys()) == {"error"}
    assert {"code", "message", "details", "request_id", "timestamp"}.issubset(
        body["error"].keys()
    )


def test_full_exception_still_logged_server_side(caplog):
    """完整例外必須記在伺服器 log（觀測性不可因修正而流失）。"""
    app = _build_crashing_app()
    with caplog.at_level(logging.ERROR, logger="app.core.exceptions"):
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get("/crash")

    # logger.exception 會帶 exc_info；敏感字串只該出現在伺服器端 log，不在 client。
    assert any(
        rec.levelno >= logging.ERROR and rec.exc_info is not None
        for rec in caplog.records
    ), "未處理例外未以 ERROR + exc_info 記錄到伺服器 log"
    assert _LEAKY_SECRET in caplog.text, "伺服器端 log 應保留完整例外細節"
