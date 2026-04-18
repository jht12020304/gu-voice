"""
文字轉語音管線 — OpenAI TTS API

將 AI 回應文字合成為 MP3 語音，支援上傳至 Supabase Storage
並產生簽章 URL 供前端播放。
"""

import logging
from typing import Any

from supabase import create_client, Client as SupabaseClient

from app.core.config import Settings
from app.core.metrics import observe_tts_latency
from app.core.openai_client import call_with_retry, get_openai_client

logger = logging.getLogger(__name__)

_STORAGE_BUCKET = "tts-audio"
_SIGNED_URL_EXPIRE_SECONDS = 3600  # 1 小時


class TTSPipeline:
    """
    OpenAI TTS 管線

    使用 tts-1 模型合成自然語音，輸出 MP3 格式，
    並可選擇性地上傳至 Supabase Storage 供前端串流播放。
    """

    def __init__(self, settings: Settings) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_TTS_MODEL   # "tts-1"
        self._voice = settings.OPENAI_TTS_VOICE   # "nova"（zh-TW / en-US 預設）
        self._speed = settings.OPENAI_TTS_SPEED   # 0.9
        # LANGUAGE_MAP 規劃 ja/ko/vi 用 shimmer；這裡保留引用，synthesize 時依場次語言覆寫。
        self._language_map = settings.LANGUAGE_MAP

        self._supabase: SupabaseClient | None = None
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            self._supabase = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY,
            )

        logger.info(
            "TTSPipeline 初始化 (OpenAI TTS) | model=%s, default_voice=%s, speed=%.1f, supabase=%s",
            self._model,
            self._voice,
            self._speed,
            "connected" if self._supabase else "disabled",
        )

    def _voice_for_language(self, language: str | None) -> str:
        """依 BCP-47 語言碼從 LANGUAGE_MAP 取 voice；未命中回 default voice。"""
        if not language:
            return self._voice
        info = self._language_map.get(language)
        if not info:
            return self._voice
        return info.get("tts_voice") or self._voice

    async def synthesize(self, text: str, language: str | None = None) -> bytes:
        """
        將文字合成為語音 MP3。

        Args:
            text: 要合成的文字
            language: 用於 metrics label 的 BCP-47 語言碼；None → 記為 "unknown"。
                     目前 OpenAI TTS 不需要語言提示（模型自動偵測），僅作觀測用。

        Returns:
            MP3 格式的音訊位元組
        """
        if not text or not text.strip():
            logger.warning("收到空白文字，跳過 TTS 合成")
            return b""

        voice = self._voice_for_language(language)

        try:
            with observe_tts_latency(language):
                response = await call_with_retry(
                    lambda: self._client.audio.speech.create(
                        model=self._model,
                        voice=voice,
                        input=text,
                        response_format="mp3",
                        speed=self._speed,
                    )
                )

            audio_bytes = response.content

            logger.info(
                "TTS 合成完成 | text_length=%d, audio_bytes=%d",
                len(text),
                len(audio_bytes),
            )

            return audio_bytes

        except Exception as exc:
            logger.error(
                "TTS 合成失敗 | text_length=%d, error=%s",
                len(text),
                str(exc),
                exc_info=True,
            )
            raise

    async def synthesize_to_url(
        self, text: str, session_id: str, message_id: str, language: str | None = None
    ) -> str:
        """
        合成語音後上傳至 Supabase Storage，回傳簽章 URL。

        Args:
            text:       要合成語音的文字
            session_id: 問診場次 ID
            message_id: 訊息 ID（用於檔案命名）

        Returns:
            可播放的簽章 URL，失敗時回傳空字串
        """
        if self._supabase is None:
            raise RuntimeError(
                "Supabase 客戶端未設定，無法上傳音訊。"
                "請確認 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY 環境變數。"
            )

        audio_bytes = await self.synthesize(text, language=language)
        if not audio_bytes:
            return ""

        # 存為 mp3
        file_path = f"sessions/{session_id}/{message_id}.mp3"

        try:
            self._supabase.storage.from_(_STORAGE_BUCKET).upload(
                path=file_path,
                file=audio_bytes,
                file_options={
                    "content-type": "audio/mpeg",
                    "upsert": "true",
                },
            )

            signed_url_response = self._supabase.storage.from_(
                _STORAGE_BUCKET
            ).create_signed_url(
                path=file_path,
                expires_in=_SIGNED_URL_EXPIRE_SECONDS,
            )

            signed_url = signed_url_response.get("signedURL", "")

            logger.info(
                "TTS 音訊已上傳 | session=%s, message=%s, path=%s",
                session_id,
                message_id,
                file_path,
            )

            return signed_url

        except Exception as exc:
            logger.error(
                "TTS 音訊上傳失敗 | session=%s, message=%s, error=%s",
                session_id,
                message_id,
                str(exc),
                exc_info=True,
            )
            raise

    async def close(self) -> None:
        """OpenAI AsyncClient 無需明確關閉，保留介面一致性。"""
        logger.info("TTSPipeline 關閉")
