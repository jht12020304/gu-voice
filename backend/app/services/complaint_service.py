"""
主訴管理服務
- 查詢預設 / 自訂主訴（依分類分組）
- CRUD 操作
- 重新排序
- 多語：`_serialize` 依 `language` 用 `pick()` 解析 localized 欄位
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Text, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundException
from app.models.chief_complaint import ChiefComplaint
from app.utils.datetime_utils import utc_now
from app.utils.localized_field import pick


def _seed_name_by_lang(name: str, name_en: Optional[str]) -> dict[str, str]:
    """由 legacy name/name_en 生成最小 *_by_lang dict，避免留空 seed 後拿不到值。"""
    seed: dict[str, str] = {settings.DEFAULT_LANGUAGE: name}
    if name_en:
        seed["en-US"] = name_en
    return seed


def _serialize_complaint(complaint: ChiefComplaint, language: Optional[str]) -> dict[str, Any]:
    """依 language 產出 localized name / description / category，保留 `*_by_lang` 原貌。"""
    target = language or settings.DEFAULT_LANGUAGE
    return {
        "id": complaint.id,
        "name": pick(
            complaint.name_by_lang,
            target,
            legacy_value=complaint.name,
        ) or complaint.name,
        "name_en": complaint.name_en,
        "description": pick(
            complaint.description_by_lang,
            target,
            legacy_value=complaint.description,
        ),
        "category": pick(
            complaint.category_by_lang,
            target,
            legacy_value=complaint.category,
        ) or complaint.category,
        "is_default": complaint.is_default,
        "is_active": complaint.is_active,
        "display_order": complaint.display_order,
        "created_by": complaint.created_by,
        "created_at": complaint.created_at,
        "updated_at": complaint.updated_at,
        "name_by_lang": complaint.name_by_lang or None,
        "description_by_lang": complaint.description_by_lang,
        "category_by_lang": complaint.category_by_lang or None,
    }


class ComplaintService:
    """主訴業務邏輯"""

    @staticmethod
    async def get_active_list(db: AsyncSession) -> list[dict[str, Any]]:
        """
        取得所有啟用中的主訴，依分類分組並依 display_order 排序

        Returns:
            依分類分組的主訴列表
            [
                {
                    "category": "排尿症狀",
                    "complaints": [ChiefComplaint, ...]
                },
                ...
            ]
        """
        result = await db.execute(
            select(ChiefComplaint)
            .where(ChiefComplaint.is_active.is_(True))
            .order_by(ChiefComplaint.category, ChiefComplaint.display_order)
        )
        complaints = result.scalars().all()

        # 依分類分組
        grouped: dict[str, list] = {}
        for complaint in complaints:
            category = complaint.category
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(complaint)

        return [
            {"category": category, "complaints": items}
            for category, items in grouped.items()
        ]

    @staticmethod
    async def create(
        db: AsyncSession,
        data: dict[str, Any],
        created_by_id: Optional[UUID] = None,
    ) -> ChiefComplaint:
        """
        建立主訴

        多語欄位缺省時以 legacy `name/name_en/description/category` seed：
          name_by_lang     = {zh-TW: name, en-US: COALESCE(name_en, name)}
          description_by_lang = {zh-TW: description}（description 為 None 時不建）
          category_by_lang = {zh-TW: category}
        """
        now = utc_now()
        name = data["name"]
        name_en = data.get("name_en")
        description = data.get("description")
        category = data["category"]

        name_by_lang = data.get("name_by_lang") or _seed_name_by_lang(name, name_en)
        category_by_lang = data.get("category_by_lang") or {settings.DEFAULT_LANGUAGE: category}
        description_by_lang = data.get("description_by_lang")
        if description_by_lang is None and description:
            description_by_lang = {settings.DEFAULT_LANGUAGE: description}

        complaint = ChiefComplaint(
            name=name,
            name_en=name_en,
            description=description,
            category=category,
            name_by_lang=name_by_lang,
            description_by_lang=description_by_lang,
            category_by_lang=category_by_lang,
            is_default=data.get("is_default", False),
            is_active=True,
            display_order=data.get("display_order", 0),
            created_by=created_by_id,
            created_at=now,
            updated_at=now,
        )
        db.add(complaint)
        await db.flush()
        return complaint

    @staticmethod
    async def update(
        db: AsyncSession,
        complaint_id: UUID,
        data: dict[str, Any],
    ) -> ChiefComplaint:
        """
        更新主訴

        Raises:
            NotFoundException: 主訴不存在
        """
        result = await db.execute(
            select(ChiefComplaint).where(ChiefComplaint.id == complaint_id)
        )
        complaint = result.scalar_one_or_none()
        if complaint is None:
            raise NotFoundException("errors.complaint_not_found")

        updatable_fields = {
            "name", "name_en", "description", "category",
            "is_active", "display_order",
            "name_by_lang", "description_by_lang", "category_by_lang",
        }
        for field, value in data.items():
            if field in updatable_fields and value is not None:
                setattr(complaint, field, value)

        complaint.updated_at = utc_now()
        await db.flush()
        return complaint

    @staticmethod
    async def delete(db: AsyncSession, complaint_id: UUID) -> None:
        """
        刪除主訴（軟刪除：設為非啟用）

        Raises:
            NotFoundException: 主訴不存在
        """
        result = await db.execute(
            select(ChiefComplaint).where(ChiefComplaint.id == complaint_id)
        )
        complaint = result.scalar_one_or_none()
        if complaint is None:
            raise NotFoundException("errors.complaint_not_found")

        complaint.is_active = False
        complaint.updated_at = utc_now()
        await db.flush()

    @staticmethod
    async def reorder(
        db: AsyncSession,
        items: list[dict[str, Any]],
    ) -> None:
        """
        批次重新排序主訴

        Args:
            items: 排序資料列表 [{"id": UUID, "display_order": int}, ...]
        """
        for item in items:
            await db.execute(
                update(ChiefComplaint)
                .where(ChiefComplaint.id == item["id"])
                .values(
                    display_order=item["display_order"],
                    updated_at=utc_now(),
                )
            )
        await db.flush()

    # --- Instance method wrappers for Router compatibility ---

    async def list_complaints(
        self,
        db: AsyncSession,
        cursor: str | None = None,
        limit: int = 20,
        category: str | None = None,
        is_default: bool | None = None,
        search: str | None = None,
        is_active: bool = True,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """列出主訴，回傳依 language resolve 過的 localized 欄位。"""
        query = select(ChiefComplaint)

        if category:
            query = query.where(ChiefComplaint.category == category)
        if is_default is not None:
            query = query.where(ChiefComplaint.is_default == is_default)
        if search:
            # search 跨 legacy name + name_by_lang（JSONB 轉 text 再 ilike，
            # 避免因為 seed 只寫入 _by_lang 時查不到）
            query = query.where(
                or_(
                    ChiefComplaint.name.ilike(f"%{search}%"),
                    ChiefComplaint.name_by_lang.cast(Text).ilike(f"%{search}%"),
                )
            )
        if is_active is not None:
            query = query.where(ChiefComplaint.is_active == is_active)

        query = query.order_by(ChiefComplaint.display_order).limit(limit)

        result = await db.execute(query)
        items = result.scalars().all()

        return {
            "data": [_serialize_complaint(c, language) for c in items],
            "pagination": {
                "next_cursor": None,
                "has_more": False,
                "limit": limit,
                "total_count": len(items),
            },
        }

    async def create_complaint(
        self,
        db: AsyncSession,
        data: Any,
        created_by: UUID,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        complaint = await self.create(db, data.model_dump(), created_by)
        return _serialize_complaint(complaint, language)

    async def reorder_complaints(
        self,
        db: AsyncSession,
        items: list[Any],
    ) -> dict[str, Any]:
        item_dicts = [{"id": item.id, "display_order": item.display_order} for item in items]
        await self.reorder(db, item_dicts)
        return {"success": True, "reordered_count": len(items)}

    async def get_complaint(
        self,
        db: AsyncSession,
        complaint_id: UUID,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(ChiefComplaint).where(ChiefComplaint.id == complaint_id)
        )
        complaint = result.scalar_one_or_none()
        if complaint is None:
            raise NotFoundException("errors.complaint_not_found")
        return _serialize_complaint(complaint, language)

    async def update_complaint(
        self,
        db: AsyncSession,
        complaint_id: UUID,
        data: Any,
        current_user: Any,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        complaint = await self.update(db, complaint_id, data.model_dump(exclude_unset=True))
        return _serialize_complaint(complaint, language)

    async def delete_complaint(
        self,
        db: AsyncSession,
        complaint_id: UUID,
        current_user: Any,
    ) -> None:
        return await self.delete(db, complaint_id)

