"""A5 [D3] 紅旗跨輪去重單元測試（e2e_realopenai_audit §三）。

守護的不變式：
- 去重只抑制「持久化 + 廣播」，絕不過濾 abort 判斷用的 red_flag_alerts list
  （被抑制的 critical 仍必須觸發 aborted_red_flag —— 醫療安全）。
- record-on-success：持久化失敗不記錄（下一輪重試照送）。
- 升級放行：high→critical 必過；同 severity 以下抑制（D3：肉眼血尿 18×→1×）。
- Redis 失效 / 身份不明 / severity 不明 → fail-open（寧重複不可漏急症）。
"""

from __future__ import annotations

import asyncio

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    StubDetector,
    make_alert,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID
_KEY = ch._SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=SID)


def _suppress(redis, alert) -> bool:
    return asyncio.run(ch._should_suppress_duplicate_alert(redis, SID, alert))


def _record(redis, alert) -> None:
    asyncio.run(ch._record_emitted_alert(redis, SID, alert))


# ── helper 級（直接測模組函式 + FakeRedis） ──────────────────
def test_first_emit_not_suppressed():
    assert _suppress(FakeRedis(), make_alert(severity="high")) is False


def test_record_then_same_severity_suppressed():
    redis = FakeRedis()
    _record(redis, make_alert(severity="high"))
    assert redis.hashes[_KEY]["gross_hematuria"] == "high"
    assert _suppress(redis, make_alert(severity="high")) is True


def test_lower_severity_suppressed():
    redis = FakeRedis()
    _record(redis, make_alert(severity="critical"))
    assert _suppress(redis, make_alert(severity="high")) is True
    assert _suppress(redis, make_alert(severity="medium")) is True


def test_escalation_high_to_critical_passes():
    redis = FakeRedis()
    _record(redis, make_alert(severity="high"))
    assert _suppress(redis, make_alert(severity="critical")) is False


def test_redis_down_fail_open():
    redis = FakeRedis(fail=True)
    assert _suppress(redis, make_alert(severity="high")) is False
    # record 不可外拋（記錄失敗頂多下一輪重複 emit）
    _record(redis, make_alert(severity="high"))


def test_missing_canonical_falls_back_to_title():
    redis = FakeRedis()
    alert = make_alert(severity="high", canonical_id=None, title="肉眼血尿")
    _record(redis, alert)
    assert redis.hashes[_KEY]["肉眼血尿"] == "high"
    assert _suppress(redis, alert) is True


def test_no_identity_never_suppressed():
    redis = FakeRedis()
    alert = make_alert(severity="high", canonical_id=None, title="")
    _record(redis, alert)  # 身份不明 → 不記錄
    assert redis.hashes == {}
    assert _suppress(redis, alert) is False


def test_unknown_severity_fail_open():
    redis = FakeRedis()
    _record(redis, make_alert(severity="high"))
    assert _suppress(redis, make_alert(severity="weird")) is False


def test_unknown_previous_severity_fail_open():
    """hash 內殘留不明 severity（例如格式演進）→ fail-open 放行。"""
    redis = FakeRedis()
    redis.hashes[_KEY] = {"gross_hematuria": "banana"}
    assert _suppress(redis, make_alert(severity="high")) is False


# ── harness 級（record-on-success + 不變式） ─────────────────
def test_persist_failure_not_recorded(monkeypatch):
    """持久化失敗 → 不記錄去重身份（下一輪照送）、error 事件有送。"""
    res = run_text_turn(
        monkeypatch,
        detector=StubDetector(alerts=[make_alert(severity="high")]),
        alert_create_side_effect=RuntimeError("db down"),
    )
    assert res.alert_create.called
    assert res.redis.hashes == {}  # record-on-success：失敗不記
    assert any(
        c["code"] == "errors.ws.red_flag_persist_failed"
        for c in res.cap.localized_calls
    )
    # 未持久化 → 不可對前端偽造 red_flag_alert 事件
    assert res.cap.messages_of_type("red_flag_alert") == []


def test_suppressed_critical_still_aborts(monkeypatch):
    """關鍵不變式：去重抑制的是持久化/廣播，不是 abort 判斷。
    同 canonical critical 已 emit 過 → 本輪不再持久化，但仍觸發 aborted_red_flag。"""
    redis = FakeRedis()
    redis.hashes[_KEY] = {"testicular_torsion": "critical"}
    alert = make_alert(
        severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
    )
    res = run_text_turn(
        monkeypatch,
        redis=redis,
        detector=StubDetector(alerts=[alert]),
    )
    assert not res.alert_create.called  # 持久化被抑制
    assert res.cap.messages_of_type("red_flag_alert") == []  # 廣播被抑制
    statuses = [c.args[3] for c in res.update_status.call_args_list]
    assert "aborted_red_flag" in statuses  # abort 照走（不變式）
    abort_calls = [
        c
        for c in res.cap.localized_calls
        if c["code"] == "events.session.aborted_red_flag"
    ]
    assert abort_calls
    # 患者面 abort 訊息須帶終態 status，前端才能導離對話頁（不卡「使用中」+無限重連）。
    assert all(
        c["extra"].get("status") == "aborted_red_flag" for c in abort_calls
    )


def test_second_turn_same_high_suppressed_but_banner_semantics(monkeypatch):
    """D3 修復：同一 high 紅旗跨輪只持久化/廣播 1 次（肉眼血尿 18×→1×）。"""
    redis = FakeRedis()
    session_context = {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }
    history: list = []
    alert = make_alert(severity="high")

    res1 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[dict(alert)]),
    )
    assert res1.alert_create.call_count == 1
    assert len(res1.cap.messages_of_type("red_flag_alert")) == 1
    assert redis.hashes[_KEY]["gross_hematuria"] == "high"

    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[dict(alert)]),
    )
    assert res2.alert_create.call_count == 0  # 第 2 輪被抑制
    assert res2.cap.messages_of_type("red_flag_alert") == []


def test_second_turn_escalated_critical_persists_and_aborts(monkeypatch):
    """升級放行：第 1 輪 high、第 2 輪同 canonical critical → 照常持久化並 abort。"""
    redis = FakeRedis()
    session_context = {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }
    history: list = []

    res1 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[make_alert(severity="high")]),
    )
    assert res1.alert_create.call_count == 1

    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[make_alert(severity="critical")]),
    )
    assert res2.alert_create.call_count == 1  # 升級放行
    statuses = [c.args[3] for c in res2.update_status.call_args_list]
    assert "aborted_red_flag" in statuses
    assert redis.hashes[_KEY]["gross_hematuria"] == "critical"  # 記錄升級後 severity
