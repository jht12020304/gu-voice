"""rescue: reactivate chief_complaints that 20260418_2300 accidentally deactivated

20260418_2300 原本意圖對「與 seed 同 zh-TW name 但不在 seed UUID 白名單」
的舊重覆記錄做軟停用，但線上部署後整個主訴列表變空 —— 疑似
`id NOT IN ('00000000-...-c1', ...)` 在 PostgreSQL `uuid` 欄位上沒有套用預期
的隱式 cast，導致「非 seed」的篩選失效、10 筆 seed 也被一起 `is_active=false`。

為快速恢復可用性：
  1. 無條件把 10 筆 seed UUID 的記錄 `is_active=true`（包括 `updated_at=NOW()`）。
  2. 把本來應該被 backfill 的 3 筆 legacy 記錄（排尿困難 / 夜尿 / 尿道灼熱感）
     也重新 activate，確保 UI 能看到它們。
  3. 原「軟停用 legacy 重覆」的效果先擱置 —— 寧可讓舊中文卡片暫時又出現，
     也不要整個列表空白；等我們在 DB 直接確認後再補寫精準版本。

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-18 23:30:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 20260418_1900 seed 寫入的固定 UUID
SEED_UUIDS: list[str] = [
    "00000000-0000-4000-8000-0000000000c1",
    "00000000-0000-4000-8000-0000000000c2",
    "00000000-0000-4000-8000-0000000000c3",
    "00000000-0000-4000-8000-0000000000c4",
    "00000000-0000-4000-8000-0000000000c5",
    "00000000-0000-4000-8000-0000000000c6",
    "00000000-0000-4000-8000-0000000000c7",
    "00000000-0000-4000-8000-0000000000c8",
    "00000000-0000-4000-8000-0000000000c9",
    "00000000-0000-4000-8000-00000000000a",
]

# 被 backfill 的 legacy 泌尿主訴（20260418_2300 補譯過的）
LEGACY_BACKFILLED_NAMES: list[str] = [
    "排尿困難",
    "夜尿",
    "尿道灼熱感",
]


def upgrade() -> None:
    # 1) 逐筆 UPDATE seed UUID —— 用明確 ::uuid cast 確保 PG 不做任何隱式轉換
    for sid in SEED_UUIDS:
        op.execute(
            f"""
            UPDATE chief_complaints
            SET is_active = true,
                updated_at = NOW()
            WHERE id = '{sid}'::uuid
            """
        )

    # 2) 若 backfill 的 3 筆 legacy 被誤停，也重新 activate
    #    （它們不在 20260418_2300 的 DUPLICATE_ZHTW_NAMES，理論上不該被停，
    #      但若前次 NOT IN 真的失效，保險一起處理。）
    name_list = ", ".join("'" + n.replace("'", "''") + "'" for n in LEGACY_BACKFILLED_NAMES)
    op.execute(
        f"""
        UPDATE chief_complaints
        SET is_active = true,
            updated_at = NOW()
        WHERE name IN ({name_list})
          AND is_active = false
        """
    )


def downgrade() -> None:
    # 本 migration 單純反轉誤停用；downgrade 不做任何事，避免再把資料弄亂
    # （真正要 rollback 20260418_2300 請走它自己的 downgrade）。
    pass
