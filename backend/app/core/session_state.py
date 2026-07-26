"""場次狀態轉移的單一權威。

先前 `VALID_TRANSITIONS` 只定義在 session_service.py 且只被 REST 路徑
（`update_status_static`）強制；實際問診幾乎全程走 WS 的 `_update_session_status`
（compare-and-set），完全不查此表 → 合法轉移有兩個事實來源、WS 端可執行表外轉移。
抽到這個中性下層，讓 REST 與 WS 兩條路徑共用同一份規則。
"""

from app.models.enums import SessionStatus

# ── 合法狀態轉移表（單一權威） ─────────────────────────────
VALID_TRANSITIONS: dict[SessionStatus, list[SessionStatus]] = {
    SessionStatus.WAITING: [
        SessionStatus.IN_PROGRESS,
        SessionStatus.CANCELLED,
    ],
    SessionStatus.IN_PROGRESS: [
        SessionStatus.COMPLETED,
        SessionStatus.ABORTED_RED_FLAG,
        SessionStatus.CANCELLED,
    ],
    SessionStatus.COMPLETED: [],
    SessionStatus.ABORTED_RED_FLAG: [],
    SessionStatus.CANCELLED: [],
}


def _coerce(status: object) -> SessionStatus | None:
    """把 str 或 SessionStatus 統一成 enum；無法解析回 None。

    WS 路徑用字串（"in_progress"），service 用 enum，兩邊都要吃。
    """
    if isinstance(status, SessionStatus):
        return status
    try:
        return SessionStatus(status)
    except ValueError:
        return None


def is_valid_transition(
    current: object, new: object, *, allow_noop: bool = False
) -> bool:
    """`current → new` 是否為合法狀態轉移。

    Args:
        allow_noop: True 時允許同狀態自轉移（X→X）視為合法。WS resume 重連會用
            `in_progress → in_progress` 冪等補寫 started_at，需放行；REST 端維持
            嚴格（預設 False），保留「重複轉移即非法」的既有語意。
    """
    c, n = _coerce(current), _coerce(new)
    if c is None or n is None:
        return False
    if allow_noop and c == n:
        return True
    return n in VALID_TRANSITIONS.get(c, [])
