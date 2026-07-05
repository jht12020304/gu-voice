"""
守護 conversations.red_flag_detected 標記（session_data_inventory §11-3 修復）：

紅旗警示持久化成功後，觸發它的「病患對話輪」必須被 UPDATE 成
red_flag_detected=true；無紅旗的輪次不得出現此 UPDATE。
標記失敗必須非致命（警示本身已 commit，不可受影響）。
"""

from __future__ import annotations

from tests.unit.websocket.conftest import StubDetector, make_alert, run_text_turn


def _conversation_update_stmts(db) -> list[str]:
    return [
        s
        for s in (str(stmt) for stmt in db.executed)
        if "UPDATE conversations" in s and "red_flag_detected" in s
    ]


def test_high_alert_marks_patient_conversation_row(monkeypatch):
    r = run_text_turn(
        monkeypatch,
        detector=StubDetector(alerts=[make_alert(severity="high")]),
    )
    marks = _conversation_update_stmts(r.db)
    assert marks, "紅旗持久化後應 UPDATE 病患對話輪 red_flag_detected"


def test_no_alert_no_conversation_mark(monkeypatch):
    r = run_text_turn(monkeypatch, detector=StubDetector(alerts=[]))
    assert _conversation_update_stmts(r.db) == []


def test_alert_persist_failure_skips_mark_but_not_fatal(monkeypatch):
    """AlertService.create 失敗 → 不偽造 alert、也不標記；整輪不拋例外。"""
    r = run_text_turn(
        monkeypatch,
        detector=StubDetector(alerts=[make_alert(severity="high")]),
        alert_create_side_effect=RuntimeError("db down (injected)"),
    )
    assert _conversation_update_stmts(r.db) == []
