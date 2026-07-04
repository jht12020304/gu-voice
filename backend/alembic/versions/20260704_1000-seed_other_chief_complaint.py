"""seed「其他」sentinel 主訴 — #5 主訴「其他」選項

病患端主訴清單只顯示 is_default=True 的預設主訴，既有 4 筆不可能涵蓋所有狀況。
本 migration 補一筆「其他」sentinel（固定 UUID、is_default=True、排最後），
病患選「其他」時 sessions.chief_complaint_id 指向此筆滿足 NOT NULL FK，
實際主訴內容存在 chief_complaint_text（病患自述）——不動 DB schema。

為什麼用固定 UUID？（同 20260418_1900 seed 的理由）
- Idempotent：重跑時以 id 做 UPSERT（INSERT ... ON CONFLICT (id) DO UPDATE），
  不會重複建立，也不會因為 sentinel 已被 sessions.chief_complaint_id 引用
  （NOT NULL FK、無 cascade）而在重跑時 DELETE 炸 FK violation
- 跨層同步：後端 conversation_handler / 前端 SelectComplaintPage 以同一常數特判
- 多環境可測：dev / staging / prod 都是同一個 id

downgrade 的取捨：sentinel 可能已被 sessions.chief_complaint_id 引用（FK），
直接 DELETE 會炸 FK。故 downgrade 一律先停用（is_active=false，病患端立即
消失），僅在完全無場次引用時才真刪。

Revision ID: a5b6c7d8e9f0
Revises: f3a4b5c6d7e8
Create Date: 2026-07-04 10:00:00.000000+08:00
"""

import json
from typing import Sequence, Union

from alembic import op


revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 與 app/websocket/conversation_handler.py 的 OTHER_CHIEF_COMPLAINT_ID 同步（unit test 交叉驗證）
OTHER_COMPLAINT_ID = "00000000-0000-4000-8000-0000000000ff"

# 與 20260418_1900 seed 的 CATEGORY_I18N["other"] 完全一致（unit test 交叉驗證），
# 前端 CATEGORY_I18N_KEY 才會把 sentinel 歸入同一個「其他」section
CATEGORY_OTHER = {
    "zh-TW": "其他", "en-US": "Other", "ja-JP": "その他",
    "ko-KR": "기타", "vi-VN": "Khác",
}

OTHER_COMPLAINT = {
    "id": OTHER_COMPLAINT_ID,
    "display_order": 99,   # 遠大於既有 1-10，病患端固定排最後
    "is_default": True,
    "name": {
        "zh-TW": "其他", "en-US": "Other", "ja-JP": "その他",
        "ko-KR": "기타", "vi-VN": "Khác",
    },
    "description": {
        "zh-TW": "以上皆不符合，請用自己的話描述症狀",
        "en-US": "None of the above — describe your symptoms in your own words",
        "ja-JP": "上記に当てはまらない場合は、ご自身の言葉で症状をご説明ください",
        "ko-KR": "해당 사항이 없으면 직접 증상을 설명해 주세요",
        "vi-VN": "Không có mục nào phù hợp — hãy mô tả triệu chứng bằng lời của quý vị",
    },
}


def _sql_literal(text_value: str) -> str:
    """用 PostgreSQL 單引號 literal；內層單引號以雙引號逃逸。"""
    return "'" + text_value.replace("'", "''") + "'"


def _jsonb_literal(payload: dict) -> str:
    """把 dict 序列化成 PostgreSQL JSONB literal（'{...}'::jsonb）。
    使用 ensure_ascii=False 保留 Unicode，再轉成 SQL literal。
    """
    return _sql_literal(json.dumps(payload, ensure_ascii=False)) + "::jsonb"


def upgrade() -> None:
    # 以 id 做 UPSERT，保持真正 idempotent：sentinel 一旦被
    # sessions.chief_complaint_id 引用（NOT NULL FK、無 cascade），
    # DELETE-then-INSERT 重跑會直接撞 FK violation；改用
    # INSERT ... ON CONFLICT (id) DO UPDATE 則無論 row 是否已存在、
    # 是否已被引用都能安全重跑，且對「尚未跑過」的環境結果不變。
    sid = _sql_literal(OTHER_COMPLAINT_ID)
    values = ", ".join(
        [
            sid,
            # legacy 欄位維持 zh-TW 以支援 pre-i18n 讀取路徑
            _sql_literal(OTHER_COMPLAINT["name"]["zh-TW"]),
            _sql_literal(OTHER_COMPLAINT["name"]["en-US"]),
            _sql_literal(OTHER_COMPLAINT["description"]["zh-TW"]),
            _sql_literal(CATEGORY_OTHER["zh-TW"]),
            # 權威多語 JSONB
            _jsonb_literal(OTHER_COMPLAINT["name"]),
            _jsonb_literal(OTHER_COMPLAINT["description"]),
            _jsonb_literal(CATEGORY_OTHER),
            "true" if OTHER_COMPLAINT["is_default"] else "false",
            "true",
            str(OTHER_COMPLAINT["display_order"]),
        ]
    )
    op.execute(
        f"""
        INSERT INTO chief_complaints (
            id, name, name_en, description, category,
            name_by_lang, description_by_lang, category_by_lang,
            is_default, is_active, display_order
        ) VALUES ({values})
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            name_en = EXCLUDED.name_en,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            name_by_lang = EXCLUDED.name_by_lang,
            description_by_lang = EXCLUDED.description_by_lang,
            category_by_lang = EXCLUDED.category_by_lang,
            is_default = EXCLUDED.is_default,
            is_active = EXCLUDED.is_active,
            display_order = EXCLUDED.display_order,
            updated_at = now()
        """
    )


def downgrade() -> None:
    sid = _sql_literal(OTHER_COMPLAINT_ID)
    # 先停用（病患端立即看不到），再嘗試真刪；已被 sessions FK 引用時
    # DELETE 的 NOT EXISTS 條件不成立 → 保留停用狀態，避免 downgrade 炸 FK
    op.execute(f"UPDATE chief_complaints SET is_active = false WHERE id = {sid}")
    op.execute(
        f"""
        DELETE FROM chief_complaints
        WHERE id = {sid} AND NOT EXISTS (
            SELECT 1 FROM sessions WHERE sessions.chief_complaint_id = chief_complaints.id
        )
        """
    )
