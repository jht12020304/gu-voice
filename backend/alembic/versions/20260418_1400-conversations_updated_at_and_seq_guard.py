"""conversations_updated_at_and_seq_guard

P2 #13：為分區表 conversations 補兩件事：
1. `updated_at` 欄位 + 自動更新 trigger（UPDATE 時觸發）
2. 跨分區 `(session_id, sequence_number)` 唯一性 BEFORE INSERT trigger

為什麼要 trigger 而不是 `UNIQUE(session_id, sequence_number)`：
- PostgreSQL 分區表的 UNIQUE 必須包含所有分區鍵；本表以 `created_at` 分區，
  所以只能做到 `UNIQUE(session_id, sequence_number, created_at)`（已由
  20260417_0910-partitioned_tables.py 建立）。
- 這只防同秒 duplicate row，不防「相同 session 跨月累積出兩個 seq=N」。
- ConversationService.create 是 `MAX(seq)+1` 模式，兩個併發 WS 訊息理論上會重號。
- 因此 app 端加 `pg_advisory_xact_lock(hashtext(session_id))` 序列化，trigger 是兜底。

資料清理：
- 此 migration 不強制清除既有 dupes（部署規範：DB 可重置，conversations 目前僅開發資料）。
- Migration 會先 RAISE NOTICE 回報若偵測到 dupes，方便手動決定是否重置。

Revision ID: b2c3d4e5f6a7
Revises: a7b8c9d0e1f2
Create Date: 2026-04-18 14:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. 先偵測既有 dupes（不 fail migration；只 RAISE NOTICE 讓人類決策） ──
    op.execute(
        """
        DO $$
        DECLARE
            dup_count BIGINT;
        BEGIN
            SELECT COUNT(*) INTO dup_count FROM (
                SELECT session_id, sequence_number
                FROM conversations
                GROUP BY session_id, sequence_number
                HAVING COUNT(*) > 1
            ) d;
            IF dup_count > 0 THEN
                RAISE NOTICE
                    '⚠ conversations 偵測到 % 組重複 (session_id, sequence_number)；'
                    'trigger 將阻擋未來插入，但既有資料未動。若需清理請手動處理。',
                    dup_count;
            END IF;
        END
        $$;
        """
    )

    # ── 2. 加 updated_at 欄位（分區 parent 加欄位會 propagate 到所有子分區） ──
    op.execute(
        """
        ALTER TABLE conversations
        ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        """
    )

    # ── 3. updated_at 自動維護 trigger ───────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION conversations_set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER conversations_set_updated_at_trg
        BEFORE UPDATE ON conversations
        FOR EACH ROW
        EXECUTE FUNCTION conversations_set_updated_at();
        """
    )

    # ── 4. 跨分區 (session_id, sequence_number) 唯一性 trigger ──────────────
    # 在 BEFORE INSERT 階段 SELECT EXISTS；命中就 raise unique_violation，
    # 讓 SQLAlchemy 拋 IntegrityError 給上層處理。
    # NOTE: 分區 parent 上的 row-level trigger 會自動傳遞到每個分區。
    op.execute(
        """
        CREATE OR REPLACE FUNCTION conversations_check_seq_unique()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM conversations
                WHERE session_id = NEW.session_id
                  AND sequence_number = NEW.sequence_number
            ) THEN
                RAISE EXCEPTION
                    'duplicate sequence_number % for session %',
                    NEW.sequence_number, NEW.session_id
                USING ERRCODE = 'unique_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER conversations_check_seq_unique_trg
        BEFORE INSERT ON conversations
        FOR EACH ROW
        EXECUTE FUNCTION conversations_check_seq_unique();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS conversations_check_seq_unique_trg ON conversations")
    op.execute("DROP FUNCTION IF EXISTS conversations_check_seq_unique()")
    op.execute("DROP TRIGGER IF EXISTS conversations_set_updated_at_trg ON conversations")
    op.execute("DROP FUNCTION IF EXISTS conversations_set_updated_at()")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS updated_at")
