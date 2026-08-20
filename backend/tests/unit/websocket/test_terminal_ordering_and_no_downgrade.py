"""終態路徑的三個順序／降級不變式（EM-1 / EM-5 / SO-3）。

三個缺陷都不是「少做一件事」，而是「事情做的順序或收尾點不對」——單看每個
分支的程式碼都像對的，錯在分支之間的縫隙：

- **EM-1（P0）**：主 critical abort 分支收尾後 **沒有 return**，會 fall-through 進
  下方的自動結束區塊。abort 的 DB 寫入失敗（CAS 回 False，場次其實還停在
  in_progress）時，下面那個 `_update_session_status(completed, in_progress)` 的
  CAS 就會命中 —— 剛判定要中止的紅旗場次被**降級成 completed**，醫師端的分流
  訊號被抹掉，病患也會收到一般感謝頁而不是「請告知現場醫護」。
- **EM-5**：自動結束路徑把 `_terminated` 設在三個 await 之後，那段窗口內背景
  late-critical drain 可以插隊跑完整套 abort 收尾。abort 路徑早就是「先標再送」，
  兩條路徑不一致。
- **SO-3**：硬上限 inline drain 解析出 late-critical 時，`_finalize_red_flag_abort`
  會立刻 `generate_soap_report.delay()`，而那面紅旗還在背景 drain 手上尚未
  commit —— Celery worker 撈 `red_flag_alerts` 時撈不到，SOAP 少掉觸發中止的紅旗。
"""

from __future__ import annotations

import asyncio
from typing import Any

from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    StubDB,
    StubDetector,
    _CaptureManager,
    make_alert,
    make_settings,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID


def _ctx() -> dict[str, Any]:
    """K=0 主訴：避開 §3b 風險因子動態 cap 加成，讓硬上限回合數可預期。"""
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "睪丸疼痛",
        "chief_complaint_display": "睪丸疼痛",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }


def _critical_alert() -> dict[str, Any]:
    return make_alert(
        severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
    )


# ══ EM-1：abort 收尾失敗不得降級成 completed ══════════════
def test_failed_abort_must_not_fall_through_to_completed(monkeypatch):
    """注入式：讓 aborted_red_flag 的狀態寫入失敗（CAS 回 False），
    同時把回合數推到硬上限——修好之前這一輪會 fall-through 進自動結束區塊，
    把場次寫成 completed。"""
    seen: list[str] = []

    async def _update(db, redis, sid, new_status, previous, **kwargs):
        seen.append(new_status)
        # 模擬「abort 的 DB 寫入炸了」：真實 `_update_session_status` 在例外時
        # 也是回 False（fire-and-forget，不可炸主迴圈）。
        return new_status != "aborted_red_flag"

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1, MIN_PATIENT_TURNS_BEFORE_AUTO_END=1
        ),
        session_context=_ctx(),
        detector=StubDetector(alerts=[_critical_alert()]),
        update_status=_update,
    )

    assert "aborted_red_flag" in seen, "沒有嘗試紅旗中止"
    assert "completed" not in seen, (
        "紅旗中止寫入失敗後，場次被自動結束區塊降級成 completed —— "
        "醫師端的紅旗分流訊號被抹掉"
    )
    assert res.result is True, "critical 中止後應回 True 讓主迴圈收工"

    completed_to_patient = [
        m
        for m in res.cap.messages_of_type("session_status")
        if m["payload"].get("status") == "completed"
    ]
    assert not completed_to_patient, (
        "紅旗中止的場次對病患端送了 completed —— 病患會看到一般感謝頁，"
        "而不是「請告知現場醫護」"
    )
    # 中止路徑本身該做的事仍要做（SOAP 刻意不受 CAS 結果影響）
    assert res.soap_spy.called


def test_failed_abort_still_reports_terminal_to_patient(monkeypatch):
    """反向鎖：不得因為 EM-1 的 return 而讓病患端拿不到 aborted 終態。"""

    async def _update(db, redis, sid, new_status, previous, **kwargs):
        return new_status != "aborted_red_flag"

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1, MIN_PATIENT_TURNS_BEFORE_AUTO_END=1
        ),
        session_context=_ctx(),
        detector=StubDetector(alerts=[_critical_alert()]),
        update_status=_update,
    )
    aborts = [
        c
        for c in res.cap.localized_calls
        if c["code"] == "events.session.aborted_red_flag"
    ]
    assert aborts, "病患端沒收到 aborted_red_flag 終態"
    assert aborts[0]["extra"].get("status") == "aborted_red_flag"


# ══ EM-5：先標 `_terminated` 再送 ═══════════════════════
class _OrderingManager(_CaptureManager):
    """在每次對外推播的當下記錄 `session_context["_terminated"]`。"""

    def __init__(self, ctx: dict[str, Any]) -> None:
        super().__init__()
        self._ctx = ctx
        self.terminated_at_emit: list[tuple[str, Any]] = []

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> bool:
        if message.get("type") == "session_status":
            self.terminated_at_emit.append(
                ("patient_status", self._ctx.get("_terminated"))
            )
        return await super().send_to_session(session_id, message)

    async def send_localized_to_session(self, session_id, msg_type, code, **kw) -> bool:
        if msg_type == "session_status":
            self.terminated_at_emit.append(
                ("patient_status", self._ctx.get("_terminated"))
            )
        return await super().send_localized_to_session(
            session_id, msg_type, code, **kw
        )

    async def broadcast_localized_dashboard(self, msg_type, code, **kw) -> None:
        if msg_type == "session_status_changed":
            self.terminated_at_emit.append(
                ("dashboard", self._ctx.get("_terminated"))
            )
        await super().broadcast_localized_dashboard(msg_type, code, **kw)


def test_auto_conclude_marks_terminated_before_any_emit(monkeypatch):
    """自動結束：三個推播 await 的每一個當下，`_terminated` 都必須已經是 completed。

    否則那段窗口內背景 late-critical drain 看不到旗標，會再跑一整套 abort 收尾
    （病患同一秒收到 completed 與 aborted_red_flag 兩則終態）。
    """
    ctx = _ctx()
    mgr = _OrderingManager(ctx)
    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1, MIN_PATIENT_TURNS_BEFORE_AUTO_END=1
        ),
        session_context=ctx,
        detector=StubDetector(alerts=[]),
        manager=mgr,
    )
    assert res.result is True
    assert mgr.terminated_at_emit, "自動結束路徑沒有任何終態推播"
    assert all(v == "completed" for _, v in mgr.terminated_at_emit), (
        "自動結束在推播終態時 `_terminated` 還沒設好（先送後標）："
        f"{mgr.terminated_at_emit}"
    )


def test_red_flag_abort_marks_terminated_before_status_write(monkeypatch):
    """紅旗中止：連 `_update_session_status` 這個 await 之前就要標好。

    守衛與標記之間只要有 await，背景 drain 與硬上限 inline drain 就能同時通過
    守衛、各跑一套收尾。
    """
    ctx = _ctx()
    marked: list[Any] = []

    async def _update(db, redis, sid, new_status, previous, **kwargs):
        if new_status == "aborted_red_flag":
            marked.append(ctx.get("_terminated"))
        return True

    run_text_turn(
        monkeypatch,
        settings=make_settings(MAX_PATIENT_TURNS_HARD_CAP=10),
        session_context=ctx,
        detector=StubDetector(alerts=[_critical_alert()]),
        update_status=_update,
    )
    assert marked == ["aborted_red_flag"], (
        f"abort 在寫狀態時還沒標 `_terminated`（觀察到 {marked}）"
    )


# ══ SO-3：SOAP 派送時紅旗已 commit ═══════════════════════
class _LoggingDB(StubDB):
    """把 commit 記進共享事件序，用來驗跨路徑的先後順序。

    `commit_delay`：讓 commit 真的**在事件迴圈上讓出控制權**。沒有這一段，全部
    stub 都是「async def 但從不 await」，drain 的持久化會一路同步跑完 —— 測試就
    算把等待拿掉也照樣綠（為錯誤的理由通過）。真實環境的 DB round-trip 一定會
    讓出，所以這裡的 sleep 是在把 stub 拉回真實的排程行為，不是在造假。
    """

    def __init__(
        self, log: list[str], label: str, commit_delay: float = 0.0, **kw: Any
    ) -> None:
        super().__init__(**kw)
        self._log = log
        self._label = label
        self._commit_delay = commit_delay

    async def commit(self) -> None:
        if self._commit_delay:
            await asyncio.sleep(self._commit_delay)
        self._log.append(f"commit:{self._label}")
        await super().commit()


def test_hard_cap_inline_drain_persists_red_flag_before_soap(monkeypatch):
    """硬上限 inline drain 解析出 late-critical → SOAP 必須排在紅旗 commit 之後。

    偵測 0.05s 才回（晚於 gate 0.01s → 走背景 drain；早於 inline 上限 0.2s →
    硬上限這輪會 inline 解析到它）。SOAP 若排在 commit 之前，Celery worker 撈
    `red_flag_alerts` 時撈不到那面紅旗，報告會漏掉中止原因。
    """
    log: list[str] = []
    drain_db = _LoggingDB(log, "drain", commit_delay=0.02)
    main_db = _LoggingDB(log, "main")

    async def _soap(*, session_id: str) -> None:
        log.append("soap_dispatch")

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
            MAX_HARD_CAP_DRAIN_DEFERS=2,
        ),
        session_context=_ctx(),
        detector=StubDetector(alerts=[_critical_alert()], delay=0.05),
        db=main_db,
        drain_db=drain_db,
        soap_spy=_soap,
        drain_background=True,
    )

    assert res.result is True, "late-critical 應中止本輪並讓主迴圈收工"
    assert "soap_dispatch" in log, "late-critical 中止卻沒派 SOAP"
    assert "commit:drain" in log, (
        "遲到紅旗沒有被 drain 持久化（`_persist_and_emit_alert` 沒跑）"
    )
    assert log.index("commit:drain") < log.index("soap_dispatch"), (
        "SOAP 在紅旗 commit 之前就派了 —— Celery 撈不到觸發中止的那面紅旗。"
        f" 事件序：{log}"
    )


def test_hard_cap_inline_drain_still_finishes_when_drain_never_persists(monkeypatch):
    """保命線不可被新的等待卡住：drain 端沒有任何 alert 可持久化時仍要收尾。

    `_drain_late_red_flags` 的 finally 一定會放行等待方；若哪天有人把那個
    finally 拿掉，這個測試會因 `HARD_CAP_DRAIN_AWAIT_SECONDS` 逾時而變慢／
    仍然通過，但下一條（偵測器卡死走 MAX_HARD_CAP_DRAIN_DEFERS）會直接紅。
    """
    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
            MAX_HARD_CAP_DRAIN_DEFERS=2,
        ),
        session_context=_ctx(),
        detector=StubDetector(alerts=[_critical_alert()], delay=0.05),
        drain_background=True,
    )
    assert res.result is True
    assert res.soap_spy.called
