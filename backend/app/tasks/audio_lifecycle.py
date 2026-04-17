"""
音訊生命週期清理（P3 #30）

產品規則：`conversations.audio_url` 上的音訊 blob 超過 `AUDIO_RETENTION_DAYS`
（預設 90 天）必須刪除，以符合隱私保留政策。

- 每月 1 日凌晨 05:00 跑 `cleanup_old_audio_files`（避開 partition 03:00 與
  audit_retention 04:00 的時段）
- 實際刪除動作目前只 log；Supabase Storage 整合尚未拉好，留 TODO。
- dry_run=True 時只盤點不動 DB / blob，方便手動預演。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from app.tasks import celery_app
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 音訊 blob 保留 90 天（產品預設）
AUDIO_RETENTION_DAYS = 90


@celery_app.task(
    name="app.tasks.audio_lifecycle.cleanup_old_audio_files",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    acks_late=True,
)
def cleanup_old_audio_files(self, dry_run: bool = False) -> dict[str, Any]:
    """
    掃 `conversations`，刪除超過 `AUDIO_RETENTION_DAYS` 的音訊 blob。

    Args:
        dry_run: True 時只盤點，不動 DB 也不刪 blob。
    """
    import asyncio

    try:
        return asyncio.get_event_loop().run_until_complete(_async_cleanup(dry_run))
    except Exception:
        return asyncio.run(_async_cleanup(dry_run))


async def _async_cleanup(dry_run: bool = False) -> dict[str, Any]:
    """核心邏輯，抽出來讓 unit test 直接打。"""
    from sqlalchemy import text

    from app.core.database import async_session_factory

    cutoff_dt = utc_now() - timedelta(days=AUDIO_RETENTION_DAYS)
    logger.info(
        "audio lifecycle cleanup started | cutoff=%s dry_run=%s",
        cutoff_dt.isoformat(), dry_run,
    )

    scanned = 0
    would_delete: list[str] = []
    deleted: list[str] = []
    errors: list[dict[str, str]] = []

    async with async_session_factory() as db:
        # 只撈還掛著 audio_url 的舊資料；id 一併回來方便後續清空欄位
        result = await db.execute(
            text(
                """
                SELECT id, audio_url
                FROM conversations
                WHERE created_at < :cutoff
                  AND audio_url IS NOT NULL
                """
            ),
            {"cutoff": cutoff_dt},
        )
        rows = result.fetchall()
        scanned = len(rows)

        for row in rows:
            conversation_id, audio_url = row[0], row[1]
            would_delete.append(audio_url)
            if dry_run:
                logger.info(
                    "[dry-run] would delete audio | conversation=%s url=%s",
                    conversation_id, audio_url,
                )
                continue

            try:
                await _delete_audio_blob(audio_url)
                # 刪成功再把 DB 欄位清空，避免 blob 已刪但 DB 仍指向舊 URL
                await db.execute(
                    text(
                        "UPDATE conversations SET audio_url = NULL "
                        "WHERE id = :id"
                    ),
                    {"id": conversation_id},
                )
                deleted.append(audio_url)
            except Exception as exc:  # noqa: BLE001 — 單筆失敗不阻斷其他
                logger.exception(
                    "audio blob delete failed | conversation=%s url=%s",
                    conversation_id, audio_url,
                )
                errors.append(
                    {"conversation_id": str(conversation_id), "url": audio_url, "error": str(exc)}
                )

        if not dry_run:
            await db.commit()

    summary = {
        "scanned": scanned,
        "would_delete": len(would_delete),
        "deleted": len(deleted),
        "errors": errors,
        "dry_run": dry_run,
        "retention_days": AUDIO_RETENTION_DAYS,
    }
    logger.info(
        "audio lifecycle cleanup done | scanned=%d would_delete=%d deleted=%d errors=%d dry_run=%s",
        scanned, len(would_delete), len(deleted), len(errors), dry_run,
    )
    return summary


async def _delete_audio_blob(audio_url: str) -> None:
    """
    實際刪除 blob 的 helper。

    TODO: 整合 Supabase Storage client，解析 bucket/object path 後呼叫
          `storage.from_(bucket).remove([path])`。目前先 log 出來，
          讓工作流程其他部分先上線。
    """
    parsed = urlparse(audio_url)
    logger.info(
        "[audio-delete TODO] host=%s path=%s (Supabase Storage 整合待接)",
        parsed.netloc, parsed.path,
    )
