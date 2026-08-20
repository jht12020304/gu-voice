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
- `test_matrix_cell` 逐格跑真正的路徑並比對觀測值。
- `test_skipped_cells_are_documented_in_code` 確認每個「刻意不做」的格子在
  程式碼裡有對應註解；把註解刪掉會讓測試紅，逼下一個人重新面對這個決定。
- `test_registry_covers_every_terminal_fanout_site` 是**跳閘器**：用 AST 掃出
  三個擁有終態轉移的模組裡所有「把場次寫成終態」的呼叫點，與矩陣註冊的集合
  比對。新增一條終態路徑而沒有登記到這張矩陣 → 直接紅。

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
_TERMINAL_STATUSES = {"completed", "aborted_red_flag", "cancelled"}


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


def _terminal_fanout_sites() -> set[str]:
    """掃出「把場次寫成終態」的呼叫點。

    三個模組各有自己的寫法，所以各認一種形狀：
    - conversation_handler：`_update_session_status(db, redis, sid, "<終態>", ...)`
    - session_service：`_after_status_transition(...)`（REST 的附帶效應入口，
      每條 REST 終態路徑都必須經過它）
    - tasks/session_timeout：`.values(status=SessionStatus.<終態>, ...)`
    """
    sites: set[str] = set()

    for name, ch_node in _enclosing_functions(
        ast.parse(_CH_PATH.read_text(encoding="utf-8"))
    ):
        if not isinstance(ch_node, ast.Call):
            continue
        func = ch_node.func
        if isinstance(func, ast.Name) and func.id == "_update_session_status":
            if len(ch_node.args) >= 4 and isinstance(ch_node.args[3], ast.Constant):
                status = ch_node.args[3].value
                if status in _TERMINAL_STATUSES:
                    sites.add(f"conversation_handler:{name}:{status}")

    for name, node in _enclosing_functions(
        ast.parse(_SS_PATH.read_text(encoding="utf-8"))
    ):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_after_status_transition":
                sites.add(f"session_service:{name}")

    for name, node in _enclosing_functions(
        ast.parse(_ST_PATH.read_text(encoding="utf-8"))
    ):
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


def test_registry_covers_every_terminal_fanout_site():
    """跳閘器：碼庫裡每一個終態 fan-out 點都必須登記在這張矩陣裡。

    新增一條終態路徑（例如再加一個 `_update_session_status(..., "completed", ...)`
    的呼叫點）而忘記登記 → 這裡直接紅，逼你先在 `TERMINAL_PATHS` 補一列並回答
    六件事各要不要做。這正是稽核「測試缺口 #1」要的東西。
    """
    registered = {p.fanout_key for p in TERMINAL_PATHS}
    found = _terminal_fanout_sites()

    unregistered = found - registered
    stale = registered - found

    assert not unregistered, (
        "發現未登記在六件事矩陣裡的終態轉移點：\n  "
        + "\n  ".join(sorted(unregistered))
        + "\n請在 TERMINAL_PATHS 補一列，逐項回答六件事要不要做。"
    )
    assert not stale, (
        "矩陣登記了已不存在的終態轉移點（路徑被刪或改名）：\n  "
        + "\n  ".join(sorted(stale))
    )
