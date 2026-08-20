"""
SO-2 / SO-4：報告 regenerate 路徑修通後的注入式回歸守護。

稽核指出的四個具體斷點，每一條在此都有一個會紅的測試：

1. **aborted_red_flag 場次拿不到報告** — 閘門硬寫 `!= COMPLETED`，把紅旗中止
   （最需要報告的一類）整類擋在門外。
2. **FAILED 報告無法重生** — regenerate 只處理 GENERATED，上一輪失敗的報告
   醫師按重生後行為未定義。
3. **GENERATING 中連點** — 重複派 Celery 任務互相覆寫同一 row。
4. **SO-4 派任務前沒 commit** — Celery worker 在另一個行程/連線，會在
   GENERATING row 落地前就開始讀。

外加 D-8 殘項：regenerate 必須把 `icd10_verified` 一併歸零。
以及 `_snapshot_revision` 的 MAX+1 併發撞號重試。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ConflictException,
    ReportAlreadyExistsException,
    SessionNotActiveException,
)
from app.models.enums import (
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
)
from app.services.report_service import (
    REPORT_ELIGIBLE_SESSION_STATUSES,
    ReportService,
)
from app.utils.datetime_utils import utc_now


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeReport:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: ReportStatus = ReportStatus.GENERATED
    review_status: ReviewStatus = ReviewStatus.APPROVED
    subjective: Optional[dict] = field(
        default_factory=lambda: {"chief_complaint": "血尿"}
    )
    objective: Optional[dict] = field(default_factory=lambda: {"vital_signs": None})
    assessment: Optional[dict] = field(
        default_factory=lambda: {"clinical_impression": "疑似膀胱腫瘤"}
    )
    plan: Optional[dict] = field(default_factory=lambda: {"urgency": "24h"})
    summary: Optional[str] = "血尿三天"
    icd10_codes: Optional[list[str]] = field(default_factory=lambda: ["R31.9"])
    icd10_verified: bool = True
    language: str = "zh-TW"
    ai_confidence_score: Optional[Decimal] = Decimal("0.91")
    raw_transcript: Optional[str] = "…"
    reviewed_by: Optional[uuid.UUID] = field(default_factory=uuid.uuid4)
    reviewed_at: Any = "2026-08-01T00:00:00Z"
    review_notes: Optional[str] = "ok"
    generated_at: Any = "2026-08-01T00:00:00Z"
    updated_at: Any = None


class _FakeDB:
    """極簡 AsyncSession 替身；`events` 記錄動作順序供 SO-4 斷言。"""

    def __init__(self, *execute_values: Any) -> None:
        self.added: list[Any] = []
        self.events: list[str] = []
        self._seq = list(execute_values)
        self._i = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.events.append("flush")

    async def commit(self) -> None:
        self.events.append("commit")

    async def execute(self, stmt: Any):
        i = self._i
        self._i += 1
        value = self._seq[i] if i < len(self._seq) else (
            self._seq[-1] if self._seq else None
        )

        class _Result:
            def scalar_one_or_none(self_inner):
                return value

            def scalar_one(self_inner):
                return value

        return _Result()


@pytest.fixture
def spy_delay(monkeypatch):
    """攔截 Celery delay，並把它記進共用的 events 序列。"""
    import app.tasks.report_queue as rq

    calls: list[str] = []
    holder: dict[str, Any] = {"db": None}

    def _delay(session_id, *a, **kw):
        calls.append(session_id)
        db = holder["db"]
        if db is not None:
            db.events.append("delay")

    monkeypatch.setattr(rq.generate_soap_report, "delay", _delay)
    return calls, holder


@pytest.fixture
def patch_snapshot(monkeypatch):
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ReportService, "_snapshot_revision", mock)
    return mock


# ──────────────────────────────────────────────────────
# 1. 場次終態閘門：aborted_red_flag 必須可產生／重生
# ──────────────────────────────────────────────────────

def test_eligible_statuses_constant_includes_red_flag_abort():
    """常數本身就是契約：紅旗中止是最需要報告的一類，不得被剔除。"""
    assert SessionStatus.ABORTED_RED_FLAG in REPORT_ELIGIBLE_SESSION_STATUSES
    assert SessionStatus.COMPLETED in REPORT_ELIGIBLE_SESSION_STATUSES
    # 未結束 / 取消的場次不得產生半截報告
    assert SessionStatus.IN_PROGRESS not in REPORT_ELIGIBLE_SESSION_STATUSES
    assert SessionStatus.WAITING not in REPORT_ELIGIBLE_SESSION_STATUSES
    assert SessionStatus.CANCELLED not in REPORT_ELIGIBLE_SESSION_STATUSES


def test_aborted_red_flag_session_can_generate_first_report(spy_delay, patch_snapshot):
    """紅旗中止場次首次產生報告：不再被 SessionNotActiveException 擋掉。"""
    calls, holder = spy_delay
    db = _FakeDB(SessionStatus.ABORTED_RED_FLAG, None)
    holder["db"] = db
    session_id = uuid.uuid4()

    report = _run(ReportService.generate_report(db, session_id=session_id))

    assert report.status == ReportStatus.GENERATING
    assert len(db.added) == 1
    assert calls == [str(session_id)]


def test_aborted_red_flag_session_can_regenerate(spy_delay, patch_snapshot):
    """紅旗中止場次的既有報告也必須能重生。"""
    calls, holder = spy_delay
    existing = _FakeReport(status=ReportStatus.GENERATED)
    db = _FakeDB(SessionStatus.ABORTED_RED_FLAG, existing)
    holder["db"] = db

    report = _run(
        ReportService.generate_report(
            db, session_id=existing.session_id, regenerate=True
        )
    )

    assert report is existing
    assert existing.status == ReportStatus.GENERATING
    assert patch_snapshot.await_count == 1
    assert patch_snapshot.await_args[0][2] == ReportRevisionReason.REGENERATE
    assert calls == [str(existing.session_id)]


@pytest.mark.parametrize(
    "status",
    [SessionStatus.WAITING, SessionStatus.IN_PROGRESS, SessionStatus.CANCELLED],
)
def test_non_terminal_session_still_rejected(status, spy_delay, patch_snapshot):
    calls, holder = spy_delay
    db = _FakeDB(status, None)
    holder["db"] = db

    with pytest.raises(SessionNotActiveException) as exc:
        _run(ReportService.generate_report(db, session_id=uuid.uuid4()))

    assert exc.value.details["current_status"] == status.value
    # 可產報告的狀態清單要回給呼叫端（前端據此提示醫師）
    assert "aborted_red_flag" in exc.value.details["eligible_statuses"]
    assert calls == []


def test_status_gate_accepts_raw_string_status(spy_delay, patch_snapshot):
    """DB driver 回裸字串時也要放行（Enum.__hash__ 走 name，不能直接 set 比對）。"""
    calls, holder = spy_delay
    db = _FakeDB("aborted_red_flag", None)
    holder["db"] = db

    _run(ReportService.generate_report(db, session_id=uuid.uuid4()))
    assert len(calls) == 1


# ──────────────────────────────────────────────────────
# 2. regenerate 狀態矩陣
# ──────────────────────────────────────────────────────

def test_failed_report_can_be_regenerated(spy_delay, patch_snapshot):
    """上一輪 FAILED 的報告，醫師按重生要能重跑（不寫快照——沒有內容可留）。"""
    calls, holder = spy_delay
    existing = _FakeReport(
        status=ReportStatus.FAILED,
        subjective=None,
        objective=None,
        assessment=None,
        plan=None,
        summary=None,
    )
    db = _FakeDB(SessionStatus.COMPLETED, existing)
    holder["db"] = db

    _run(
        ReportService.generate_report(
            db, session_id=existing.session_id, regenerate=True
        )
    )

    assert existing.status == ReportStatus.GENERATING
    assert patch_snapshot.await_count == 0
    assert calls == [str(existing.session_id)]


def test_generated_report_without_regenerate_flag_conflicts(spy_delay, patch_snapshot):
    calls, holder = spy_delay
    existing = _FakeReport(status=ReportStatus.GENERATED)
    db = _FakeDB(SessionStatus.COMPLETED, existing)
    holder["db"] = db

    with pytest.raises(ReportAlreadyExistsException) as exc:
        _run(ReportService.generate_report(db, session_id=existing.session_id))

    assert exc.value.status_code == 409
    assert exc.value.details["report_id"] == str(existing.id)
    assert calls == []


@pytest.mark.parametrize("regenerate", [False, True])
def test_generating_report_is_rejected_with_explicit_message(
    regenerate, spy_delay, patch_snapshot
):
    """防連點：生成中一律 409 errors.report_generating，且**不得**再派任務。"""
    calls, holder = spy_delay
    existing = _FakeReport(status=ReportStatus.GENERATING)
    db = _FakeDB(SessionStatus.COMPLETED, existing)
    holder["db"] = db

    with pytest.raises(ConflictException) as exc:
        _run(
            ReportService.generate_report(
                db, session_id=existing.session_id, regenerate=regenerate
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.message == "errors.report_generating"
    assert exc.value.details["current_status"] == "generating"
    assert calls == []
    # 既有 row 不得被重置
    assert existing.status == ReportStatus.GENERATING


def test_stale_generating_can_be_taken_over_by_regenerate(spy_delay, patch_snapshot):
    """
    逃生口：派任務是「commit → delay()」，broker 掛掉時 row 會永遠停在
    GENERATING。若防連點守衛沒有時效，醫師端的手動 regenerate 補救路徑
    （WS 觸發器註解明講的那條）會被自己的守衛永久堵死。
    """
    calls, holder = spy_delay
    stale = _FakeReport(
        status=ReportStatus.GENERATING,
        updated_at=utc_now() - timedelta(hours=1),
    )
    db = _FakeDB(SessionStatus.COMPLETED, stale)
    holder["db"] = db

    _run(
        ReportService.generate_report(
            db, session_id=stale.session_id, regenerate=True
        )
    )

    assert stale.status == ReportStatus.GENERATING  # 重置後仍是 generating
    assert stale.icd10_verified is False
    assert calls == [str(stale.session_id)]


def test_recently_started_generating_is_not_taken_over(spy_delay, patch_snapshot):
    """剛開始跑的（＝真的連點）不得接手，否則兩個任務會互相覆寫。"""
    calls, holder = spy_delay
    fresh = _FakeReport(status=ReportStatus.GENERATING, updated_at=utc_now())
    db = _FakeDB(SessionStatus.COMPLETED, fresh)
    holder["db"] = db

    with pytest.raises(ConflictException):
        _run(
            ReportService.generate_report(
                db, session_id=fresh.session_id, regenerate=True
            )
        )
    assert calls == []


def test_generating_without_timestamp_is_not_taken_over(spy_delay, patch_snapshot):
    """沒有時間戳可判斷 → 保守走 409，不猜。"""
    calls, holder = spy_delay
    unknown = _FakeReport(status=ReportStatus.GENERATING, updated_at=None)
    db = _FakeDB(SessionStatus.COMPLETED, unknown)
    holder["db"] = db

    with pytest.raises(ConflictException):
        _run(
            ReportService.generate_report(
                db, session_id=unknown.session_id, regenerate=True
            )
        )
    assert calls == []


def test_report_generating_message_key_is_translatable():
    """明確訊息必須真的翻得出來（否則前端會看到 raw key）。"""
    from app.utils.i18n_messages import get_message, is_message_key

    assert is_message_key("errors.report_generating")
    for lang in ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"):
        assert get_message("errors.report_generating", lang)


def test_regenerate_resets_icd10_verified(spy_delay, patch_snapshot):
    """D-8 殘項：codes 清空了，verified 旗標不能留著騙 UI 說「已驗證」。"""
    calls, holder = spy_delay
    existing = _FakeReport(status=ReportStatus.GENERATED, icd10_verified=True)
    db = _FakeDB(SessionStatus.COMPLETED, existing)
    holder["db"] = db

    _run(
        ReportService.generate_report(
            db, session_id=existing.session_id, regenerate=True
        )
    )

    assert existing.icd10_codes is None
    assert existing.icd10_verified is False
    # 其餘重置欄位一併確認（審閱結果不可殘留到新版本上）
    assert existing.review_status == ReviewStatus.PENDING
    assert existing.reviewed_by is None
    assert existing.reviewed_at is None
    assert existing.review_notes is None
    assert existing.generated_at is None
    assert existing.ai_confidence_score is None


# ──────────────────────────────────────────────────────
# 3. SO-4：先 commit 再 delay
# ──────────────────────────────────────────────────────

def test_commit_happens_before_celery_dispatch(spy_delay, patch_snapshot):
    """Celery worker 在另一個行程；commit 晚於 delay 會讀到還沒落地的 row。"""
    calls, holder = spy_delay
    db = _FakeDB(SessionStatus.COMPLETED, None)
    holder["db"] = db

    _run(ReportService.generate_report(db, session_id=uuid.uuid4()))

    assert "commit" in db.events and "delay" in db.events
    assert db.events.index("commit") < db.events.index("delay"), db.events


def test_commit_before_dispatch_on_regenerate_path(spy_delay, patch_snapshot):
    calls, holder = spy_delay
    existing = _FakeReport(status=ReportStatus.GENERATED)
    db = _FakeDB(SessionStatus.COMPLETED, existing)
    holder["db"] = db

    _run(
        ReportService.generate_report(
            db, session_id=existing.session_id, regenerate=True
        )
    )

    assert db.events.index("commit") < db.events.index("delay"), db.events


# ──────────────────────────────────────────────────────
# 4. _snapshot_revision：MAX+1 併發撞號重試
# ──────────────────────────────────────────────────────

class _CollidingDB:
    """第一次 flush 撞 unique constraint，第二次成功；MAX 也跟著往上跳。"""

    def __init__(self) -> None:
        self.max_no = 1
        self.added: list[Any] = []
        self.flush_calls = 0
        self.savepoints = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, stmt: Any):
        value = self.max_no

        class _Result:
            def scalar_one(self_inner):
                return value

        return _Result()

    async def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_calls == 1:
            # 另一個交易搶先寫掉了 revision_no=2
            self.max_no = 2
            raise IntegrityError(
                "INSERT INTO soap_report_revisions",
                {},
                Exception("uq_soap_report_revisions_report_id_rev_no"),
            )

    def begin_nested(self):
        outer = self

        class _SavePoint:
            async def __aenter__(self_inner):
                outer.savepoints += 1
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                if exc_type is not None:
                    # SAVEPOINT 回滾：把該次 add 的物件退掉
                    outer.added = [
                        o for o in outer.added if o is not outer.added[-1]
                    ] if outer.added else []
                return False

        return _SavePoint()


def test_snapshot_retries_once_on_revision_no_collision():
    db = _CollidingDB()
    report = _FakeReport()

    revision = _run(
        ReportService._snapshot_revision(
            db, report, ReportRevisionReason.REGENERATE, created_by=None
        )
    )

    assert db.flush_calls == 2
    assert db.savepoints == 2
    # 重讀 MAX 之後改用下一個號碼，而不是硬塞同一號
    assert revision.revision_no == 3


class _AlwaysCollidingDB(_CollidingDB):
    async def flush(self) -> None:
        self.flush_calls += 1
        raise IntegrityError("INSERT", {}, Exception("uq_…"))


def test_revision_no_unique_constraint_exists_in_migration():
    """
    重試邏輯的前提：DB 真的擋得住撞號。若哪天有人把這個 unique constraint
    拿掉，MAX+1 競態就會變成「兩筆同號 revision」的靜默資料損毀，
    而不是可重試的 IntegrityError。
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "20260418_1600-soap_report_revisions.py"
    )
    text = migration.read_text(encoding="utf-8")
    assert "uq_soap_report_revisions_report_id_rev_no" in text
    assert '["report_id", "revision_no"]' in text


def test_snapshot_reraises_when_retry_exhausted():
    """撞號重試用盡要把錯誤丟出去——快照遺失不可靜默吞掉。"""
    db = _AlwaysCollidingDB()
    with pytest.raises(IntegrityError):
        _run(
            ReportService._snapshot_revision(
                db, _FakeReport(), ReportRevisionReason.REGENERATE
            )
        )
    assert db.flush_calls == 2
