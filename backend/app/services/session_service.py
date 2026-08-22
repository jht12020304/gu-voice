"""
問診場次服務
- 場次 CRUD
- 狀態轉移驗證
- 醫師指派
"""

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authz import get_user_role as _get_user_role
from app.core.exceptions import (
    ForbiddenException,
    InvalidStatusTransitionException,
    NotFoundException,
    SessionNotFoundException,
    ValidationException,
)
from app.models.conversation import Conversation
from app.models.enums import AuditAction, SessionStatus, UserRole
from app.core.config import settings
from app.models.patient import Patient
from app.models.session import Session
from app.models.user import User
from app.utils.datetime_utils import utc_now
from app.utils.language import resolve_language

logger = logging.getLogger(__name__)


async def _broadcast_session_created(db: AsyncSession, session: Session) -> None:
    """H-8：場次建立後向儀表板推播 session_created + 最新 queue/stats。

    推播一律走 Redis pub/sub 橋接（``publish_dashboard_event`` →各 API 行程的
    subscriber →本行程 fan-out），因此**不得**以本行程的
    ``manager.dashboard_connection_count`` 當作 early return 條件：該計數是單一
    uvicorn worker 的行程本地值，多 worker 部署下處理請求的 worker 往往沒有任何
    dashboard 連線，提早 return 會讓事件根本進不了 Redis，其他 worker 上連著的
    醫師就收不到（4 worker、1 連線時約 3/4 機率漏發）。

    Redis 端無訂閱者時 publish 成本極低，且 ``publish_dashboard_event`` 自帶例外
    保護（Redis 不可用只記 log）。本函式亦吞掉所有例外，絕不影響場次建立主流程。

    注意：report_generated 的真正完成點在 Celery worker（另一進程），該處尚未
    比照接線，詳見 report_service 的 TODO。
    """
    try:
        from app.cache.redis_client import get_redis
        from app.websocket.connection_manager import manager
        from app.websocket.dashboard_handler import broadcast_queue_and_stats

        patient = getattr(session, "patient", None)
        patient_name = getattr(patient, "name", "") if patient else ""
        await manager.broadcast_session_created(
            session_id=str(session.id),
            patient_name=patient_name or "",
            chief_complaint=getattr(session, "chief_complaint_text", "") or "",
            status=(
                session.status.value
                if hasattr(session.status, "value")
                else str(session.status)
            ),
        )
        # 順帶刷新 queue/stats（沿用 conversation_handler 既有的全域廣播語意）
        redis = await get_redis()
        await broadcast_queue_and_stats(db, redis)
    except Exception as exc:  # pragma: no cover - 推播失敗非致命
        logger.warning(
            "場次建立後推播儀表板事件失敗（非致命） | session=%s, error=%s",
            getattr(session, "id", None),
            str(exc),
        )


# ── REST 狀態轉移的附帶效應（不變式 #20「終態六件事」） ──────────────
#
# EM-2：`PUT /sessions/{id}/status` 以前只做「改 status」一件事——把場次標成
# completed 卻不派 SOAP、不廣播 dashboard、不通知任何人，醫師端排隊清單留著一筆
# 已結束的場次、且永遠等不到報告。以下把 REST 路徑能做的補齊。
#
# dashboard `session_status_changed` 的在地化 code：刻意只挑「既有」的 canonical
# code（新增一個 key 要同步 frontend/src + frontend/public 鏡像 + flutter_app
# 三份共 15 個 locale 檔），cancelled 沿用「病患或助手結束場次」語意吻合。
_STATUS_CHANGED_CODES: dict[SessionStatus, str] = {
    SessionStatus.COMPLETED: "events.session.completed_normal",
    SessionStatus.ABORTED_RED_FLAG: "events.session.aborted_red_flag_dashboard",
    SessionStatus.CANCELLED: "events.session.ended_by_user",
}
_STATUS_CHANGED_SEVERITIES: dict[SessionStatus, str] = {
    SessionStatus.ABORTED_RED_FLAG: "critical",
}
# 會派 SOAP 的終態。cancelled **刻意不派**：與 P7 的既有政策一致
# （`tasks/session_timeout` 的逾時 cancelled、病患直接關瀏覽器皆無報告——
# 未完成場次不出報告是產品決策，不是缺陷）。要改政策請三處一起改。
_SOAP_ON_TERMINAL: frozenset[SessionStatus] = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.ABORTED_RED_FLAG}
)


async def _refresh_session_state_cache(session_id: UUID, new_status: SessionStatus) -> None:
    """把 Redis 的場次狀態快取更新成新狀態（與 WS `_update_session_status` 對稱）。

    key 格式刻意從 `conversation_handler` import 而不是在這裡再寫一份字面值：
    兩處漂移的後果是「REST 改了狀態但快取還是舊值」，而且不會有任何訊號。
    """
    from app.cache.redis_client import get_redis
    from app.websocket.conversation_handler import (
        _SESSION_STATE_KEY,
        _SESSION_STATE_TTL,
    )

    redis = await get_redis()
    state_key = _SESSION_STATE_KEY.format(session_id=str(session_id))
    await redis.hset(state_key, "status", new_status.value)
    await redis.expire(state_key, _SESSION_STATE_TTL)


async def _after_status_transition(
    db: AsyncSession,
    *,
    session_id: UUID,
    previous_status: SessionStatus,
    new_status: SessionStatus,
) -> None:
    """REST 狀態轉移 **commit 之後** 的附帶效應。逐項對照不變式 #20 的六件事：

    1. **改 status**：呼叫端（`update_status_static`）已做。
    2. **派 SOAP**：做——`completed` / `aborted_red_flag` 走與 WS 完全同一個觸發器
       （`conversation_handler._generate_soap_report_async`：建 GENERATING row →
       派 Celery `generate_soap_report`）。不變式 #13「SOAP 生成單一路徑」要求所有
       路徑共用同一個觸發器，因此這裡刻意 import 那個私有 helper 而不是自己再寫
       一份「建 row + delay」。冪等由存在性檢查 + `soap_reports.session_id` UNIQUE
       保證，與 WS 路徑同時觸發也只會有一份報告。`cancelled` 不派（見
       `_SOAP_ON_TERMINAL`）。
    3. **送病患端 `session_status`**：**做不到（架構限制，刻意省略）**。病患 WS 連線
       在 `ConnectionManager.active_connections`——那是**行程本地** dict，生產是 4 個
       uvicorn worker，處理本次 REST 請求的行程有 3/4 機率不是持有該連線的行程；
       全碼庫唯一的跨行程橋接是 `DASHBOARD_EVENTS_CHANNEL`（只 fan-out 給 dashboard
       連線，見 `dashboard_handler._dispatch_dashboard_event`），沒有 per-session 的
       等價物。這與 `tasks/session_timeout` 的同一格是同一個限制、同一個理由。
       **後果與現有防線**：
       - 新連線：`conversation_websocket` 步驟 2 的狀態守衛（`status not in
         ("waiting", "in_progress")` → close 4009）擋掉，病患無法對已終態場次重連。
       - **已在飛的連線：擋不住**——`session_context["_terminated"]` 是行程內旗標，
         REST 在別的行程改狀態時設不了它，所以那條 WS 會繼續問診。狀態不會被弄髒
         （WS 所有終態轉移都是 `... WHERE status='in_progress'` 的 compare-and-set，
         對已終態場次必定 miss，且 EM-4 之後 CAS miss 就不送 completed / 不廣播 /
         不派 SOAP），SOAP 也不會多一份（冪等），但病患畫面不會自己離開對話頁。
         要真正修掉需要 per-session 的跨行程通知橋接，屬獨立需求。
    4. **廣播 dashboard**：做——`session_status_changed` +（所有成功轉移都）刷新
       queue/stats。走 `broadcast_localized_dashboard` → `broadcast_dashboard_event`
       → Redis publish（不變式 #15：不可用行程本地 fan-out）。
       非終態轉移（`waiting → in_progress`）不送 `session_status_changed`：現有
       canonical code 只有 `events.session.ws_connected`（語意是「WS 連上了」，
       REST 轉移時是假話），queue/stats 刷新已足以讓醫師端清單正確。
    5. **建醫師通知**：`completed` 的 SESSION_COMPLETE 通知由
       `update_status_static` 建（本輪補上，與 WS `_update_session_status` 同一
       判準：僅在 `session.doctor_id` 有值時建）；
       `aborted_red_flag` 的 RED_FLAG 通知**刻意不在此建**——REST 這條路徑沒有
       任何 `red_flag_alerts` 上下文（是醫師/admin 手動改狀態，不是偵測器觸發），
       憑空 fan-out 一則「偵測到紅旗」通知給全體在職醫師會製造假警報。
       `cancelled` **刻意不建通知**：`NotificationType` 只有 red_flag /
       session_complete / report_ready / system 四種，沒有「場次被取消」語意的
       類型；新增列舉值要 Alembic `ALTER TYPE ... ADD VALUE` + 通知偏好欄位 +
       i18n 字串，與 `tasks/session_timeout` 的同一格是同一個結論。
    6. **設 `_terminated`**：**不適用**——那是 `conversation_handler` 的
       `session_context` 行程內旗標，REST 行程沒有那份 context（見第 3 點）。

    任何一步失敗都不可回滾已 commit 的狀態轉移，故全部包在 try/except 內只記
    warning；SOAP 派送刻意獨立於廣播之外（廣播掛掉不可讓醫師端等不到報告）。
    """
    try:
        await _refresh_session_state_cache(session_id, new_status)
    except Exception as exc:  # pragma: no cover - 快取失敗非致命
        logger.warning(
            "REST 狀態轉移後更新 Redis 場次狀態快取失敗（非致命） | session=%s, error=%s",
            session_id,
            str(exc),
        )

    try:
        from app.cache.redis_client import get_redis
        from app.websocket.connection_manager import manager
        from app.websocket.dashboard_handler import broadcast_queue_and_stats

        code = _STATUS_CHANGED_CODES.get(new_status)
        if code is not None:
            await manager.broadcast_localized_dashboard(
                msg_type="session_status_changed",
                code=code,
                params={},
                severity=_STATUS_CHANGED_SEVERITIES.get(new_status, "info"),
                extra={
                    "sessionId": str(session_id),
                    "status": new_status.value,
                    "previousStatus": getattr(
                        previous_status, "value", str(previous_status)
                    ),
                },
            )
        redis = await get_redis()
        await broadcast_queue_and_stats(db, redis)
    except Exception as exc:  # pragma: no cover - 推播失敗非致命
        logger.warning(
            "REST 狀態轉移後推播儀表板事件失敗（非致命） | session=%s, error=%s",
            session_id,
            str(exc),
        )

    if new_status in _SOAP_ON_TERMINAL:
        try:
            from app.websocket.conversation_handler import (
                _generate_soap_report_async,
            )

            await _generate_soap_report_async(session_id=str(session_id))
        except Exception as exc:  # pragma: no cover - helper 自身已吞例外
            logger.error(
                "REST 狀態轉移後 SOAP 派送失敗 | session=%s, error=%s",
                session_id,
                str(exc),
                exc_info=True,
            )


async def _authorize_session_access(
    db: AsyncSession,
    session: Session,
    current_user: Any,
) -> None:
    """
    校驗 current_user 是否能存取此 session。無權限則 raise ForbiddenException,
    不存在 current_user 則 raise UnauthorizedException 語意(此處視為 Forbidden)。

    角色規則:
      - admin         → 無限制
      - doctor        → 擁有 doctor_id == self OR doctor_id 為空(未指派) 的場次
      - patient       → 只能看自己名下 patient 的場次(Session.patient.user_id == self.id)
      - 其餘/未知角色 → 拒絕
    """
    if current_user is None:
        raise ForbiddenException("errors.session_access_no_principal")

    role = _get_user_role(current_user)
    user_id = getattr(current_user, "id", None)

    if role == UserRole.ADMIN:
        return

    if role == UserRole.DOCTOR:
        if session.doctor_id is None or session.doctor_id == user_id:
            return
        raise ForbiddenException(
            "errors.session_forbidden_other_doctor",
            details={"session_id": str(session.id)},
        )

    if role == UserRole.PATIENT:
        # 取出 patient.user_id。避免 lazy-load 錯誤,用明確 query 核對。
        result = await db.execute(
            select(Patient.user_id).where(Patient.id == session.patient_id)
        )
        owner_user_id = result.scalar_one_or_none()
        if owner_user_id is not None and owner_user_id == user_id:
            return
        raise ForbiddenException(
            "errors.session_forbidden_patient",
            details={"session_id": str(session.id)},
        )

    # 未知角色 — 保守拒絕
    raise ForbiddenException(
        "errors.session_unknown_role_access",
        details={"session_id": str(session.id), "role": str(role)},
    )


def _parse_date_filter(value: Optional[str], field: str) -> Optional[datetime]:
    """
    解析 date_from / date_to 查詢字串為 datetime。

    - None / 空字串 → None（不套用篩選）
    - 無法解析 → ValidationException（422），訊息使用 ISO-8601 日期格式錯誤鍵。
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValidationException(
            "errors.invalid_date_format",
            details={"field": field, "value": value},
        )


def _parse_cursor(cursor: Optional[str]) -> Optional[UUID]:
    """
    將 cursor 解析為 UUID。

    cursor 為「上一頁最後一筆的 id」（UUID 字串）。無法解析為合法 UUID 時
    保守視為「無 cursor」（回傳 None），避免把無效字串直接餵進 SQL，
    同時維持既有「cursor 查不到對應 record 即從頭分頁」的向後相容行為。
    """
    if not cursor:
        return None
    try:
        return UUID(str(cursor))
    except (ValueError, AttributeError, TypeError):
        return None


# ── 排序白名單 ───────────────────────────────────────────
# 僅允許白名單欄位排序，避免任意欄位字串造成 500 或資訊外洩。
# 注意：cursor 分頁的 keyset 條件以 created_at + id 為基準，故所有排序
# 都以 (主要欄位, id) 作為 tiebreaker，維持分頁穩定。
_SORTABLE_COLUMNS: dict[str, Any] = {
    "created_at": Session.created_at,
    "updated_at": Session.updated_at,
    "started_at": Session.started_at,
    "completed_at": Session.completed_at,
    "status": Session.status,
}


def _resolve_sort(sort_by: Optional[str], sort_order: Optional[str]) -> tuple[Any, bool]:
    """
    解析白名單排序欄位與方向。

    Returns:
        (column, descending)；sort_by 不在白名單退回 created_at，
        sort_order 非 asc 一律視為 desc（向後相容預設）。
    """
    column = _SORTABLE_COLUMNS.get(sort_by or "", Session.created_at)
    descending = (sort_order or "desc").lower() != "asc"
    return column, descending


def _apply_sort(query: Any, column: Any, descending: bool) -> Any:
    """套用排序，並一律附加 Session.id 作為 tiebreaker 確保分頁穩定。"""
    if descending:
        return query.order_by(column.desc(), Session.id.desc())
    return query.order_by(column.asc(), Session.id.asc())


def _apply_cursor_keyset(
    query: Any, cursor_record: Any, column: Any, descending: bool
) -> Any:
    """
    依排序方向套用 keyset 分頁條件，使 cursor 與 sort 一致。

    descending → 取「排在 cursor 之後」= column < cursor_value，tie 時 id < cursor_id。
    ascending  → column > cursor_value，tie 時 id > cursor_id。
    """
    cursor_value = getattr(cursor_record, column.key)
    cursor_id = cursor_record.id
    if descending:
        return query.where(
            (column < cursor_value)
            | ((column == cursor_value) & (Session.id < cursor_id))
        )
    return query.where(
        (column > cursor_value)
        | ((column == cursor_value) & (Session.id > cursor_id))
    )


# 合法狀態轉移表已抽到 app/core/session_state.py 作為單一權威（REST + WS 共用）；
# 此處 re-export 保持既有 import 相容。
from app.core.session_state import VALID_TRANSITIONS, is_valid_transition  # noqa: E402


class SessionService:
    """問診場次業務邏輯"""

    @staticmethod
    async def create(db: AsyncSession, data: dict[str, Any]) -> Session:
        """
        建立問診場次（初始狀態為 waiting）

        Args:
            data: 場次資料（patient_id, chief_complaint_id, ...）

        Returns:
            新建的 Session 物件
        """
        now = utc_now()
        session = Session(
            patient_id=data["patient_id"],
            doctor_id=data.get("doctor_id"),
            chief_complaint_id=data["chief_complaint_id"],
            chief_complaint_text=data.get("chief_complaint_text"),
            status=SessionStatus.WAITING,
            red_flag=False,
            language=data.get("language") or settings.DEFAULT_LANGUAGE,
            intake_data=data.get("intake"),
            intake_completed_at=now if data.get("intake") else None,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        status: Optional[SessionStatus] = None,
        doctor_id: Optional[UUID] = None,
        patient_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        取得場次列表（Cursor-based 分頁 + 多條件篩選）

        Args:
            cursor: 分頁游標（UUID 或字串；非合法 UUID 視為無 cursor）
            limit: 每頁筆數
            status: 篩選狀態
            doctor_id: 篩選醫師
            patient_id: 篩選病患
            date_from: 起始日期
            date_to: 結束日期
            sort_by: 排序欄位（白名單外退回 created_at）
            sort_order: 排序方向（asc / desc，預設 desc）
        """
        limit = min(limit, 100)
        _cursor = _parse_cursor(cursor) if not isinstance(cursor, UUID) else cursor
        _sort_column, _sort_desc = _resolve_sort(sort_by, sort_order)

        query = select(Session).options(selectinload(Session.patient))
        query = _apply_sort(query, _sort_column, _sort_desc)

        # 條件篩選
        if status:
            query = query.where(Session.status == status)
        if doctor_id:
            query = query.where(Session.doctor_id == doctor_id)
        if patient_id:
            query = query.where(Session.patient_id == patient_id)
        if date_from:
            query = query.where(Session.created_at >= date_from)
        if date_to:
            query = query.where(Session.created_at <= date_to)

        # Cursor 分頁 — keyset 條件依排序方向套用
        if _cursor is not None:
            result = await db.execute(
                select(Session).where(Session.id == _cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = _apply_cursor_keyset(
                    query, cursor_record, _sort_column, _sort_desc
                )

        result = await db.execute(query.limit(limit + 1))
        sessions = result.scalars().all()

        has_more = len(sessions) > limit
        if has_more:
            sessions = sessions[:limit]

        # 近似總筆數
        count_query = select(func.count()).select_from(Session)
        if status:
            count_query = count_query.where(Session.status == status)
        if doctor_id:
            count_query = count_query.where(Session.doctor_id == doctor_id)
        if patient_id:
            count_query = count_query.where(Session.patient_id == patient_id)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": sessions,
            "pagination": {
                "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(db: AsyncSession, session_id: UUID) -> Session:
        """
        根據 ID 取得場次（含對話紀錄）

        Raises:
            SessionNotFoundException: 場次不存在
        """
        result = await db.execute(
            select(Session)
            .options(
                selectinload(Session.conversations),
                selectinload(Session.patient),
            )
            .where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundException()
        return session

    @staticmethod
    async def update_status_static(
        db: AsyncSession,
        session_id: UUID,
        new_status: SessionStatus,
        reason: Optional[str] = None,
        actor_user_id: Optional[UUID] = None,
    ) -> Session:
        """
        更新場次狀態（含狀態轉移驗證）

        Args:
            session_id: 場次 ID
            new_status: 目標狀態
            reason: 狀態變更原因（取消、紅旗等）
            actor_user_id: 操作者 user id（REST 路徑帶 current_user；供稽核）

        Raises:
            SessionNotFoundException: 場次不存在
            InvalidStatusTransitionException: 不合法的狀態轉移
        """
        session = await SessionService.get_by_id(db, session_id)
        current_status = session.status

        # 驗證狀態轉移合法性（單一權威 is_valid_transition，REST 維持嚴格：不允許 no-op）
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if not is_valid_transition(current_status, new_status):
            raise InvalidStatusTransitionException(
                "errors.status_transition_not_allowed",
                details={
                    "current_status": current_status.value,
                    "requested_status": new_status.value,
                    "allowed_transitions": [s.value for s in allowed],
                },
                message_kwargs={
                    "current": current_status.value,
                    "target": new_status.value,
                },
            )

        now = utc_now()
        session.status = new_status
        session.updated_at = now

        # 狀態特定處理
        if new_status == SessionStatus.IN_PROGRESS:
            session.started_at = now

        elif new_status in (
            SessionStatus.COMPLETED,
            SessionStatus.ABORTED_RED_FLAG,
            SessionStatus.CANCELLED,
        ):
            session.completed_at = now
            # 計算持續秒數
            if session.started_at:
                delta = now - session.started_at
                session.duration_seconds = int(delta.total_seconds())

        if new_status == SessionStatus.ABORTED_RED_FLAG:
            session.red_flag = True
            if reason:
                session.red_flag_reason = reason

        # SESSION_START / SESSION_END 稽核（REST 路徑；WS 路徑由
        # conversation_handler._update_session_status 負責，兩邊不重疊）。
        audit_action: Optional[AuditAction] = None
        if new_status == SessionStatus.IN_PROGRESS:
            audit_action = AuditAction.SESSION_START
        elif new_status in (
            SessionStatus.COMPLETED,
            SessionStatus.ABORTED_RED_FLAG,
            SessionStatus.CANCELLED,
        ):
            audit_action = AuditAction.SESSION_END
        if audit_action is not None:
            from app.services.audit_log_service import AuditLogService

            await AuditLogService.log(
                db,
                user_id=actor_user_id,
                action=audit_action,
                resource_type="session",
                resource_id=str(session.id),
                details={
                    "previous_status": current_status.value,
                    "new_status": new_status.value,
                    "reason": reason,
                    "via": "rest",
                },
                language=session.language,
            )

        # EM-2（不變式 #20 第 5 件事「建醫師通知」）：WS 的
        # `_update_session_status` 在轉 completed 且場次已指派醫師時會建一則
        # SESSION_COMPLETE 通知，REST 這條路徑以前完全沒有 —— 同一個事實
        # （這場問診結束了）走 REST 就沒人被通知。補齊成對稱。
        # 未指派醫師（院內 kiosk 常態）時 no-op，與 WS 端同一判準。
        if new_status == SessionStatus.COMPLETED and session.doctor_id is not None:
            from app.services.notification_service import NotificationService

            try:
                await NotificationService.notify_session_complete(
                    db,
                    session_id=session.id,
                    doctor_id=session.doctor_id,
                    patient_id=session.patient_id,
                )
            except Exception as exc:  # pragma: no cover - 通知失敗不可擋轉移
                logger.warning(
                    "REST 場次完成通知建立失敗（非致命，轉移已生效） | session=%s, error=%s",
                    session.id,
                    str(exc),
                )

        await db.flush()
        return session

    @staticmethod
    async def end_for_language_switch(
        db: AsyncSession,
        session_id: UUID,
        to_language: str,
        current_user: Any,
    ) -> Session:
        """
        M16 / G35b：使用者在問診中切語言 → 收掉當前場次並改偏好語言。

        - 授權沿用 `_authorize_session_access`（病患本人 / 負責或未指派醫師 / admin），
          不另立一套規則
        - to_language 必須在 SUPPORTED_LANGUAGES（schema 層已驗證）
        - 終態與轉移合法性一律問 `app/core/session_state.py`（不變式 #16 單一權威），
          不在此處自帶狀態白名單；轉移表改了這裡自動跟著改
        - 冪等：場次已在終態就不再轉移、直接回成功。切語言前的守衛可能被重試或連點，
          回 409 會讓「語言切不掉」，而此時「沒有孤兒 in_progress 場次」的目的已達成
        - 非終態但轉移表不允許 `→ cancelled` → InvalidStatusTransitionException（409），
          明確報錯而非靜默成功
        - audit_log 紀錄 from_lang / to_lang / session_id（冪等路徑額外記當時狀態）
        """
        from app.services.audit_log_service import AuditLogService

        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)

        # allowed_next 為 None 代表狀態不在轉移表內（不該發生）；為 [] 代表已是終態。
        allowed_next = VALID_TRANSITIONS.get(session.status)
        can_cancel = is_valid_transition(session.status, SessionStatus.CANCELLED)
        already_terminal = allowed_next == []
        # 表外狀態走到這裡時未必是 enum，用 getattr 取值避免在「回明確錯誤」的路徑上 500。
        current_status_value = getattr(session.status, "value", str(session.status))

        if not can_cancel and not already_terminal:
            raise InvalidStatusTransitionException(
                "errors.session_not_switchable",
                details={
                    "session_id": str(session.id),
                    "current_status": current_status_value,
                    "requested_status": SessionStatus.CANCELLED.value,
                    "allowed_transitions": [s.value for s in (allowed_next or [])],
                },
            )

        from_lang = session.language
        now = utc_now()
        # L-3：保留變更前狀態，供 SessionStatusResponse.previous_status 回傳。
        previous_status = session.status

        if can_cancel:
            session.status = SessionStatus.CANCELLED
            session.completed_at = now
            session.updated_at = now
            if session.started_at:
                session.duration_seconds = int((now - session.started_at).total_seconds())

        # 更新 user preferred_language（下次登入 / 下一場新 session 會套用）。
        # 冪等路徑也要更新——呼叫端收到 200 就會認為語言偏好已生效。
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is not None:
                user.preferred_language = to_language
                user.updated_at = now

        details: dict[str, Any] = {
            "from_lang": from_lang,
            "to_lang": to_language,
        }
        if not can_cancel:
            # 冪等路徑：場次不是這次呼叫收掉的，記下當時狀態以便回溯
            details["session_already_terminal"] = True
            details["previous_status"] = current_status_value

        await AuditLogService.log(
            db,
            user_id=user_id,
            action=AuditAction.LANGUAGE_SWITCH_END_SESSION,
            resource_type="session",
            resource_id=str(session.id),
            details=details,
            language=from_lang,
        )

        await db.flush()
        # D-8：切語言把場次收成 cancelled 也是一次終態轉移，以前完全沒有任何
        # dashboard 推播 —— 醫師端排隊清單會留著一筆早已被病患切掉的場次，直到
        # 下一個事件才被動刷新。與 P7（`tasks/session_timeout` 的逾時 cancelled）
        # 對齊：廣播 `session_status_changed` + 刷新 queue/stats、**不派 SOAP**。
        # 冪等路徑（場次早已是終態、本次沒轉移）不推播，避免重複事件。
        if can_cancel:
            await db.commit()
            await _after_status_transition(
                db,
                session_id=session.id,
                previous_status=previous_status,
                new_status=SessionStatus.CANCELLED,
            )
        session.previous_status = previous_status
        return session

    @staticmethod
    async def get_conversations_static(
        db: AsyncSession,
        session_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        取得場次的對話紀錄

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        # 確認場次存在
        await SessionService.get_by_id(db, session_id)

        query = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.sequence_number.asc())
        )

        # cursor 為上一頁最後一筆 Conversation.id（UUID）；非合法 UUID 視為無 cursor。
        _cursor = _parse_cursor(cursor)
        if _cursor is not None:
            result = await db.execute(
                select(Conversation).where(Conversation.id == _cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    Conversation.sequence_number > cursor_record.sequence_number
                )

        result = await db.execute(query.limit(limit + 1))
        conversations = result.scalars().all()

        has_more = len(conversations) > limit
        if has_more:
            conversations = conversations[:limit]

        count_result = await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.session_id == session_id)
        )
        total_count = count_result.scalar() or 0

        return {
            "data": conversations,
            "pagination": {
                "next_cursor": str(conversations[-1].id) if has_more and conversations else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def assign_doctor_static(
        db: AsyncSession,
        session_id: UUID,
        doctor_id: UUID,
    ) -> Session:
        """
        指派醫師至場次

        Raises:
            SessionNotFoundException: 場次不存在
        """
        session = await SessionService.get_by_id(db, session_id)
        session.doctor_id = doctor_id
        session.updated_at = utc_now()
        await db.flush()
        return session

    # --- Instance method wrappers for Router compatibility ---
    async def create_session(
        self,
        db: AsyncSession,
        data: Any,
        current_user: Any = None,
        accept_language: Optional[str] = None,
    ) -> Session:
        import random
        from datetime import date
        from app.models.enums import Gender
        from app.models.patient import Patient
        from app.models.user import User

        data_dict = data.model_dump(exclude_none=True)
        patient_info = data_dict.pop("patient_info", None)
        requested_patient_id = data_dict.get("patient_id")

        # 解析語言：payload > user.preferred_language > Accept-Language > default
        data_dict["language"] = resolve_language(
            payload_language=data_dict.get("language"),
            user=current_user,
            accept_language_header=accept_language,
        )

        current_user_id = current_user.id if current_user else None

        def _generate_mrn() -> str:
            return f"P-{utc_now().year}-{random.randint(100000, 999999)}"

        patient: Optional[Any] = None

        # 1a) 醫師/管理員代病患建場次（2026-08-22，醫師端語音問診入口）：
        #     指定的 patient_id 不受「屬於自己」限制——醫師在診間拿著裝置訪談病患，
        #     場次要記在**該病患**的病歷下，不是醫師自己名下。
        #     授權邊界：只有 doctor/admin 走這條；指定的 id 必須真的存在（查無→
        #     fall through 到下面的自有邏輯，對醫師而言最終會 404/建在自己名下，
        #     所以前端一律從病患清單帶真實 id）。存取控制與後續 WS 連線由
        #     _validate_session_access 把關（doctor 可存取 doctor_id 為 NULL 的場次，
        #     本場次建立時 doctor_id 即為 NULL，故建立者本人一定連得上）。
        creator_role = _get_user_role(current_user)
        if requested_patient_id and creator_role in (UserRole.DOCTOR, UserRole.ADMIN):
            result = await db.execute(
                select(Patient).where(Patient.id == requested_patient_id)
            )
            patient = result.scalar_one_or_none()

        # 1) 明確指定 patient_id → 必須屬於目前使用者才採用（病患自己的路徑）
        if patient is None and requested_patient_id and current_user_id:
            result = await db.execute(
                select(Patient).where(
                    and_(
                        Patient.id == requested_patient_id,
                        Patient.user_id == current_user_id,
                    )
                )
            )
            patient = result.scalar_one_or_none()

        # 2) 帶 patient_info → 依 (user_id, name, dob, phone) get_or_create
        if patient is None and patient_info is not None and current_user_id is not None:
            info_name = patient_info.get("name")
            info_gender_raw = patient_info.get("gender")
            info_gender: Optional[Gender]
            if isinstance(info_gender_raw, Gender) or info_gender_raw is None:
                info_gender = info_gender_raw
            else:
                try:
                    info_gender = Gender(info_gender_raw)
                except ValueError:
                    info_gender = Gender.OTHER
            info_dob = patient_info.get("date_of_birth")
            info_phone = patient_info.get("phone")

            conditions = [
                Patient.user_id == current_user_id,
                Patient.name == info_name,
                Patient.date_of_birth == info_dob,
            ]
            # phone 可能為 None，NULL 對 NULL 也算命中
            if info_phone is None:
                conditions.append(Patient.phone.is_(None))
            else:
                conditions.append(Patient.phone == info_phone)

            existing_result = await db.execute(
                select(Patient).where(and_(*conditions))
            )
            patient = existing_result.scalar_one_or_none()

            if patient is None:
                mrn = _generate_mrn()
                patient = Patient(
                    user_id=current_user_id,
                    medical_record_number=mrn,
                    name=info_name,
                    gender=info_gender or Gender.OTHER,
                    date_of_birth=info_dob or date(1900, 1, 1),
                    phone=info_phone,
                )
                db.add(patient)
                await db.flush()

        # 3) Fallback — 回退舊行為：使用者名下第一位病患，否則自動建立 placeholder
        if patient is None and current_user_id is not None:
            fallback_result = await db.execute(
                select(Patient)
                .where(Patient.user_id == current_user_id)
                .order_by(Patient.created_at.asc())
            )
            patient = fallback_result.scalars().first()

            if patient is None:
                user_result = await db.execute(
                    select(User).where(User.id == current_user_id)
                )
                user_obj = user_result.scalar_one_or_none()
                mrn = _generate_mrn()
                patient = Patient(
                    user_id=current_user_id,
                    medical_record_number=mrn,
                    # DB 要求 NOT NULL,使用者沒填名字時以英文 "Unknown" 佔位,
                    # 避免中文「未知」外流到 en-US / ja-JP 等場次的病患清單。
                    name=user_obj.name if user_obj else "Unknown",
                    gender=Gender.OTHER,
                    date_of_birth=date(1900, 1, 1),
                )
                db.add(patient)
                await db.flush()

        if patient is None:
            raise NotFoundException("errors.session_patient_unresolved")

        data_dict["patient_id"] = patient.id

        session = await SessionService.create(db, data_dict)
        await db.commit()
        # Re-fetch with conversations eagerly loaded to avoid lazy-load error during serialization
        result = await db.execute(
            select(Session)
            .options(
                selectinload(Session.conversations),
                selectinload(Session.patient),
            )
            .where(Session.id == session.id)
        )
        created = result.scalar_one()
        # H-8：場次建立成功（已 commit）後，向儀表板推播 session_created
        # 與最新 queue/stats。helper 不可拋例外，不影響回傳。
        await _broadcast_session_created(db, created)
        return created

    async def list_sessions(
        self,
        db: AsyncSession,
        current_user: Any = None,
        cursor: Optional[str] = None,
        limit: int = 20,
        status: Optional[str] = None,
        patient_id: Optional[UUID] = None,
        doctor_id: Optional[UUID] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        依角色限縮可見場次。
          - admin   → 全部
          - doctor  → 自己負責 + 未指派(doctor_id IS NULL)
          - patient → 自己名下 Patient 底下的所有 session
          - 無角色  → 403
        傳入的 doctor_id / patient_id 過濾條件會與角色限制做 AND;
        禁止一般使用者靠手動傳參數跳脫自身範圍(下方會強制覆寫)。
        """
        if current_user is None:
            raise ForbiddenException("errors.session_list_no_principal")

        role = _get_user_role(current_user)
        user_id = getattr(current_user, "id", None)

        _date_from = _parse_date_filter(date_from, "date_from")
        _date_to = _parse_date_filter(date_to, "date_to")
        _cursor = _parse_cursor(cursor)

        _status: Optional[SessionStatus] = None
        if status is not None:
            try:
                _status = SessionStatus(status) if not isinstance(status, SessionStatus) else status
            except ValueError:
                _status = None  # 無效字串直接忽略,避免 500

        _patient_id = patient_id
        _doctor_id = doctor_id
        _sort_column, _sort_desc = _resolve_sort(sort_by, sort_order)

        if role == UserRole.PATIENT:
            # 以 subquery 將 patient_id 限縮為 current_user 名下所有 Patient.id
            owned_patient_ids_subq = (
                select(Patient.id).where(Patient.user_id == user_id)
            )
            # 如果呼叫端有指定 patient_id,還是要落在自己名下 → 用 get_list 不支援多 id,
            # 改在這裡手動查完整 query,以 patient_id IN subquery 強制限縮。
            query = (
                select(Session)
                .options(selectinload(Session.patient))
                .where(Session.patient_id.in_(owned_patient_ids_subq))
            )
            query = _apply_sort(query, _sort_column, _sort_desc)
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _status:
                query = query.where(Session.status == _status)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            # Cursor 分頁 — keyset 條件依排序方向套用，與 sort 保持一致
            if _cursor is not None:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == _cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = _apply_cursor_keyset(
                        query, cursor_record, _sort_column, _sort_desc
                    )

            effective_limit = min(limit, 100)
            result = await db.execute(query.limit(effective_limit + 1))
            sessions = result.scalars().all()
            has_more = len(sessions) > effective_limit
            if has_more:
                sessions = sessions[:effective_limit]

            count_query = (
                select(func.count())
                .select_from(Session)
                .where(Session.patient_id.in_(owned_patient_ids_subq))
            )
            if _status:
                count_query = count_query.where(Session.status == _status)
            if _patient_id is not None:
                count_query = count_query.where(Session.patient_id == _patient_id)
            total_count = (await db.execute(count_query)).scalar() or 0

            return {
                "data": sessions,
                "pagination": {
                    "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                    "has_more": has_more,
                    "limit": effective_limit,
                    "total_count": total_count,
                },
            }

        if role == UserRole.DOCTOR:
            # 醫師: 自己負責 + 未指派。呼叫端傳的 doctor_id 會被強制覆寫為 self.id,
            # 避免透過 query 參數窺探其他醫師負責的場次。
            effective_limit = min(limit, 100)
            query = (
                select(Session)
                .options(selectinload(Session.patient))
                .where(
                    (Session.doctor_id == user_id) | (Session.doctor_id.is_(None))
                )
            )
            query = _apply_sort(query, _sort_column, _sort_desc)
            if _status:
                query = query.where(Session.status == _status)
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            if _cursor is not None:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == _cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = _apply_cursor_keyset(
                        query, cursor_record, _sort_column, _sort_desc
                    )

            result = await db.execute(query.limit(effective_limit + 1))
            sessions = result.scalars().all()
            has_more = len(sessions) > effective_limit
            if has_more:
                sessions = sessions[:effective_limit]

            count_query = (
                select(func.count())
                .select_from(Session)
                .where(
                    (Session.doctor_id == user_id) | (Session.doctor_id.is_(None))
                )
            )
            if _status:
                count_query = count_query.where(Session.status == _status)
            if _patient_id is not None:
                count_query = count_query.where(Session.patient_id == _patient_id)
            total_count = (await db.execute(count_query)).scalar() or 0

            return {
                "data": sessions,
                "pagination": {
                    "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                    "has_more": has_more,
                    "limit": effective_limit,
                    "total_count": total_count,
                },
            }

        if role == UserRole.ADMIN:
            return await SessionService.get_list(
                db,
                _cursor,
                limit,
                _status,
                _doctor_id,
                _patient_id,
                _date_from,
                _date_to,
                sort_by=sort_by,
                sort_order=sort_order,
            )

        # 未知角色
        raise ForbiddenException("errors.session_unknown_role")

    async def get_session(
        self, db: AsyncSession, session_id: UUID, current_user: Any = None
    ) -> Session:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)
        return session

    # 病患不得自行觸發的紅旗 / 終止類狀態 — 僅醫師 / admin 可設定，
    # 避免病患透過 REST 端點偽造 aborted_red_flag 觸發紅旗流程。
    _PRIVILEGED_STATUSES: frozenset[SessionStatus] = frozenset(
        {SessionStatus.ABORTED_RED_FLAG}
    )

    async def update_status(
        self,
        db: AsyncSession,
        session_id: UUID,
        new_status: SessionStatus,
        reason: Optional[str] = None,
        current_user: Any = None,
    ) -> Session:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)

        # 角色限制：紅旗 / 終止類狀態僅限 doctor / admin 變更，
        # 病患不得自行把場次改成 aborted_red_flag 等紅旗狀態。
        if new_status in self._PRIVILEGED_STATUSES:
            role = _get_user_role(current_user)
            if role not in (UserRole.DOCTOR, UserRole.ADMIN):
                raise ForbiddenException(
                    "errors.session_forbidden_patient",
                    details={
                        "session_id": str(session.id),
                        "requested_status": new_status.value,
                    },
                )

        previous_status = session.status
        updated = await SessionService.update_status_static(
            db,
            session_id,
            new_status,
            reason,
            actor_user_id=getattr(current_user, "id", None),
        )
        # EM-2：附帶效應必須在 **commit 之後** 才做，否則
        # (a) Celery worker 在另一個行程／連線 SELECT 場次時還讀得到 in_progress，
        #     SOAP 會用「尚未結束」的狀態去生成；
        # (b) `broadcast_queue_and_stats` 重算排隊會算到舊狀態，推給醫師端的清單
        #     反而更舊。
        # 沿用 `create_session` 的既有慣例（明確 commit → 再推播）；FastAPI 的
        # `get_db` 之後再 commit 一次是無害的 no-op。
        await db.commit()
        await _after_status_transition(
            db,
            session_id=session_id,
            previous_status=previous_status,
            new_status=new_status,
        )
        # L-3：REST 路徑回傳變更前狀態（供 SessionStatusResponse.previous_status）。
        updated.previous_status = previous_status
        return updated

    async def get_conversations(
        self,
        db: AsyncSession,
        session_id: UUID,
        current_user: Any = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)
        return await SessionService.get_conversations_static(db, session_id, cursor, limit)

    async def assign_doctor(
        self, db: AsyncSession, session_id: UUID, doctor_id: UUID, current_user: Any = None
    ) -> Session:
        # Router 已透過 require_role("doctor","admin") 限制角色,
        # 這裡仍做 ownership 檢查(防止 doctor A 把其他醫師已負責的 session 搶走)。
        session = await SessionService.get_by_id(db, session_id)
        role = _get_user_role(current_user)
        if role == UserRole.ADMIN:
            # admin 可任意指派
            pass
        elif role == UserRole.DOCTOR:
            # doctor 只能把未指派的場次搶起來,或把自己名下的場次轉出給自己(no-op)
            if session.doctor_id is not None and session.doctor_id != getattr(current_user, "id", None):
                raise ForbiddenException(
                    "errors.assign_doctor_conflict",
                    details={"session_id": str(session.id)},
                )
        else:
            raise ForbiddenException("errors.assign_doctor_role_required")
        return await SessionService.assign_doctor_static(db, session_id, doctor_id)
