"""
音訊生命週期清理（P3 #30）

產品規則：`conversations.audio_url` 上的音訊 blob 超過 `AUDIO_RETENTION_DAYS`
（預設 90 天）必須刪除，以符合隱私保留政策。

- 每月 1 日凌晨 05:00 跑 `cleanup_old_audio_files`（避開 partition 03:00 與
  audit_retention 04:00 的時段）
- 實際刪除動作會解析 `audio_url` 的 bucket / object path，呼叫 Supabase Storage
  `storage.from_(bucket).remove([path])` 真正刪除 blob。
- dry_run=True 時只盤點不動 DB / blob，方便手動預演。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import unquote, urlparse

from app.tasks import celery_app
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 音訊 blob 保留 90 天（產品預設）
AUDIO_RETENTION_DAYS = 90

# audio_service.upload_audio 存的是「不含 bucket 前綴」的裸 object path
# （`{session_id}/{conversation_id}.{format}`），blob 落在這個 bucket。
# 解析不到 Supabase URL 結構時，視為此 bucket 的裸 path。
_DEFAULT_AUDIO_BUCKET = "audio-recordings"

# Supabase Storage public / signed / authenticated URL 的 object 區段前綴：
#   https://<proj>.supabase.co/storage/v1/object/{sign|public|authenticated}/{bucket}/{path}
_STORAGE_OBJECT_MARKER = "/storage/v1/object/"
# object marker 後面緊接的「存取模式」segment，要先吃掉才輪到 bucket。
_STORAGE_ACCESS_SEGMENTS = frozenset({"sign", "public", "authenticated"})


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


def _parse_bucket_and_path(audio_url: str) -> tuple[str, str]:
    """
    從 `audio_url` 解析出 (bucket, object_path)。

    支援兩種 audio_url 寫法（對齊上傳端怎麼存）：
      1. Supabase Storage public / signed / authenticated URL，例如
         `https://<proj>.supabase.co/storage/v1/object/sign/<bucket>/<path>?token=...`
         → 吃掉 `/storage/v1/object/{sign|public|authenticated}/`，第一段是 bucket，
            其餘是 object path（query string 丟掉、percent-encoding 還原）。
      2. audio_service.upload_audio 存的裸 object path（不含 bucket 前綴），例如
         `{session_id}/{conversation_id}.wav`
         → bucket 視為 `_DEFAULT_AUDIO_BUCKET`，整串當 object path。

    解析不到合法 path 時 raise ValueError，交由呼叫端記成 error 並下次重試。
    """
    if not audio_url or not audio_url.strip():
        raise ValueError("audio_url 為空，無法解析 bucket / path")

    raw = audio_url.strip()
    marker_idx = raw.find(_STORAGE_OBJECT_MARKER)
    if marker_idx != -1:
        # 取 marker 之後、query/fragment 之前的部分
        tail = raw[marker_idx + len(_STORAGE_OBJECT_MARKER):]
        tail = tail.split("?", 1)[0].split("#", 1)[0]
        segments = [unquote(s) for s in tail.split("/") if s]
        # 吃掉存取模式 segment（sign / public / authenticated）才輪到 bucket
        if segments and segments[0] in _STORAGE_ACCESS_SEGMENTS:
            segments = segments[1:]
        if len(segments) < 2:
            raise ValueError(f"Supabase URL 缺少 bucket/path：{audio_url}")
        bucket = segments[0]
        path = "/".join(segments[1:])
        if not bucket or not path:
            raise ValueError(f"Supabase URL bucket/path 解析為空：{audio_url}")
        return bucket, path

    # 裸 path（無 Supabase URL 結構）→ 預設 bucket
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        # 是 URL 但不是預期的 Supabase Storage 結構 → 拒絕，避免亂刪
        raise ValueError(f"無法識別的音訊 URL 結構：{audio_url}")
    path = unquote(raw.lstrip("/"))
    if not path:
        raise ValueError(f"音訊 path 解析為空：{audio_url}")
    return _DEFAULT_AUDIO_BUCKET, path


def _get_supabase_client():
    """
    建立 Supabase client，沿用 tts_pipeline 的 SERVICE_ROLE_KEY 寫法。

    沒設 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 時 raise，讓該筆記成 error
    且不清空 DB 欄位，下個週期重試（而非靜默把音訊留著）。
    """
    from supabase import create_client

    from app.core.config import settings

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Supabase 未設定（缺 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY），無法刪除音訊 blob"
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


async def _delete_audio_blob(audio_url: str) -> None:
    """
    實際刪除 Supabase Storage 上的音訊 blob。

    解析 bucket / object path 後呼叫 `storage.from_(bucket).remove([path])`。
    刪除失敗（raise）時，呼叫端不會清空 DB 欄位，下個週期會重試 → 不會把音訊
    遺留下來。supabase-py 是同步 client，丟到 thread executor 跑避免卡住 event loop。
    """
    import asyncio

    bucket, path = _parse_bucket_and_path(audio_url)

    client = _get_supabase_client()

    def _remove() -> None:
        client.storage.from_(bucket).remove([path])

    try:
        await asyncio.to_thread(_remove)
    except Exception:
        logger.error(
            "Supabase blob remove 失敗 | bucket=%s path=%s url=%s",
            bucket, path, audio_url,
        )
        raise

    logger.info(
        "音訊 blob 已刪除 | bucket=%s path=%s",
        bucket, path,
    )
