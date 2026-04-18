"""
紅旗警示服務
- 警示 CRUD
- 警示確認
- 紅旗規則管理
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlertAlreadyAcknowledgedException,
    NotFoundException,
)
from app.models.enums import AlertSeverity, AuditAction, RedFlagConfidence
from app.models.red_flag_alert import RedFlagAlert
from app.models.red_flag_rule import RedFlagRule
from app.utils.datetime_utils import utc_now


class AlertService:
    """紅旗警示業務邏輯"""

    # ── 警示 CRUD ─────────────────────────────────────────

    @staticmethod
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        severity: Optional[AlertSeverity] = None,
        acknowledged: Optional[bool] = None,
        session_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        """
        取得警示列表（Cursor-based 分頁）

        Args:
            cursor: 分頁游標
            limit: 每頁筆數
            severity: 篩選嚴重度
            acknowledged: 篩選是否已確認
            session_id: 篩選場次
        """
        limit = min(limit, 100)

        query = select(RedFlagAlert).order_by(
            RedFlagAlert.created_at.desc(), RedFlagAlert.id.desc()
        )

        if severity:
            query = query.where(RedFlagAlert.severity == severity)
        if acknowledged is not None:
            if acknowledged:
                query = query.where(RedFlagAlert.acknowledged_by.isnot(None))
            else:
                query = query.where(RedFlagAlert.acknowledged_by.is_(None))
        if session_id:
            query = query.where(RedFlagAlert.session_id == session_id)

        if cursor:
            result = await db.execute(
                select(RedFlagAlert).where(RedFlagAlert.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    (RedFlagAlert.created_at < cursor_record.created_at)
                    | (
                        (RedFlagAlert.created_at == cursor_record.created_at)
                        & (RedFlagAlert.id < cursor_record.id)
                    )
                )

        result = await db.execute(query.limit(limit + 1))
        alerts = result.scalars().all()

        has_more = len(alerts) > limit
        if has_more:
            alerts = alerts[:limit]

        count_query = select(func.count()).select_from(RedFlagAlert)
        if severity:
            count_query = count_query.where(RedFlagAlert.severity == severity)
        if session_id:
            count_query = count_query.where(RedFlagAlert.session_id == session_id)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": alerts,
            "pagination": {
                "next_cursor": str(alerts[-1].id) if has_more and alerts else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(db: AsyncSession, alert_id: UUID) -> RedFlagAlert:
        """
        根據 ID 取得警示

        Raises:
            NotFoundException: 警示不存在
        """
        result = await db.execute(
            select(RedFlagAlert).where(RedFlagAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if alert is None:
            raise NotFoundException("errors.alert_not_found")
        return alert

    @staticmethod
    async def create(db: AsyncSession, data: dict[str, Any]) -> RedFlagAlert:
        """
        建立紅旗警示 + 觸發推播通知

        Args:
            data: 警示資料

        Returns:
            新建的 RedFlagAlert 物件
        """
        # TODO-M8 / TODO-E6: confidence + canonical_id 欄位
        # - confidence 若未傳入則預設 rule_hit(向後相容)。
        # - 值可為 str 或 RedFlagConfidence enum;ORM mapper 會自動轉型。
        confidence_val = data.get("confidence") or RedFlagConfidence.RULE_HIT
        if isinstance(confidence_val, str):
            try:
                confidence_val = RedFlagConfidence(confidence_val)
            except ValueError:
                confidence_val = RedFlagConfidence.RULE_HIT

        alert = RedFlagAlert(
            session_id=data["session_id"],
            conversation_id=data.get("conversation_id"),
            alert_type=data["alert_type"],
            severity=data["severity"],
            title=data["title"],
            description=data.get("description"),
            trigger_reason=data["trigger_reason"],
            trigger_keywords=data.get("trigger_keywords"),
            matched_rule_id=data.get("matched_rule_id"),
            llm_analysis=data.get("llm_analysis"),
            suggested_actions=data.get("suggested_actions"),
            canonical_id=data.get("canonical_id"),
            confidence=confidence_val,
            language=data.get("language") or "zh-TW",
            created_at=utc_now(),
        )
        db.add(alert)
        await db.flush()

        # TODO-M8:uncovered_locale(locale 覆蓋不足,fail-safe 觸發 escalation)
        # 必須寫入 audit log 以利後續檢視哪些紅旗的 i18n 規則需要補。
        # 走 try/except 以免 audit 失敗影響警示建立。
        if confidence_val == RedFlagConfidence.UNCOVERED_LOCALE:
            try:
                from app.services.audit_log_service import AuditLogService
                await AuditLogService.log(
                    db,
                    user_id=None,
                    action=AuditAction.CREATE,
                    resource_type="red_flag_alert",
                    resource_id=str(alert.id),
                    details={
                        "reason": "uncovered_locale_escalation",
                        "canonical_id": data.get("canonical_id"),
                        "language": data.get("language"),
                        "session_id": str(data["session_id"]),
                        "severity": (
                            data["severity"].value
                            if hasattr(data["severity"], "value")
                            else data["severity"]
                        ),
                    },
                )
            except Exception:
                # audit 失敗不應阻擋警示建立,但要 log 以便排查
                import logging
                logging.getLogger(__name__).warning(
                    "uncovered_locale escalation audit log failed",
                    exc_info=True,
                )

        # 觸發推播通知（非同步任務）
        try:
            from app.tasks.notification_retry import send_push_notification_task

            # 取得場次的負責醫師以發送通知
            from app.models.session import Session

            session_result = await db.execute(
                select(Session).where(Session.id == data["session_id"])
            )
            session = session_result.scalar_one_or_none()

            if session and session.doctor_id:
                from app.utils.i18n_messages import get_message as _i18n_get
                push_title = _i18n_get(
                    "alert.push_notification_title",
                    getattr(session, "language", None),
                    title=data["title"],
                )
                send_push_notification_task.delay(
                    user_id=str(session.doctor_id),
                    title=push_title,
                    body=data.get("description", ""),
                    data={
                        "type": "red_flag",
                        "alert_id": str(alert.id),
                        "session_id": str(data["session_id"]),
                        "severity": data["severity"].value if hasattr(data["severity"], "value") else data["severity"],
                    },
                )
        except Exception:
            # 推播失敗不應影響警示建立
            pass

        return alert

    @staticmethod
    async def acknowledge(
        db: AsyncSession,
        alert_id: UUID,
        user_id: UUID,
        notes: Optional[str] = None,
    ) -> RedFlagAlert:
        """
        確認警示

        Args:
            alert_id: 警示 ID
            user_id: 確認醫師 ID
            notes: 確認備註

        Raises:
            NotFoundException: 警示不存在
            AlertAlreadyAcknowledgedException: 警示已被確認
        """
        alert = await AlertService.get_by_id(db, alert_id)

        if alert.acknowledged_by is not None:
            raise AlertAlreadyAcknowledgedException()

        now = utc_now()
        alert.acknowledged_by = user_id
        alert.acknowledged_at = now
        alert.acknowledge_notes = notes

        await db.flush()
        return alert

    # ── 紅旗規則管理 ──────────────────────────────────────

    @staticmethod
    async def get_rules(
        db: AsyncSession,
        is_active: Optional[bool] = None,
    ) -> list[RedFlagRule]:
        """
        取得紅旗規則列表

        Args:
            is_active: 篩選啟用狀態（None 表示全部）
        """
        query = select(RedFlagRule).order_by(RedFlagRule.created_at.desc())

        if is_active is not None:
            query = query.where(RedFlagRule.is_active == is_active)

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_rule(
        db: AsyncSession,
        data: dict[str, Any],
        created_by_id: Optional[UUID] = None,
    ) -> RedFlagRule:
        """
        建立紅旗規則

        Args:
            data: 規則資料
            created_by_id: 建立者 ID
        """
        now = utc_now()
        rule = RedFlagRule(
            name=data["name"],
            description=data.get("description"),
            category=data["category"],
            keywords=data["keywords"],
            regex_pattern=data.get("regex_pattern"),
            severity=data["severity"],
            suspected_diagnosis=data.get("suspected_diagnosis"),
            suggested_action=data.get("suggested_action"),
            is_active=data.get("is_active", True),
            created_by=created_by_id,
            created_at=now,
            updated_at=now,
        )
        db.add(rule)
        await db.flush()
        return rule

    @staticmethod
    async def update_rule(
        db: AsyncSession,
        rule_id: UUID,
        data: dict[str, Any],
    ) -> RedFlagRule:
        """
        更新紅旗規則

        Raises:
            NotFoundException: 規則不存在
        """
        result = await db.execute(
            select(RedFlagRule).where(RedFlagRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            raise NotFoundException("errors.red_flag_rule_not_found")

        updatable_fields = {
            "name", "description", "category", "keywords",
            "regex_pattern", "severity", "suspected_diagnosis",
            "suggested_action", "is_active",
        }
        for field, value in data.items():
            if field in updatable_fields and value is not None:
                setattr(rule, field, value)

        rule.updated_at = utc_now()
        await db.flush()
        return rule

    @staticmethod
    async def delete_rule(db: AsyncSession, rule_id: UUID) -> None:
        """
        刪除紅旗規則（軟刪除：設為非啟用）

        Raises:
            NotFoundException: 規則不存在
        """
        result = await db.execute(
            select(RedFlagRule).where(RedFlagRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            raise NotFoundException("errors.red_flag_rule_not_found")

        rule.is_active = False
        rule.updated_at = utc_now()
        await db.flush()

    # ── Aliases for router compatibility ─────────────────
    async def list_alerts(self, db, cursor=None, limit=20, severity=None,
                          alert_type=None, is_acknowledged=None, session_id=None,
                          patient_id=None, date_from=None, date_to=None):
        return await self.get_list(db, cursor=cursor, limit=limit, severity=severity,
                                   acknowledged=is_acknowledged, session_id=session_id)

    async def get_alert(self, db, alert_id):
        return await self.get_by_id(db, alert_id)

    async def acknowledge_alert(self, db, alert_id, user_id, notes=None):
        return await self.acknowledge(db, alert_id=alert_id, user_id=user_id, notes=notes)

    async def list_rules(self, db, is_active=None):
        return await self.get_rules(db, is_active=is_active)

    async def create_rule_entry(self, db, data, created_by=None):
        return await self.create_rule(db, data=data.model_dump() if hasattr(data, 'model_dump') else data, created_by_id=created_by)

    async def update_rule_entry(self, db, rule_id, data):
        return await self.update_rule(db, rule_id=rule_id, data=data.model_dump(exclude_unset=True) if hasattr(data, 'model_dump') else data)

    async def delete_rule_entry(self, db, rule_id):
        return await self.delete_rule(db, rule_id=rule_id)
