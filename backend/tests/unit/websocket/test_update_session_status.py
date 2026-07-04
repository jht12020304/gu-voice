"""A4 [D2] 模組級 _update_session_status 單元測試（e2e_realopenai_audit §三）。

守護的不變式：
- 轉 aborted_red_flag 時補寫 red_flag=True（+ 有 reason 才寫 red_flag_reason）。
- completed 不寫 red_flag（E7 決策 3：session.red_flag 語意＝「因紅旗中止」，
  「曾有紅旗」查 red_flag_alerts 表）。
- WHERE 兩條件（id + status==previous）一字不動 —— compare-and-set 終態保護：
  aborted_red_flag 永不被後續路徑降級成 completed。
- rowcount=0（狀態不符）→ 回 False 且不動 Redis；DB 例外 → 回 False 不外拋。
"""

from __future__ import annotations

import asyncio

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import DEFAULT_SESSION_ID, FakeRedis, StubDB

SID = DEFAULT_SESSION_ID


def _run(db, redis, new_status, previous_status, **kwargs):
    return asyncio.run(
        ch._update_session_status(db, redis, SID, new_status, previous_status, **kwargs)
    )


def _compiled_params(stmt) -> dict:
    return dict(stmt.compile().params)


def test_aborted_sets_red_flag_and_reason():
    db = StubDB(rowcount=1)
    redis = FakeRedis()
    ok = _run(db, redis, "aborted_red_flag", "in_progress", red_flag_reason="睪丸扭轉")
    assert ok is True
    assert len(db.executed) == 1
    params = _compiled_params(db.executed[0])
    assert params["status"] == "aborted_red_flag"
    assert params["red_flag"] is True
    assert params["red_flag_reason"] == "睪丸扭轉"
    # WHERE 兩條件不動（終態保護）：id 與 status==previous
    stmt = db.executed[0]
    assert len(stmt._where_criteria) == 2
    assert params["id_1"] == SID
    assert params["status_1"] == "in_progress"
    # 轉移成功 → Redis 快取同步
    assert redis.hset_calls and redis.hset_calls[0][2] == "aborted_red_flag"


def test_aborted_without_reason_sets_flag_only():
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "aborted_red_flag", "in_progress")
    assert ok is True
    params = _compiled_params(db.executed[0])
    assert params["red_flag"] is True
    assert "red_flag_reason" not in params


def test_completed_does_not_write_red_flag():
    """E7 決策 3：high-only 撐到硬上限收尾的 completed 也不設 red_flag。"""
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "completed", "in_progress")
    assert ok is True
    params = _compiled_params(db.executed[0])
    assert params["status"] == "completed"
    assert "red_flag" not in params
    assert "red_flag_reason" not in params


def test_in_progress_does_not_write_red_flag():
    """既有呼叫點（waiting→in_progress）行為不變。"""
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "in_progress", "waiting")
    assert ok is True
    params = _compiled_params(db.executed[0])
    assert params["status"] == "in_progress"
    assert "red_flag" not in params


def test_no_transition_returns_false_and_skips_redis():
    """rowcount=0（目前狀態 != previous）→ no-op：回 False、不動 Redis。"""
    db = StubDB(rowcount=0)
    redis = FakeRedis()
    ok = _run(db, redis, "completed", "in_progress")
    assert ok is False
    assert redis.hset_calls == []


def test_db_error_returns_false():
    db = StubDB(execute_error=RuntimeError("db down"))
    redis = FakeRedis()
    ok = _run(db, redis, "aborted_red_flag", "in_progress", red_flag_reason="x")
    assert ok is False
    assert redis.hset_calls == []


# ── E8-3：sessions.started_at / completed_at 補寫 ──────────────────────────
# 根因：這兩欄過去只有 REST 端點（SessionService.update_status_static）會寫，
# 但實際問診幾乎全程走 WS 這條路徑（本函式），從未被寫過 → 恆為 NULL，
# dashboard 平均時長只能退回同樣沒人寫的 duration_seconds（等於恆缺值）。
def test_in_progress_sets_started_at_via_coalesce_not_where():
    """轉 in_progress 時用 COALESCE(既有值, now()) 達成冪等 —— 刻意不能用額外
    WHERE 擋（compare-and-set 條件不可動；resume 重連時 previous_status 常已是
    in_progress，加 WHERE 會讓整條 UPDATE 連 status 都轉不了）。"""
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "in_progress", "waiting")
    assert ok is True
    stmt = db.executed[0]
    sql = str(stmt.compile())
    assert "started_at=coalesce(sessions.started_at, now())" in sql
    assert "completed_at" not in sql
    # WHERE 仍然只有 id + status==previous 兩條件（終態保護不受影響）。
    assert len(stmt._where_criteria) == 2


def test_in_progress_resume_reconnect_still_transitions_status():
    """既有『重連時 previous_status 已是 in_progress』情境：status 轉移本身
    （rowcount）不可因新增 started_at 邏輯而被擋下。"""
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "in_progress", "in_progress")
    assert ok is True


def test_completed_sets_completed_at():
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "completed", "in_progress")
    assert ok is True
    sql = str(db.executed[0].compile())
    assert "completed_at=now()" in sql
    assert "started_at" not in sql


def test_aborted_red_flag_sets_completed_at():
    db = StubDB(rowcount=1)
    ok = _run(db, FakeRedis(), "aborted_red_flag", "in_progress", red_flag_reason="x")
    assert ok is True
    sql = str(db.executed[0].compile())
    assert "completed_at=now()" in sql


def test_no_transition_skips_timestamp_write_too():
    """rowcount=0（CAS 失敗）：連 status 都沒轉移，started_at/completed_at 的
    SQL 表達式雖然出現在語句裡（UPDATE 語句本身沒送出才是重點），但整條
    UPDATE 因 WHERE 不符根本不會生效 —— 這裡鎖住『no-op 回 False』不變。"""
    db = StubDB(rowcount=0)
    redis = FakeRedis()
    ok = _run(db, redis, "completed", "in_progress")
    assert ok is False
    assert redis.hset_calls == []
