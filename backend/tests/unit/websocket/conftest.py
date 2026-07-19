"""tests/unit/websocket 共用 harness（E2E 稽核修復 A 群：D1/D2/D3/D5）。

提供 `_handle_text_message` 的純 Python 測試 driver（無 pytest-asyncio、無
fakeredis、無真 DB，沿用專案 asyncio.run + stub + monkeypatch 慣例）：

- ``_CaptureManager``：connection manager 替身，捕捉 session / dashboard /
  localized 推播（比照 test_supervisor_guidance_emit，補齊 dashboard 兩方法）。
- ``FakeRedis``：dict-backed async stub；``fail=True`` 時所有方法 raise，
  供紅旗去重 fail-open 測試。
- ``StubDB`` / ``StubResult``：捕捉 execute 的 stmt、rowcount 可設、可注入
  execute 例外，供 `_update_session_status` compare-and-set 測試。
- ``make_settings``：Settings.model_construct + object.__setattr__（沿用
  test_auto_conclude 的 _settings 模式），預設含 A 群新 kill-switch。
- ``run_text_turn``：包 asyncio.run(ch._handle_text_message(...)) 的 driver，
  內建全部必要 monkeypatch（服務層 AsyncMock spy、引擎 stub、
  _RED_FLAG_WAIT_TIMEOUT 縮短、drain 自有 DB session 假造）。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import app.websocket.conversation_handler as ch
from app.core.config import Settings

DEFAULT_SESSION_ID = "11111111-1111-4111-8111-111111111111"


# ── WS manager 替身 ──────────────────────────────────────
class _CaptureManager:
    """最小 connection manager 替身，捕捉所有推播訊息。"""

    def __init__(self) -> None:
        self.session_messages: list[dict[str, Any]] = []
        self.localized_calls: list[dict[str, Any]] = []
        self.dashboard_messages: list[dict[str, Any]] = []
        self.localized_dashboard_calls: list[dict[str, Any]] = []
        # 病患端 WS 是否仍在（drain 情境為 False；record-on-success 不看此值）
        self.send_to_session_result = True

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> bool:
        self.session_messages.append({"session_id": session_id, "message": message})
        return self.send_to_session_result

    async def send_localized_to_session(
        self,
        session_id: str,
        msg_type: str,
        code: str,
        params: dict[str, Any] | None = None,
        severity: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> bool:
        self.localized_calls.append(
            {
                "session_id": session_id,
                "msg_type": msg_type,
                "code": code,
                "params": params or {},
                "severity": severity,
                "extra": extra or {},
            }
        )
        return True

    async def broadcast_dashboard(self, message: dict[str, Any]) -> None:
        self.dashboard_messages.append(message)

    async def broadcast_dashboard_event(
        self, event_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        # P0-1 橋接後的事件與舊 broadcast_dashboard 捕成同一形狀，既有斷言不用改
        self.dashboard_messages.append({"type": event_type, "payload": payload or {}})

    async def broadcast_localized_dashboard(
        self,
        msg_type: str,
        code: str,
        params: dict[str, Any] | None = None,
        severity: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.localized_dashboard_calls.append(
            {
                "msg_type": msg_type,
                "code": code,
                "params": params or {},
                "severity": severity,
                "extra": extra or {},
            }
        )

    # ── 斷言輔助 ─────────────────────────────────────
    def messages_of_type(self, msg_type: str) -> list[dict[str, Any]]:
        return [
            m["message"]
            for m in self.session_messages
            if m["message"].get("type") == msg_type
        ]

    def chunk_texts(self) -> list[str]:
        return [
            m["payload"]["text"] for m in self.messages_of_type("ai_response_chunk")
        ]


# ── Redis 替身 ──────────────────────────────────────────
class FakeRedis:
    """dict-backed async Redis stub；fail=True 時所有操作 raise（fail-open 測試）。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.kv: dict[str, Any] = {}
        self.hashes: dict[str, dict[str, Any]] = {}
        self.hset_calls: list[tuple[str, str, Any]] = []

    def _maybe_fail(self) -> None:
        if self.fail:
            raise ConnectionError("redis down (injected)")

    async def get(self, key: str) -> Any:
        self._maybe_fail()
        return self.kv.get(key)

    async def setex(self, key: str, ttl: int, value: Any) -> None:
        self._maybe_fail()
        self.kv[key] = value

    async def hget(self, key: str, field: str) -> Any:
        self._maybe_fail()
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: Any) -> int:
        self._maybe_fail()
        self.hashes.setdefault(key, {})[field] = value
        self.hset_calls.append((key, field, value))
        return 1

    async def expire(self, key: str, ttl: int) -> bool:
        self._maybe_fail()
        return True


# ── DB 替身 ─────────────────────────────────────────────
class StubResult:
    def __init__(self, rowcount: int = 1, row: Any | None = None) -> None:
        self.rowcount = rowcount
        self._row = row

    def first(self) -> Any | None:
        """UPDATE ... RETURNING 語意：CAS 命中（rowcount≥1）回一列，否則 None。

        預設列帶 `_update_session_status` 稽核 / 通知所需欄位；doctor_id=None
        讓通知路徑 no-op，避免 stub 需要再模擬 User / Patient 查詢。
        """
        if self._row is not None:
            return self._row
        if self.rowcount:
            return SimpleNamespace(language="zh-TW", doctor_id=None, patient_id=None)
        return None


class StubDB:
    """捕捉 execute stmt 的最小 AsyncSession 替身。"""

    def __init__(
        self,
        rowcount: int = 1,
        execute_error: Exception | None = None,
        returning_row: Any | None = None,
    ) -> None:
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.rowcount = rowcount
        self.execute_error = execute_error
        self.returning_row = returning_row
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt: Any) -> StubResult:
        if self.execute_error is not None:
            raise self.execute_error
        self.executed.append(stmt)
        return StubResult(self.rowcount, row=self.returning_row)

    def add(self, obj: Any) -> None:
        """ORM add 替身（AuditLogService.log / NotificationService.create 用）。"""
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ── 設定 builder（沿用 test_auto_conclude 的 _settings 模式） ─
def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        HPI_COMPLETION_TERMINATION_ENABLED=True,
        HPI_COMPLETION_TERMINATION_THRESHOLD=80,
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=5,
        MAX_PATIENT_TURNS_HARD_CAP=10,
        SUPERVISOR_TIMEOUT_SECONDS=5,
        LLM_EMPTY_RESPONSE_RETRY=True,
        HARD_CAP_DRAIN_AWAIT_SECONDS=5.0,
        MAX_HARD_CAP_DRAIN_DEFERS=2,
        REDIS_KEY_PREFIX="gu:",
    )
    base.update(overrides)
    s = Settings.model_construct()
    for k, v in base.items():
        object.__setattr__(s, k, v)
    return s


# ── alert dict builder（形狀對齊 red_flag_detector 輸出） ─
def make_alert(
    severity: str = "high",
    canonical_id: str | None = "gross_hematuria",
    title: str = "肉眼血尿",
    description: str = "尿中帶血，需追蹤評估",
) -> dict[str, Any]:
    return {
        "canonical_id": canonical_id,
        "severity": severity,
        "title": title,
        "description": description,
        "trigger_reason": "keyword match",
        "alert_type": "semantic",
        "confidence": "rule_hit",
        "suggested_actions": [],
        "matched_rule_id": None,
    }


# ── 可編程引擎 stub ──────────────────────────────────────
class StubLLMEngine:
    """generate_response 依呼叫次序回放 programs：list[str]（逐 chunk yield）
    或 Exception 實例（await 首個 chunk 時 raise）。"""

    def __init__(self, programs: list[Any]) -> None:
        self.programs = list(programs)
        self.calls = 0

    def build_wrap_up_prompt(self, language: str | None = None) -> str:
        # 收尾輪極簡 prompt（stub：回固定字串即可，handler 只是把它當 system_prompt 傳下）
        return "WRAP_UP"

    def format_messages(
        self,
        conversation_history: list[dict[str, Any]],
        system_prompt: str,
        supervisor_guidance: Any = None,
        language: str | None = None,
        conclude: bool = False,
    ) -> list[dict[str, str]]:
        return [{"role": "system", "content": system_prompt}]

    def generate_response(self, messages: Any, session_context: Any):
        idx = min(self.calls, len(self.programs) - 1)
        program = self.programs[idx]
        self.calls += 1

        async def _gen():
            if isinstance(program, BaseException):
                raise program
            for chunk in program:
                yield chunk

        return _gen()


class StubTTS:
    async def synthesize(self, *, text: str, language: str | None = None) -> bytes:
        return b""


class StubSupervisor:
    async def analyze_next_step(self, **kwargs: Any) -> None:
        return None


class StubDetector:
    """可編程紅旗偵測器：立即回 / sleep 後回 / 永久 pending / raise。"""

    def __init__(
        self,
        alerts: list[dict[str, Any]] | None = None,
        delay: float = 0.0,
        hang: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.alerts = alerts or []
        self.delay = delay
        self.hang = hang
        self.error = error

    async def detect(self, text: str, session_context: dict[str, Any]) -> list[dict[str, Any]]:
        if self.hang:
            await asyncio.sleep(999)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return list(self.alerts)


# ── 單輪 driver ─────────────────────────────────────────
def run_text_turn(
    monkeypatch,
    *,
    text: str = "我最近排尿會痛",
    language: str = "zh-TW",
    llm_programs: list[Any] | None = None,
    detector: StubDetector | None = None,
    settings: Settings | None = None,
    session_context: dict[str, Any] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    redis: FakeRedis | None = None,
    alert_create_side_effect: Exception | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    red_flag_wait_timeout: float = 0.01,
) -> SimpleNamespace:
    """跑一輪 _handle_text_message，回傳所有 spy / capture 供斷言。

    session_context / conversation_history / redis 可跨輪傳同一實例
    （模擬同一 WS 連線的多輪對話，例如 _hard_cap_drain_defers 累計）。
    """
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    # 縮短紅旗 gate 同步等待（原 3.5s），讓 drain 情境測試不用真等
    monkeypatch.setattr(ch, "_RED_FLAG_WAIT_TIMEOUT", red_flag_wait_timeout)

    settings = settings or make_settings()
    redis = redis if redis is not None else FakeRedis()
    if conversation_history is None:
        conversation_history = []
    if session_context is None:
        session_context = {
            "session_id": session_id,
            "user_id": "user-1",
            "chief_complaint": "血尿",
            "chief_complaint_display": "血尿",
            "patient_info": {"name": "測試病患"},
            "language": language,
        }

    db = StubDB()
    drain_db = StubDB()

    # 服務層 AsyncMock spy（Mock 不實作 descriptor，staticmethod 直接可換）
    from app.services.alert_service import AlertService
    from app.services.conversation_service import ConversationService

    conv_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(ConversationService, "create", conv_create)
    alert_create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    if alert_create_side_effect is not None:
        alert_create.side_effect = alert_create_side_effect
    monkeypatch.setattr(AlertService, "create", alert_create)

    # 模組級 helper spy（_handle_text_message 走模組 global，patch 即生效）
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(ch, "_update_session_status", update_status)
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)
    monkeypatch.setattr(
        ch, "_broadcast_dashboard_queue_and_stats", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(ch, "_save_conversation_history", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "_cap_conversation_history", AsyncMock(return_value=None))

    # _drain_late_red_flags 的自有 DB session：換成假 context manager，不碰真 DB
    import app.core.database as core_db

    @asynccontextmanager
    async def _fake_get_db_session():
        yield drain_db

    monkeypatch.setattr(core_db, "get_db_session", _fake_get_db_session)

    llm = StubLLMEngine(llm_programs if llm_programs is not None else [["好的。"]])
    det = detector or StubDetector(alerts=[])

    result = asyncio.run(
        ch._handle_text_message(
            session_id=session_id,
            text=text,
            llm_engine=llm,
            tts_pipeline=StubTTS(),
            red_flag_detector=det,
            supervisor_engine=StubSupervisor(),
            system_prompt="test-system-prompt",
            conversation_history=conversation_history,
            session_context=session_context,
            redis=redis,
            db=db,
            settings=settings,
        )
    )

    return SimpleNamespace(
        result=result,
        cap=cap,
        redis=redis,
        db=db,
        drain_db=drain_db,
        llm=llm,
        conv_create=conv_create,
        alert_create=alert_create,
        update_status=update_status,
        soap_spy=soap_spy,
        conversation_history=conversation_history,
        session_context=session_context,
    )
