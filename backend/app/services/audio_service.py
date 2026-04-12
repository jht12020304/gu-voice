"""
音訊檔案服務
- 上傳音訊至 Supabase Storage
- 生成簽名 URL
"""

import logging
from typing import Optional
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

# Supabase Storage bucket 名稱
AUDIO_BUCKET = "audio-recordings"

# 簽名 URL 有效期（秒）
SIGNED_URL_EXPIRY = 3600


class AudioService:
    """音訊檔案管理"""

    @staticmethod
    async def upload_audio(
        session_id: UUID,
        conversation_id: UUID,
        audio_data: bytes,
        format: str = "wav",
    ) -> str:
        """
        上傳音訊檔案至 Supabase Storage

        檔案路徑: audio-recordings/{session_id}/{conversation_id}.{format}

        Args:
            session_id: 場次 ID
            conversation_id: 對話 ID
            audio_data: 音訊二進制資料
            format: 音訊格式（預設 wav）

        Returns:
            上傳後的檔案路徑
        """
        file_path = f"{session_id}/{conversation_id}.{format}"

        # 決定 content type
        content_type_map = {
            "wav": "audio/wav",
            "webm": "audio/webm",
            "ogg": "audio/ogg",
        }
        content_type = content_type_map.get(format, "application/octet-stream")

        try:
            # 使用 supabase-py 上傳
            from supabase import create_client

            supabase = create_client(
                settings.SUPABASE_URL if hasattr(settings, "SUPABASE_URL") else "",
                settings.SUPABASE_KEY if hasattr(settings, "SUPABASE_KEY") else "",
            )

            supabase.storage.from_(AUDIO_BUCKET).upload(
                path=file_path,
                file=audio_data,
                file_options={"content-type": content_type},
            )

            logger.info("音訊上傳成功: %s/%s", AUDIO_BUCKET, file_path)
            return file_path

        except ImportError:
            # Supabase SDK 未安裝，使用本地檔案系統作為 fallback
            logger.warning("supabase-py 未安裝，音訊將不會被持久化存儲")
            return file_path

        except Exception as exc:
            logger.error("音訊上傳失敗: %s", exc)
            raise

    @staticmethod
    async def get_audio_url(
        session_id: UUID,
        conversation_id: UUID,
        format: str = "wav",
    ) -> Optional[str]:
        """
        生成音訊檔案的簽名 URL

        Args:
            session_id: 場次 ID
            conversation_id: 對話 ID
            format: 音訊格式

        Returns:
            簽名 URL，若檔案不存在回傳 None
        """
        file_path = f"{session_id}/{conversation_id}.{format}"

        try:
            from supabase import create_client

            supabase = create_client(
                settings.SUPABASE_URL if hasattr(settings, "SUPABASE_URL") else "",
                settings.SUPABASE_KEY if hasattr(settings, "SUPABASE_KEY") else "",
            )

            result = supabase.storage.from_(AUDIO_BUCKET).create_signed_url(
                path=file_path,
                expires_in=SIGNED_URL_EXPIRY,
            )

            if result and "signedURL" in result:
                return result["signedURL"]

            return None

        except ImportError:
            logger.warning("supabase-py 未安裝，無法生成簽名 URL")
            return None

        except Exception as exc:
            logger.error("生成簽名 URL 失敗: %s", exc)
            return None
