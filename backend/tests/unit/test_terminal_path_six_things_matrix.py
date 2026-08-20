"""終態路徑 × 六件事矩陣（CLAUDE.md 鐵律／不變式 #20）。

> 新增場次終態轉移時六件事一起做——改 status、派 SOAP、送病患端 `session_status`
> （**要帶 `extra`**）、廣播 dashboard、建醫師通知、設 `_terminated`。

這條鐵律過去是靠人肉記憶執行的，於是每加一條終態路徑就漏掉幾格：
主 abort 分支做全套、drain 分支只做兩件（場次 aborted 卻無 SOAP）、硬上限
inline drain 漏 `extra`（病患卡在對話頁）、閒置逾時整條沒有 SOAP、REST
`PUT /status` 六件只做一件。稽核的「測試缺口 #1」就是**沒有任何測試在看這張
矩陣**——每個缺陷都是各修各的，下一條新路徑一樣會漏。

本檔把矩陣寫成資料：

- `TERMINAL_PATHS` 列出每一條終態路徑與它每一格的**預期值**
  （`DONE` / `VIA_STATUS_HELPER` / `Skip(理由, 程式碼註解錨點)`）。
- `test_terminal_path_does_the_six_things` 逐格跑真正的路徑並比對觀測值。
- `test_skipped_cells_are_documented_in_code` 確認每個「刻意不做」的格子在
  程式碼裡有對應註解；把註解刪掉會讓測試紅，逼下一個人重新面對這個決定。
- `test_registry_covers_every_terminal_fanout_site` 是**跳閘器**：用 AST 掃出
  三個擁有終態轉移的模組裡所有「把場次寫成終態」的站點，與矩陣註冊的集合
  比對。新增一條終態路徑而沒有登記到這張矩陣 → 直接紅。
- `test_terminal_status_writes_route_through_the_fanout_entry` 問的是另一件事：
  直接寫終態的函式**有沒有把 fan-out 做完**（session_service 必須呼叫
  `_after_status_transition`；conversation_handler 一律只准經由
  `_update_session_status`）。「登記了」不等於「做完了」。
- `test_tripwire_trips_on_each_known_blind_spot` 是跳閘器的**自我測試**：把
  2026-08-21 敵意查證實測出的三種漏網寫法（＋兩種同族樣態）注入產品碼副本，
  證明現在真的會紅；`test_blind_spot_injections_are_red_under_the_old_shape_only_scanner`
  是它的反向釘子（證明這些樣態在舊版掃描器下確實一個都掃不到）。

新增終態路徑時：先在 `TERMINAL_PATHS` 加一列（含 `fanout_key`），再讓它綠。
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import AsyncMock

import pytest

from app.models.enums import SessionStatus as _SessionStatus

_BACKEND = pathlib.Path(__file__).resolve().parents[2]
_CH_PATH = _BACKEND / "app" / "websocket" / "conversation_handler.py"
_SS_PATH = _BACKEND / "app" / "services" / "session_service.py"
_ST_PATH = _BACKEND / "app" / "tasks" / "session_timeout.py"

# ── 六件事 ───────────────────────────────────────────────
STATUS = "改 status"
SOAP = "派 SOAP"
PATIENT = "送病患端 session_status（帶 extra.status）"
DASHBOARD = "廣播 dashboard"
NOTIFICATION = "建醫師通知"
TERMINATED = "設 _terminated"
SIX_THINGS = (STATUS, SOAP, PATIENT, DASHBOARD, NOTIFICATION, TERMINATED)

DONE = "done"
# 由 `_update_session_status`（WS）/ `update_status_static`（REST）代勞的格子：
# 這兩個 helper 在轉終態時會寫稽核並建 SESSION_COMPLETE / RED_FLAG 通知。
# 路徑層測試把它們 mock 掉了，所以這格改成「路徑有沒有走那個 helper」，
# helper 自身的行為由 test_update_session_status.py / test_rest_status_side_effects.py 守。
VIA_STATUS_HELPER = "via_status_helper"


@dataclass(frozen=True)
class Skip:
    """刻意不做的格子：必須說得出理由，且理由要寫在程式碼裡。"""

    reason: str
    doc_path: pathlib.Path
    doc_anchor: str

    def __repr__(self) -> str:  # 讓 pytest 的失敗訊息可讀
        return f"Skip({self.reason})"


@dataclass
class TerminalPath:
    name: str
    #  AST 跳閘器用的識別鍵（見 _terminal_fanout_sites）
    fanout_key: str
    cells: dict[str, Any]
    #  跑這條路徑並回傳 {六件事: 觀測值}；None＝只做文件檢查（跨行程路徑）
    exercise: Optional[Callable[[Any], dict[str, Any]]] = None
    notes: str = ""
    doc_only_anchors: list[tuple[pathlib.Path, str]] = field(default_factory=list)


# ══ 各路徑的 exercise ═══════════════════════════════════
def _ws_ctx(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": "user-1",
        "chief_complaint": "睪丸疼痛",
        "chief_complaint_display": "睪丸疼痛",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }


def _observe_ws(res, *, patient_code: str, status: str) -> dict[str, Any]:
    """把 WS driver 的 capture 轉成六件事觀測值。"""
    cap = res.cap
    # 病患端終態訊號：localized（帶 extra）或原始 payload（自動結束那條）
    patient_ok = any(
        c["code"] == patient_code and c["extra"].get("status") == status
        for c in cap.localized_calls
    ) or any(
        m["payload"].get("status") == status
        for m in cap.messages_of_type("session_status")
    )
    dashboard_ok = any(
        c["msg_type"] == "session_status_changed"
        and c["extra"].get("status") == status
        for c in cap.localized_dashboard_calls
    )
    status_ok = any(
        c.args[3] == status for c in res.update_status.call_args_list
    )
    return {
        STATUS: DONE if status_ok else "missing",
        SOAP: DONE if res.soap_spy.called else "missing",
        PATIENT: DONE if patient_ok else "missing",
        DASHBOARD: DONE if dashboard_ok else "missing",
        # 通知由 `_update_session_status` 內部建（本層已 mock）
        NOTIFICATION: VIA_STATUS_HELPER if status_ok else "missing",
        TERMINATED: DONE
        if res.session_context.get("_terminated") == status
        else "missing",
    }


def _ex_ws_end_session(monkeypatch) -> dict[str, Any]:
    from tests.unit.websocket.conftest import run_control_action

    res = run_control_action(
        monkeypatch,
        messages=[{"type": "control", "payload": {"action": "end_session"}}],
    )
    return _observe_ws(
        res, patient_code="events.session.ended_by_user", status="completed"
    )


def _ex_ws_auto_conclude(monkeypatch) -> dict[str, Any]:
    from tests.unit.websocket.conftest import (
        DEFAULT_SESSION_ID,
        StubDetector,
        make_settings,
        run_text_turn,
    )

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1, MIN_PATIENT_TURNS_BEFORE_AUTO_END=1
        ),
        session_context=_ws_ctx(DEFAULT_SESSION_ID),
        detector=StubDetector(alerts=[]),
    )
    assert res.result is True
    return _observe_ws(
        res, patient_code="events.session.completed_hpi", status="completed"
    )


def _critical_alert():
    from tests.unit.websocket.conftest import make_alert

    return make_alert(
        severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
    )


def _ex_ws_abort_main(monkeypatch) -> dict[str, Any]:
    from tests.unit.websocket.conftest import (
        DEFAULT_SESSION_ID,
        StubDetector,
        make_settings,
        run_text_turn,
    )

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(MAX_PATIENT_TURNS_HARD_CAP=10),
        session_context=_ws_ctx(DEFAULT_SESSION_ID),
        detector=StubDetector(alerts=[_critical_alert()]),
    )
    return _observe_ws(
        res, patient_code="events.session.aborted_red_flag", status="aborted_red_flag"
    )


def _ex_ws_abort_drain(monkeypatch) -> dict[str, Any]:
    """偵測 0.1s 才回（晚於 gate）→ 走背景 late-critical drain。"""
    from tests.unit.websocket.conftest import (
        DEFAULT_SESSION_ID,
        StubDetector,
        make_settings,
        run_text_turn,
    )

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(MAX_PATIENT_TURNS_HARD_CAP=10),
        session_context=_ws_ctx(DEFAULT_SESSION_ID),
        detector=StubDetector(alerts=[_critical_alert()], delay=0.1),
        drain_background=True,
    )
    return _observe_ws(
        res, patient_code="events.session.aborted_red_flag", status="aborted_red_flag"
    )


def _ex_ws_abort_hard_cap_inline(monkeypatch) -> dict[str, Any]:
    """硬上限收尾前 inline 解析出 late-critical。"""
    from tests.unit.websocket.conftest import (
        DEFAULT_SESSION_ID,
        StubDetector,
        make_settings,
        run_text_turn,
    )

    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
        ),
        session_context=_ws_ctx(DEFAULT_SESSION_ID),
        detector=StubDetector(alerts=[_critical_alert()], delay=0.05),
        drain_background=True,
    )
    assert res.result is True
    return _observe_ws(
        res, patient_code="events.session.aborted_red_flag", status="aborted_red_flag"
    )


def _ex_ws_idle_timeout(monkeypatch) -> dict[str, Any]:
    import asyncio

    import app.websocket.conversation_handler as ch
    from tests.unit.websocket.conftest import (
        DEFAULT_SESSION_ID,
        FakeRedis,
        StubDB,
        _CaptureManager,
    )

    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(ch, "_update_session_status", update_status)
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)
    monkeypatch.setattr(
        ch, "_broadcast_dashboard_queue_and_stats", AsyncMock(return_value=None)
    )

    asyncio.run(
        ch._finalize_idle_timeout(
            db=StubDB(),
            redis=FakeRedis(),
            session_id=DEFAULT_SESSION_ID,
            idle_timeout_seconds=600,
        )
    )
    res = SimpleNamespace(
        cap=cap,
        update_status=update_status,
        soap_spy=soap_spy,
        session_context={},
    )
    return _observe_ws(
        res, patient_code="events.session.idle_timeout", status="completed"
    )


def _rest_wiring(monkeypatch):
    """REST 兩條路徑共用的依賴替身（回傳 spy bundle）。"""
    import uuid

    import app.cache.redis_client as redis_client
    import app.websocket.conversation_handler as ch
    import app.websocket.dashboard_handler as dash
    from app.services import audit_log_service as als
    from app.services import notification_service as ns
    from app.services import session_service as ss
    from app.websocket import connection_manager as cm

    dashboard_calls: list[dict[str, Any]] = []

    class _Mgr:
        async def broadcast_localized_dashboard(
            self, msg_type, code, params=None, severity="info", extra=None
        ) -> None:
            dashboard_calls.append(
                {"msg_type": msg_type, "extra": extra or {}}
            )

    monkeypatch.setattr(cm, "manager", _Mgr())

    soap_calls: list[str] = []

    async def _soap(*, session_id: str) -> None:
        soap_calls.append(session_id)

    monkeypatch.setattr(ch, "_generate_soap_report_async", _soap)

    queue_calls: list[Any] = []

    async def _queue(db, redis) -> None:
        queue_calls.append(db)

    monkeypatch.setattr(dash, "broadcast_queue_and_stats", _queue)

    class _R:
        async def hset(self, *a):
            return 1

        async def expire(self, *a):
            return True

    async def _get_redis():
        return _R()

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)

    async def _log(db, **kwargs):
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(als.AuditLogService, "log", _log)

    notif_calls: list[Any] = []

    async def _notify(db, *, session_id, doctor_id, patient_id):
        notif_calls.append(doctor_id)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(ns.NotificationService, "notify_session_complete", _notify)

    async def _no_auth(db, session, current_user):
        return None

    monkeypatch.setattr(ss, "_authorize_session_access", _no_auth)

    return SimpleNamespace(
        dashboard_calls=dashboard_calls,
        soap_calls=soap_calls,
        queue_calls=queue_calls,
        notif_calls=notif_calls,
    )


def _rest_fakes(monkeypatch, status_in):
    import uuid

    from app.models.enums import SessionStatus, UserRole
    from app.services.session_service import SessionService

    session = SimpleNamespace(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        doctor_id=uuid.uuid4(),
        status=status_in,
        language="zh-TW",
        started_at=None,
        completed_at=None,
        updated_at=None,
        duration_seconds=None,
        previous_status=None,
    )

    async def _get_by_id(db, session_id):
        return session

    monkeypatch.setattr(SessionService, "get_by_id", staticmethod(_get_by_id))

    class _DB:
        def __init__(self) -> None:
            self.commits = 0

        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

        async def flush(self):
            return None

        async def commit(self):
            self.commits += 1

    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
    return session, _DB(), user, SessionStatus


def _observe_rest(w, *, status: str) -> dict[str, Any]:
    dashboard_ok = any(
        c["msg_type"] == "session_status_changed"
        and c["extra"].get("status") == status
        for c in w.dashboard_calls
    )
    return {
        STATUS: DONE,
        SOAP: DONE if w.soap_calls else "missing",
        PATIENT: "missing",  # 架構限制，見矩陣的 Skip
        DASHBOARD: DONE if dashboard_ok else "missing",
        NOTIFICATION: DONE if w.notif_calls else "missing",
        TERMINATED: "missing",  # 架構限制，見矩陣的 Skip
    }


def _ex_rest_completed(monkeypatch) -> dict[str, Any]:
    import asyncio

    from app.services.session_service import SessionService

    w = _rest_wiring(monkeypatch)
    session, db, user, SessionStatus = _rest_fakes(
        monkeypatch, _SessionStatus.IN_PROGRESS
    )
    asyncio.run(
        SessionService().update_status(
            db,
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=user,
        )
    )
    return _observe_rest(w, status="completed")


def _ex_rest_cancelled(monkeypatch) -> dict[str, Any]:
    import asyncio

    from app.services.session_service import SessionService

    w = _rest_wiring(monkeypatch)
    session, db, user, SessionStatus = _rest_fakes(
        monkeypatch, _SessionStatus.IN_PROGRESS
    )
    asyncio.run(
        SessionService().update_status(
            db,
            session_id=session.id,
            new_status=SessionStatus.CANCELLED,
            current_user=user,
        )
    )
    obs = _observe_rest(w, status="cancelled")
    obs[SOAP] = "missing" if not w.soap_calls else DONE
    obs[NOTIFICATION] = "missing" if not w.notif_calls else DONE
    return obs


def _ex_rest_language_switch(monkeypatch) -> dict[str, Any]:
    import asyncio

    from app.models.enums import SessionStatus, UserRole
    from app.services.session_service import SessionService

    w = _rest_wiring(monkeypatch)
    session, db, user, _ = _rest_fakes(monkeypatch, SessionStatus.IN_PROGRESS)
    user.role = UserRole.PATIENT
    asyncio.run(
        SessionService.end_for_language_switch(
            db,
            session_id=session.id,
            to_language="en-US",
            current_user=user,
        )
    )
    obs = _observe_rest(w, status="cancelled")
    obs[SOAP] = "missing" if not w.soap_calls else DONE
    obs[NOTIFICATION] = "missing" if not w.notif_calls else DONE
    return obs


# ══ 矩陣本體 ═══════════════════════════════════════════
_WS_TERMINATED_SKIP_IDLE = Skip(
    "閒置看門狗 task 拿不到主迴圈的 session_context；收尾後直接 close(4000)，"
    "沒有下一輪訊息需要被旗標攔下",
    _CH_PATH,
    "本函式跑在閒置看門狗 task 裡，拿不到主迴圈的 `session_context`",
)
_REST_PATIENT_SKIP = Skip(
    "病患 WS 連線在 ConnectionManager 的行程本地 dict，REST 行程碰不到；"
    "全碼庫唯一的跨行程橋接只 fan-out 給 dashboard",
    _SS_PATH,
    "做不到（架構限制，刻意省略）",
)
_REST_TERMINATED_SKIP = Skip(
    "`_terminated` 是 conversation_handler 的行程內旗標，REST 行程沒有那份 context",
    _SS_PATH,
    "REST 行程沒有那份 context",
)
_CANCELLED_SOAP_SKIP = Skip(
    "cancelled 不出報告是產品決策（P7），與逾時清理 / 病患關瀏覽器同一政策",
    _SS_PATH,
    "cancelled **刻意不派**",
)
_CANCELLED_NOTIF_SKIP = Skip(
    "NotificationType 沒有「場次被取消」語意的類型，新增列舉值屬獨立需求",
    _SS_PATH,
    "刻意不建通知",
)

TERMINAL_PATHS: list[TerminalPath] = [
    TerminalPath(
        name="ws:control end_session → completed",
        fanout_key="conversation_handler:conversation_websocket:completed",
        exercise=_ex_ws_end_session,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: DONE,
        },
    ),
    TerminalPath(
        name="ws:自動結束（HPI 達標／硬上限）→ completed",
        fanout_key="conversation_handler:_handle_text_message:completed",
        exercise=_ex_ws_auto_conclude,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: DONE,
        },
    ),
    TerminalPath(
        name="ws:主 critical 紅旗中止 → aborted_red_flag",
        fanout_key="conversation_handler:_finalize_red_flag_abort:aborted_red_flag",
        exercise=_ex_ws_abort_main,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: DONE,
        },
    ),
    TerminalPath(
        name="ws:背景 late-critical drain → aborted_red_flag",
        fanout_key="conversation_handler:_finalize_red_flag_abort:aborted_red_flag",
        exercise=_ex_ws_abort_drain,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: DONE,
        },
    ),
    TerminalPath(
        name="ws:硬上限 inline drain 的 late-critical → aborted_red_flag",
        fanout_key="conversation_handler:_finalize_red_flag_abort:aborted_red_flag",
        exercise=_ex_ws_abort_hard_cap_inline,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: DONE,
        },
    ),
    TerminalPath(
        name="ws:閒置逾時 → completed",
        fanout_key="conversation_handler:_finalize_idle_timeout:completed",
        exercise=_ex_ws_idle_timeout,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: DONE,
            DASHBOARD: DONE,
            NOTIFICATION: VIA_STATUS_HELPER,
            TERMINATED: _WS_TERMINATED_SKIP_IDLE,
        },
    ),
    TerminalPath(
        name="rest:PUT /sessions/{id}/status → completed",
        fanout_key="session_service:update_status",
        exercise=_ex_rest_completed,
        cells={
            STATUS: DONE,
            SOAP: DONE,
            PATIENT: _REST_PATIENT_SKIP,
            DASHBOARD: DONE,
            NOTIFICATION: DONE,
            TERMINATED: _REST_TERMINATED_SKIP,
        },
    ),
    TerminalPath(
        name="rest:PUT /sessions/{id}/status → cancelled",
        fanout_key="session_service:update_status",
        exercise=_ex_rest_cancelled,
        cells={
            STATUS: DONE,
            SOAP: _CANCELLED_SOAP_SKIP,
            PATIENT: _REST_PATIENT_SKIP,
            DASHBOARD: DONE,
            NOTIFICATION: _CANCELLED_NOTIF_SKIP,
            TERMINATED: _REST_TERMINATED_SKIP,
        },
    ),
    TerminalPath(
        name="rest:POST /sessions/{id}/end-for-language-switch → cancelled",
        fanout_key="session_service:end_for_language_switch",
        exercise=_ex_rest_language_switch,
        cells={
            STATUS: DONE,
            SOAP: _CANCELLED_SOAP_SKIP,
            PATIENT: _REST_PATIENT_SKIP,
            DASHBOARD: DONE,
            NOTIFICATION: _CANCELLED_NOTIF_SKIP,
            TERMINATED: _REST_TERMINATED_SKIP,
        },
    ),
    TerminalPath(
        name="celery:session_timeout 60 分鐘逾時 → cancelled",
        fanout_key="session_timeout:_async_check:cancelled",
        # 跑在 Celery worker 行程，需要真 DB session factory 才跑得起來；
        # 這一列只驗「六件事逐項評估有寫進模組 docstring」，行為由
        # tests/unit/tasks 的既有測試守。
        exercise=None,
        cells={
            STATUS: DONE,
            SOAP: Skip(
                "cancelled 不派 SOAP 是既定政策（P7）",
                _ST_PATH,
                "cancelled 不派 SOAP 是既定政策",
            ),
            PATIENT: Skip(
                "Celery 行程碰不到 API 行程的 in-memory 連線表",
                _ST_PATH,
                "沒有 per-session 的",
            ),
            DASHBOARD: DONE,
            NOTIFICATION: Skip(
                "NotificationType 沒有「場次逾時取消」語意的類型",
                _ST_PATH,
                "沒有「場次逾時取消」語意的類型",
            ),
            TERMINATED: Skip(
                "Celery 任務沒有 session_context，也沒有主迴圈要中止",
                _ST_PATH,
                "Celery 任務沒有該 context",
            ),
        },
    ),
]


# ══ 測試 ═══════════════════════════════════════════════
@pytest.mark.parametrize(
    "path", TERMINAL_PATHS, ids=[p.name for p in TERMINAL_PATHS]
)
def test_terminal_path_does_the_six_things(monkeypatch, path: TerminalPath):
    """逐路徑跑一次，比對六件事的每一格。"""
    if path.exercise is None:
        pytest.skip("跨行程路徑：只做文件檢查，見 test_skipped_cells_are_documented")

    observed = path.exercise(monkeypatch)
    assert set(observed) == set(SIX_THINGS)

    failures: list[str] = []
    for thing in SIX_THINGS:
        expected = path.cells[thing]
        got = observed[thing]
        if isinstance(expected, Skip):
            # 刻意不做的格子：觀測到「有做」反而要提醒（政策改了就要改矩陣）
            if got not in ("missing",):
                failures.append(
                    f"  [{thing}] 矩陣說刻意不做（{expected.reason}），"
                    f"但實際做了 → 政策改了就要同步更新矩陣"
                )
            continue
        if got != expected:
            failures.append(f"  [{thing}] 預期 {expected}，實際 {got}")
    assert not failures, (
        f"終態路徑「{path.name}」的六件事矩陣不符（不變式 #20）：\n"
        + "\n".join(failures)
    )


def test_skipped_cells_are_documented_in_code():
    """每一格「刻意不做」都要在程式碼裡說得出理由。

    註解被刪掉 → 這裡紅。這是刻意的：那些格子是架構限制與產品決策的結論，
    下一個人看到空格時必須看得到「為什麼」，否則只會當成漏做而亂補。
    """
    missing: list[str] = []
    for path in TERMINAL_PATHS:
        for thing, cell in path.cells.items():
            if not isinstance(cell, Skip):
                continue
            text = cell.doc_path.read_text(encoding="utf-8")
            if cell.doc_anchor not in text:
                missing.append(
                    f"  {path.name} / {thing}："
                    f"{cell.doc_path.name} 找不到註解錨點 {cell.doc_anchor!r}"
                )
    assert not missing, "「刻意不做」的格子失去程式碼註解：\n" + "\n".join(missing)


# ── AST 跳閘器 ─────────────────────────────────────────
# 2026-08-21 EM-7：舊版跳閘器只認**三種寫死的形狀**，敵意查證（verify_claudemd.md
# B5）實測出三個盲點——三種新增終態路徑的寫法都不會跳閘：
#   ① `session_service` 直接 `session.status = SessionStatus.COMPLETED` 而**沒呼叫**
#      `_after_status_transition`（舊版 session_service 那格認的是 fan-out 呼叫，
#      繞過它就整個看不見）。這正是 #20 這條鐵律要防的失敗樣態：終態卻沒有 SOAP。
#   ② `_update_session_status(..., new_status="completed", ...)`（keyword arg —
#      舊版只讀 `args[3]`）。
#   ③ 用常數變數 `_update_session_status(..., _TERMINAL, ...)`（舊版只認
#      `ast.Constant` 字面值）。
#
# 現行掃描器的設計原則：
#   - **形狀是「寫終態」而不是「呼叫某個 helper」**：直接對 `.status` 賦值
#     （含 tuple/list 多重指派、鏈式、AnnAssign）、`.values(status=…)` 與
#     `.values({"status": …})` 的 SQLAlchemy UPDATE、`setattr(obj, "status", …)`、
#     以及呼叫低階狀態寫入 helper 一起認，keyword / positional 都吃。
#   - **狀態值解析得出來就解析，解析不出來一律當成終態**（保守側）。函式參數、
#     dict 查表、f-string 都會落在「解析不出來」→ 產生 `<unresolved>` 站點 → 未登記
#     → 紅。放行一個看不懂的狀態值＝把「終態卻沒有 SOAP」放回來，成本不對稱。
#   - **只認 DB 寫入的形狀，不認訊息 payload**：`extra={"status": "completed"}`
#     這種 dict 字面值是送給前端的訊息，不是狀態轉移。曾經把 dict 字面值一起掃，
#     結果 `conversation_websocket` 的 dashboard 廣播 payload 也被判成終態寫入
#     ——**噪音會讓下一個人把跳閘器關掉**，比漏掉一種形狀更危險。
#     所以裸 dict 字面值一律不看，只有**掛在 `.values()` 位置引數上**的 dict 才算。
#
# ⚠️ **掃描器的覆蓋面是「形狀清單」，不是「所有寫法」**——這一點永遠成立，別因為
# 下面的注入清單變長就當它封閉了。目前**刻意留著不認**的兩類（2026-08-21 複驗實測
# 逃得掉，但都判斷為「噪音成本 > 覆蓋收益」）：
#   - `.values(**payload)`（`kw.arg is None`）：`_update_session_status` 自己就是
#     這樣寫的（`conversation_handler` 組完 `values` dict 再展開），認了會讓**寫入
#     helper 本身**變成一個 `<unresolved>` 站點，等於天天要人去看一個假警報。
#   - `session.__dict__[…]`／`vars(session)[…]`／`object.__setattr__`／把 helper
#     綁到別的名字再呼叫／`db.execute(text("UPDATE …"))` 裸 SQL：這些是**刻意規避**，
#     不是有人會不小心寫出來的慣用法。跳閘器防的是手滑，不是防內鬼。
#   **所以最後一道防線仍然是人**：新增終態路徑先在 `TERMINAL_PATHS` 補一列。
_TERMINAL_STATUSES = {"completed", "aborted_red_flag", "cancelled"}
#  狀態值靜態解析不出來時的佔位（保守：一律當成終態寫入，要求登記）
_UNRESOLVED = "<unresolved>"
#  低階「狀態寫入 helper」→ 狀態參數的 positional index（keyword 一律吃 `new_status`）
_STATUS_WRITER_CALLS: dict[str, int] = {
    # conversation_handler：WS 那條的唯一狀態寫入點（CAS）
    "_update_session_status": 3,
    # session_service：REST 那條的資料層寫入點
    "update_status_static": 2,
}
#  REST 的 fan-out 入口：呼叫它＝正在對某次狀態轉移做附帶效應
_FANOUT_ENTRY = "_after_status_transition"
#  「直接寫終態」會出現的 keyword 名稱（`.values(status=…)` / `(new_status=…)`）
_STATUS_KEYWORDS = ("status", "new_status")
#  直接對 model 欄位賦值的形狀（`session.status = …`）
_STATUS_ATTR = "status"

# 掃到終態寫入、但**刻意**不在這張矩陣裡各佔一列的站點。逐筆寫理由——新增一筆
# 等於宣告「我確認這個站點的六件事由別人做完了」，跟 `Skip` 同一個舉證標準。
_TERMINAL_WRITE_EXEMPTIONS: dict[str, str] = {
    "session_service:update_status_static": (
        "純資料層 helper：只寫 status／started_at／completed_at／duration 與稽核，"
        "**刻意不做** fan-out。唯一呼叫端 `SessionService.update_status` 在 "
        "`db.commit()` 之後才呼叫 `_after_status_transition`（EM-2 時序鐵律：附帶"
        "效應必須在 commit 之後，否則 Celery worker 在另一個連線上還讀得到 "
        "in_progress）。那條路徑已登記為 fanout_key='session_service:update_status'，"
        "六件事在該列逐格回答過；這裡再列一次只會變成同一條路徑的重複登記。"
    ),
}


def _enclosing_functions(tree: ast.AST):
    """yield (最內層函式名, node)，涵蓋巢狀函式（`_finalize_red_flag_abort` 是
    `_handle_text_message` 的內部函式）。"""

    def walk(node: ast.AST, fn: str) -> Any:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from walk(child, child.name)
            else:
                yield fn, child
                yield from walk(child, fn)

    yield from walk(tree, "<module>")


def _name_bindings(tree: ast.AST) -> dict[str, list[ast.expr]]:
    """name → 它在本模組（含函式內）被指派過的所有 value node。

    同一個名字有多個指派時由 `_resolve_status` 決定：全部解析成同一個值才採信，
    否則回 `_UNRESOLVED`（保守側）。函式參數不會出現在這裡，所以參數一律解析不出來。
    """
    out: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out.setdefault(target.id, []).append(value)
    return out


def _resolve_status(
    node: ast.expr, binds: dict[str, list[ast.expr]], depth: int = 0
) -> str | None:
    """回傳終態字串 / `_UNRESOLVED` / None（None＝**證明得出**不是終態）。

    認得的形狀：字面值字串、`SessionStatus.COMPLETED`、`SessionStatus.COMPLETED.value`、
    以及指向上述任一形狀的常數變數（可跨一層以上，遞迴深度上限 4）。
    """
    if depth > 4:
        return _UNRESOLVED
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value if node.value in _TERMINAL_STATUSES else None
        # None / int / bool：不是狀態字串，證明得出不是終態
        return None
    if isinstance(node, ast.Attribute):
        if node.attr == "value":  # SessionStatus.COMPLETED.value
            return _resolve_status(node.value, binds, depth + 1)
        if isinstance(node.value, ast.Name) and node.value.id.endswith("SessionStatus"):
            attr = node.attr.lower()
            return attr if attr in _TERMINAL_STATUSES else None
        return _UNRESOLVED
    if isinstance(node, ast.Name):
        bound = binds.get(node.id)
        if not bound:
            return _UNRESOLVED
        resolved = {_resolve_status(b, binds, depth + 1) for b in bound}
        return resolved.pop() if len(resolved) == 1 else _UNRESOLVED
    return _UNRESOLVED


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _values_positional_status(
    call: ast.Call, binds: dict[str, list[ast.expr]]
) -> str | None:
    """`.values({"status": …})` 這種**位置引數 dict** 的狀態值。

    為什麼要認（2026-08-21 敵意複驗實測逃逸）：`Update.values()` 吃 dict 是
    SQLAlchemy 文件寫明的用法，欄位名要動態組時本來就會這樣寫——它是**合法慣用法
    而不是刻意規避**，所以最可能被無辜寫出來，也最該被跳閘器接住。

    只看掛在 `.values()` 位置引數上的 dict；裸 dict 字面值一律不看（訊息 payload
    的噪音問題見上方設計原則）。key 不是字面值字串（`{**payload}` 的 key 是 None、
    或變數 key）時無法證明裡面沒有 status → 保守回 `_UNRESOLVED`。
    """
    if not call.args:
        return None
    first = call.args[0]
    if not isinstance(first, ast.Dict):
        # `.values(payload)`：拿不到內容，不能證明它沒寫 status。
        return _UNRESOLVED
    unresolved = False
    for key, value in zip(first.keys, first.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            unresolved = True  # `{**payload}` / 變數 key
            continue
        if key.value not in _STATUS_KEYWORDS:
            continue
        status = _resolve_status(value, binds)
        if status is not None:
            return status
    return _UNRESOLVED if unresolved else None


def _setattr_status_value(
    call: ast.Call, binds: dict[str, list[ast.expr]]
) -> ast.expr | None | str:
    """`setattr(obj, "status", value)` → 回傳 value node；不是狀態寫入回 None。

    屬性名解析不出來（`setattr(obj, attr, v)` 的欄位表迴圈）時回 `_UNRESOLVED`：
    保守側同上——放行一個看不懂的屬性名等於把「終態卻沒有 SOAP」放回來。要自證
    「我寫的不是 status」，把屬性名寫成字面值或模組常數即可。
    """
    if len(call.args) < 3:
        return None
    attr = call.args[1]
    if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
        return call.args[2] if attr.value == _STATUS_ATTR else None
    if isinstance(attr, ast.Name):
        bound = binds.get(attr.id)
        resolved = {
            b.value
            for b in bound or []
            if isinstance(b, ast.Constant) and isinstance(b.value, str)
        }
        if len(resolved) == 1 and len(bound or []) == 1:
            return call.args[2] if resolved.pop() == _STATUS_ATTR else None
    return _UNRESOLVED


def _assign_targets(target: ast.expr, value: ast.expr | None):
    """展開一個 assign target，yield `(葉節點 target, 對應的 value 或 None)`。

    為什麼需要這個（2026-08-21 敵意複驗 ⑪，實測不跳閘）：
    `session.status, session.completed_at = SessionStatus.COMPLETED, now`
    的 target 是一個 `ast.Tuple`，舊碼的迴圈只認 `ast.Attribute`，整條 tuple 直接
    被略過 → **完全掃不到**。而這是「同時寫 status 與 completed_at」最自然的慣用法
    （產品碼裡 `_finalize_*` 那類函式本來就是一次寫兩三個欄位），不是刻意規避——
    也正是不變式 #20 要防的「終態卻沒有 SOAP」樣態。

    value 對不上時回 `None`，呼叫端一律當 `_UNRESOLVED`（保守側，見 `_terminal_writes`）：
    `session.status, x = _decide()` 這種 unpack 靜態解析不出狀態值，放行的成本
    （漏掉一個終態轉移）遠高於誤判的成本（多登記一格）。
    """
    if isinstance(target, ast.Starred):
        # `a, *rest = ...`：rest 綁的是**剩餘元素**，對不到單一 value。
        yield from _assign_targets(target.value, None)
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        elts = target.elts
        if (
            isinstance(value, (ast.Tuple, ast.List))
            and len(value.elts) == len(elts)
            and not any(isinstance(e, ast.Starred) for e in elts)
        ):
            values: list[ast.expr | None] = list(value.elts)
        else:
            values = [None] * len(elts)
        for sub_target, sub_value in zip(elts, values):
            yield from _assign_targets(sub_target, sub_value)
        return
    yield target, value


@dataclass(frozen=True)
class _Write:
    """一個「把場次寫成終態」的站點。"""

    function: str
    status: str  # 終態字串或 `_UNRESOLVED`
    shape: str  # 給失敗訊息看的樣態描述
    direct: bool  # True＝直接寫 DB 欄位（沒有經過任何狀態寫入 helper）


def _terminal_writes(path: pathlib.Path) -> list[_Write]:
    """掃出一個模組裡所有「把場次寫成終態」的站點。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    binds = _name_bindings(tree)
    writes: list[_Write] = []

    for fn, node in _enclosing_functions(tree):
        # ① 直接對 model 欄位賦值：`session.status = SessionStatus.COMPLETED`
        #    含鏈式（`a = b.status = X`）與 **tuple/list 多重指派**
        #    （`session.status, session.completed_at = SessionStatus.COMPLETED, now`）。
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                multi = isinstance(target, (ast.Tuple, ast.List))
                for leaf, leaf_value in _assign_targets(target, value):
                    if not (
                        isinstance(leaf, ast.Attribute) and leaf.attr == _STATUS_ATTR
                    ):
                        continue
                    status = (
                        _UNRESOLVED
                        if leaf_value is None
                        else _resolve_status(leaf_value, binds)
                    )
                    if status is not None:
                        shape = (
                            ".status, … = <終態>, …（tuple 多重指派）"
                            if multi
                            else ".status = <終態>"
                        )
                        writes.append(_Write(fn, status, shape, True))
            continue

        if not isinstance(node, ast.Call):
            continue
        called = _called_name(node.func)

        # ② SQLAlchemy UPDATE：`.values(status=SessionStatus.CANCELLED, ...)`
        #    keyword 與**位置引數 dict**（`.values({"status": …})`）都吃。
        if called == "values":
            for kw_name in _STATUS_KEYWORDS:
                value = _keyword_value(node, kw_name)
                if value is None:
                    continue
                status = _resolve_status(value, binds)
                if status is not None:
                    writes.append(
                        _Write(fn, status, f".values({kw_name}=<終態>)", True)
                    )
            dict_status = _values_positional_status(node, binds)
            if dict_status is not None:
                writes.append(
                    _Write(fn, dict_status, '.values({"status": <終態>})', True)
                )

        # ②b `setattr(session, "status", SessionStatus.COMPLETED)`——與 ① 同一件事，
        #     只是走動態屬性名。一般寫法（欄位表驅動時很自然），不是規避。
        if called == "setattr":
            value = _setattr_status_value(node, binds)
            if value is not None:
                status = (
                    _UNRESOLVED
                    if isinstance(value, str)
                    else _resolve_status(value, binds)
                )
                if status is not None:
                    writes.append(
                        _Write(fn, status, 'setattr(…, "status", <終態>)', True)
                    )

        # ③ 呼叫低階狀態寫入 helper（keyword 與 positional 都吃；
        #    連參數都拿不到時保守當成 `_UNRESOLVED`）
        if called in _STATUS_WRITER_CALLS:
            index = _STATUS_WRITER_CALLS[called]
            value = _keyword_value(node, "new_status")
            if value is None and len(node.args) > index:
                value = node.args[index]
            status = _UNRESOLVED if value is None else _resolve_status(value, binds)
            if status is not None:
                writes.append(_Write(fn, status, f"{called}(<終態>)", False))

        # ④ REST 的 fan-out 入口：呼叫它就是一次終態轉移的附帶效應
        if called == _FANOUT_ENTRY:
            writes.append(_Write(fn, _UNRESOLVED, f"{_FANOUT_ENTRY}()", False))

    return writes


def _terminal_fanout_sites(
    ch_path: pathlib.Path | None = None,
    ss_path: pathlib.Path | None = None,
    st_path: pathlib.Path | None = None,
) -> set[str]:
    """掃出「把場次寫成終態」的站點，轉成註冊表用的 key。

    三個模組的 key 形狀沿用既有註冊表：
    - conversation_handler：`conversation_handler:<函式>:<終態>`
    - session_service：`session_service:<函式>`（REST 那格不帶狀態——同一個函式可能
      同時寫 status 又呼叫 fan-out 入口，帶狀態只會把一條路徑拆成兩把鑰匙）
    - tasks/session_timeout：`session_timeout:<函式>:<終態>`

    path 參數只給自我測試用（掃注入過的副本），產品掃描一律用預設路徑。
    """
    sites: set[str] = set()
    for write in _terminal_writes(ch_path or _CH_PATH):
        sites.add(f"conversation_handler:{write.function}:{write.status}")
    for write in _terminal_writes(ss_path or _SS_PATH):
        sites.add(f"session_service:{write.function}")
    for write in _terminal_writes(st_path or _ST_PATH):
        sites.add(f"session_timeout:{write.function}:{write.status}")
    return sites


def test_registry_covers_every_terminal_fanout_site():
    """跳閘器：碼庫裡每一個終態轉移點都必須登記在這張矩陣裡。

    新增一條終態路徑（再加一個 `_update_session_status(..., "completed", ...)`
    的呼叫點、或直接 `session.status = SessionStatus.COMPLETED`）而忘記登記 →
    這裡直接紅，逼你先在 `TERMINAL_PATHS` 補一列並回答六件事各要不要做。
    這正是稽核「測試缺口 #1」要的東西。
    """
    registered = {p.fanout_key for p in TERMINAL_PATHS}
    exempted = set(_TERMINAL_WRITE_EXEMPTIONS)
    found = _terminal_fanout_sites()

    unregistered = found - registered - exempted
    stale = registered - found

    assert not unregistered, (
        "發現未登記在六件事矩陣裡的終態轉移點：\n  "
        + "\n  ".join(sorted(unregistered))
        + "\n請在 TERMINAL_PATHS 補一列，逐項回答六件事要不要做。"
        + "\n（狀態值是 <unresolved> 表示靜態解析不出來——跳閘器一律保守當成終態；"
        "若它真的寫不出終態，把狀態值寫成字面值或模組常數即可自證。）"
    )
    assert not stale, (
        "矩陣登記了已不存在的終態轉移點（路徑被刪或改名）：\n  "
        + "\n  ".join(sorted(stale))
    )


def test_terminal_write_exemptions_are_real_and_justified():
    """例外表不是後門：每一筆都要（a）真的還存在、（b）說得出理由。

    路徑被改名／刪掉之後留下的死條目會靜默擴大例外面——下一個人加同名函式就白白
    被放行。理由字數門檻沿用 #22 的舉證慣例。
    """
    found = _terminal_fanout_sites()
    problems: list[str] = []
    for key, reason in _TERMINAL_WRITE_EXEMPTIONS.items():
        if key not in found:
            problems.append(f"  {key}：掃不到這個站點了（改名或刪除？）請移除此例外")
        if len(reason) < 40:
            problems.append(f"  {key}：理由太短（{len(reason)} 字），要說得出誰做完六件事")
    assert not problems, "終態寫入例外表有問題：\n" + "\n".join(problems)


def test_terminal_status_writes_route_through_the_fanout_entry():
    """盲點①的正面守衛：**直接寫終態**的函式必須自己把 fan-out 做完。

    `test_registry_covers_every_terminal_fanout_site` 只問「有沒有登記」；這條問的是
    「有沒有 fan-out」——兩者防的是不同的手滑：

    - session_service：任何直接寫終態（`.status =` / `.values(status=)`）的函式，
      必須在同一個函式裡呼叫 `_after_status_transition`（REST 那條的 fan-out 入口，
      派 SOAP / 廣播 dashboard / 建通知都在它裡面）。查證報告實測的樣態
      「`session.status = SessionStatus.COMPLETED` 但沒呼叫 `_after_status_transition`」
      在這裡就會紅，而且錯誤訊息直接指向缺的那件事。
    - conversation_handler：WS 那條**只准**經由 `_update_session_status` 寫狀態
      （CAS ＋ 稽核 ＋ 通知都在裡面）。繞過它直接改欄位＝繞過 CAS，EM-4 的
      「CAS 回傳值必須被尊重」整條就失效。
    """
    problems: list[str] = []

    ss_tree = ast.parse(_SS_PATH.read_text(encoding="utf-8"))
    fanout_callers = {
        fn
        for fn, node in _enclosing_functions(ss_tree)
        if isinstance(node, ast.Call) and _called_name(node.func) == _FANOUT_ENTRY
    }
    for write in _terminal_writes(_SS_PATH):
        if not write.direct or write.function in fanout_callers:
            continue
        if f"session_service:{write.function}" in _TERMINAL_WRITE_EXEMPTIONS:
            continue
        problems.append(
            f"  session_service.{write.function}：{write.shape} 寫了終態"
            f"（{write.status}）卻沒有呼叫 {_FANOUT_ENTRY}()"
            " → 場次會變成終態但沒有 SOAP／沒有 dashboard 廣播／沒有醫師通知"
            "（不變式 #20）"
        )

    for write in _terminal_writes(_CH_PATH):
        if not write.direct:
            continue
        if write.function == "_update_session_status":  # 寫入 helper 自己
            continue
        if f"conversation_handler:{write.function}" in _TERMINAL_WRITE_EXEMPTIONS:
            continue
        problems.append(
            f"  conversation_handler.{write.function}：{write.shape} 繞過 "
            "`_update_session_status` 直接改狀態 → 繞過 CAS（EM-4）"
        )

    assert not problems, (
        "有函式把場次寫成終態卻沒把 fan-out 做完：\n" + "\n".join(problems)
    )


# ── 跳閘器的自我測試：三個實測盲點必須會紅 ────────────────
# 「探針自己也會壞掉，而且壞得沒有訊號」（不變式 #31）。跳閘器只在**它認得的形狀**
# 上有效，所以下面把查證報告 B5 實測出的三種寫法（外加兩種同族樣態）真的注入到
# 產品碼副本裡，證明現在掃得到。注入只在 tmp_path 的副本上做，repo 檔案不動。
_BLIND_SPOT_INJECTIONS: list[tuple[str, str, str, str]] = [
    (
        "① session_service 直接寫終態、完全不呼叫 _after_status_transition",
        "ss",
        '''

async def _hostile_finish_without_fanout(db, session):
    """注入樣態①（B5 實測不跳閘；正是 #20 要防的『終態卻沒有 SOAP』）。"""
    session.status = SessionStatus.COMPLETED
    await db.commit()
''',
        "session_service:_hostile_finish_without_fanout",
    ),
    (
        "② conversation_handler 用 keyword arg 傳終態",
        "ch",
        '''

async def _hostile_keyword_status(db, redis, session_id):
    """注入樣態②（B5 實測不跳閘：舊版只讀 args[3]）。"""
    return await _update_session_status(
        db, redis, session_id, new_status="completed", previous_status="in_progress"
    )
''',
        "conversation_handler:_hostile_keyword_status:completed",
    ),
    (
        "③ conversation_handler 用常數變數而非字面值",
        "ch",
        '''

_HOSTILE_TERMINAL_STATUS = "completed"


async def _hostile_constant_status(db, redis, session_id):
    """注入樣態③（B5 實測不跳閘：舊版只認 ast.Constant）。"""
    return await _update_session_status(
        db, redis, session_id, _HOSTILE_TERMINAL_STATUS, "in_progress"
    )
''',
        "conversation_handler:_hostile_constant_status:completed",
    ),
    (
        "④ 狀態值靜態解析不出來（保守側必須當成終態）",
        "ch",
        '''

_HOSTILE_STATUS_TABLE = {"ok": "completed"}


async def _hostile_dynamic_status(db, redis, session_id, outcome):
    """解析不出來就放行＝把『終態卻沒有 SOAP』放回來，成本不對稱。"""
    return await _update_session_status(
        db, redis, session_id, _HOSTILE_STATUS_TABLE[outcome], "in_progress"
    )
''',
        "conversation_handler:_hostile_dynamic_status:<unresolved>",
    ),
    (
        "⑤ session_service 走裸 SQLAlchemy UPDATE 繞過所有 helper",
        "ss",
        '''

async def _hostile_raw_update(db, session_id):
    """`.values(status=…)` 是 session_timeout 已在用的形狀，另兩個模組同樣要認。"""
    await db.execute(
        update(Session).where(Session.id == session_id).values(
            status=SessionStatus.CANCELLED
        )
    )
''',
        "session_service:_hostile_raw_update",
    ),
    (
        "⑥ tuple 多重指派同時寫 status 與 completed_at",
        "ss",
        '''

async def _hostile_tuple_status(db, session):
    """注入樣態⑥（2026-08-21 敵意複驗 ⑪ 實測不跳閘）。

    `session.status, session.completed_at = ...` 的 target 是 `ast.Tuple`，
    舊碼的迴圈只認 `ast.Attribute` → 整條略過。這是**一般慣用法**（一次寫兩個欄位）
    而不是刻意規避，也正是 #20 要防的「終態卻沒有 SOAP」樣態。
    """
    session.status, session.completed_at = SessionStatus.COMPLETED, datetime.now(UTC)
    await db.commit()
''',
        "session_service:_hostile_tuple_status",
    ),
    (
        "⑦ tuple 多重指派但右側解析不出來（保守側必須當成終態）",
        "ss",
        '''

async def _hostile_tuple_unresolved(db, session, decide):
    """右側是一個呼叫 → 靜態拆不出對應元素。放行＝把漏報放回來，成本不對稱。"""
    session.status, session.completed_at = decide()
    await db.commit()
''',
        "session_service:_hostile_tuple_unresolved",
    ),
    (
        "⑧ SQLAlchemy `.values()` 吃**位置引數 dict** 而不是 keyword",
        "ss",
        '''

async def _hostile_values_positional_dict(db, session_id):
    """注入樣態⑧（2026-08-21 敵意複驗第二輪實測不跳閘）。

    `.values({"status": …})` 是 SQLAlchemy 文件寫明的用法（欄位名要動態組時
    本來就會這樣寫）＝**合法慣用法而不是規避**，所以是最可能被無辜寫出來的一種。
    """
    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values({"status": SessionStatus.CANCELLED})
    )
''',
        "session_service:_hostile_values_positional_dict",
    ),
    (
        "⑨ setattr 動態屬性名寫終態",
        "ss",
        '''

async def _hostile_setattr_status(db, session):
    """注入樣態⑨（2026-08-21 敵意複驗第二輪實測不跳閘）。

    `setattr(session, "status", …)` 與 `session.status = …` 是同一件事，只是走
    動態屬性名——欄位表驅動的收尾函式很自然就會寫成這樣，不是刻意規避。
    """
    setattr(session, "status", SessionStatus.COMPLETED)
    await db.commit()
''',
        "session_service:_hostile_setattr_status",
    ),
    (
        "⑩ setattr 的屬性名也解析不出來（保守側必須當成終態）",
        "ss",
        '''

async def _hostile_setattr_dynamic_attr(db, session, field, value):
    """屬性名是函式參數 → 靜態證明不出「它寫的不是 status」。放行＝把漏報放回來。"""
    setattr(session, field, value)
    await db.commit()
''',
        "session_service:_hostile_setattr_dynamic_attr",
    ),
]


def _inject(dest: pathlib.Path, which: str, snippet: str) -> dict[str, pathlib.Path]:
    """把注入樣態接在產品碼副本尾端，回傳給 `_terminal_fanout_sites` 的 path 覆寫。

    `dest` 每次都要是**空的**目錄——注入版與對照版寫同一個檔名，共用目錄會互相覆蓋
    （早期版本正是這樣把注入內容洗掉，測試照樣綠）。
    """
    dest.mkdir(parents=True, exist_ok=True)
    copies: dict[str, pathlib.Path] = {}
    for key, src in {"ch": _CH_PATH, "ss": _SS_PATH, "st": _ST_PATH}.items():
        text = src.read_text(encoding="utf-8")
        if key == which:
            text += snippet
        dst = dest / f"{key}_{src.name}"
        dst.write_text(text, encoding="utf-8")
        copies[key] = dst
    return copies


def _scan(copies: dict[str, pathlib.Path]) -> set[str]:
    return _terminal_fanout_sites(
        ch_path=copies["ch"], ss_path=copies["ss"], st_path=copies["st"]
    )


@pytest.mark.parametrize(
    "label,which,snippet,expected_site",
    _BLIND_SPOT_INJECTIONS,
    ids=[i[0][:2] for i in _BLIND_SPOT_INJECTIONS],
)
def test_tripwire_trips_on_each_known_blind_spot(
    tmp_path, label: str, which: str, snippet: str, expected_site: str
):
    """把每一種盲點樣態注入產品碼副本，跳閘器必須掃得到、而且判定為未登記。"""
    baseline = _scan(_inject(tmp_path / "clean", "none", ""))
    found = _scan(_inject(tmp_path / "injected", which, snippet))

    assert expected_site in found, (
        f"跳閘器掃不到注入樣態「{label}」——它會靜默通過。\n"
        f"掃到的新站點：{sorted(found - baseline)}"
    )
    registered = {p.fanout_key for p in TERMINAL_PATHS} | set(
        _TERMINAL_WRITE_EXEMPTIONS
    )
    assert expected_site not in registered, (
        f"注入樣態「{label}」被既有註冊表／例外表吸收了，不會紅"
    )


def test_injection_free_copy_matches_the_real_scan(tmp_path):
    """自我測試的對照組：沒注入任何東西的副本要掃出與產品碼**一模一樣**的站點。

    否則「注入後多了一個站點」可能只是複製過程的假象。
    """
    assert _scan(_inject(tmp_path / "clean", "none", "")) == _terminal_fanout_sites()


def test_blind_spot_injections_are_red_under_the_old_shape_only_scanner(tmp_path):
    """反向釘子：這五種樣態在**舊版三種寫死形狀**的掃描器下確實一個都掃不到。

    沒有這條，上面那組測試無法證明它們真的曾是盲點——也就無法阻止有人把掃描器
    「簡化」回舊版而測試仍然全綠。
    """

    def _old_scanner(ch: pathlib.Path, ss: pathlib.Path, st: pathlib.Path) -> set[str]:
        """2026-08-20 版掃描器（逐字重現，只認三種寫死形狀）。"""
        sites: set[str] = set()
        for name, node in _enclosing_functions(ast.parse(ch.read_text("utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_update_session_status":
                if len(node.args) >= 4 and isinstance(node.args[3], ast.Constant):
                    if node.args[3].value in _TERMINAL_STATUSES:
                        sites.add(
                            f"conversation_handler:{name}:{node.args[3].value}"
                        )
        for name, node in _enclosing_functions(ast.parse(ss.read_text("utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == _FANOUT_ENTRY:
                    sites.add(f"session_service:{name}")
        for name, node in _enclosing_functions(ast.parse(st.read_text("utf-8"))):
            if not isinstance(node, ast.keyword) or node.arg != "status":
                continue
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "SessionStatus"
                and value.attr.lower() in _TERMINAL_STATUSES
            ):
                sites.add(f"session_timeout:{name}:{value.attr.lower()}")
        return sites

    for index, (label, which, snippet, expected_site) in enumerate(
        _BLIND_SPOT_INJECTIONS
    ):
        copies = _inject(tmp_path / f"old_{index}", which, snippet)
        old = _old_scanner(copies["ch"], copies["ss"], copies["st"])
        assert expected_site not in old, (
            f"樣態「{label}」在舊版掃描器下就掃得到了 → 這條反向釘子的前提不成立"
        )
