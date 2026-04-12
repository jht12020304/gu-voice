"""
文字轉語音管線 — Google Cloud Text-to-Speech

將 AI 回應文字轉換為自然語音，支援上傳至 Supabase Storage
並產生簽章 URL 供前端播放。
"""

import logging
import uuid as uuid_lib
from typing import Any

from google.cloud import texttospeech_v1 as tts
from supabase import create_client, Client as SupabaseClient

from app.core.config import Settings

logger = logging.getLogger(__name__)

# ── Supabase Storage 設定 ────────────────────────────────
_STORAGE_BUCKET = "tts-audio"
_SIGNED_URL_EXPIRE_SECONDS = 3600  # 1 小時


class TTSPipeline:
    """
    Google Cloud Text-to-Speech 管線

    使用 Wavenet 語音模型合成自然的繁體中文語音，
    並可選擇性地上傳至 Supabase Storage 供前端串流播放。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 Google Cloud TTS 客戶端與 Supabase 客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        try:
            self._tts_client = tts.TextToSpeechAsyncClient()
        except Exception as e:
            logger.warning("無法初始化 Google Cloud TTS，將禁用語音功能: %s", str(e))
            self._tts_client = None

        # 語音設定
        self._voice_name = settings.GOOGLE_TTS_VOICE_NAME  # cmn-TW-Wavenet-A
        self._speaking_rate = settings.GOOGLE_TTS_SPEAKING_RATE  # 0.9
        self._sample_rate = settings.GOOGLE_TTS_SAMPLE_RATE  # 24000

        # Supabase 客戶端（用於上傳音訊檔案）
        self._supabase: SupabaseClient | None = None
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            self._supabase = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY,
            )

        logger.info(
            "TTSPipeline 初始化 | voice=%s, rate=%.1f, sample_rate=%d, supabase=%s",
            self._voice_name,
            self._speaking_rate,
            self._sample_rate,
            "connected" if self._supabase else "disabled",
        )

    async def synthesize(self, text: str) -> bytes:
        """
        將文字合成為語音音訊

        Args:
            text: 要合成語音的文字（繁體中文）

        Returns:
            LINEAR16 格式的音訊位元組資料

        Raises:
            Exception: Google Cloud TTS API 呼叫失敗時
        """
        if not text or not text.strip():
            logger.warning("收到空白文字，跳過 TTS 合成")
            return b""

        try:
            # 合成輸入
            synthesis_input = tts.SynthesisInput(text=text)

            # 語音參數
            voice_params = tts.VoiceSelectionParams(
                language_code="cmn-TW",
                name=self._voice_name,
            )

            # 音訊設定
            audio_config = tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16,
                sample_rate_hertz=self._sample_rate,
                speaking_rate=self._speaking_rate,
            )

            # 呼叫 TTS API
            response = await self._tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )

            audio_bytes = response.audio_content
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
        self, text: str, session_id: str, message_id: str
    ) -> str:
        """
        合成語音後上傳至 Supabase Storage，回傳簽章 URL

        Args:
            text: 要合成語音的文字
            session_id: 問診場次 ID
            message_id: 訊息 ID（用於檔案命名）

        Returns:
            可用於播放的簽章 URL

        Raises:
            RuntimeError: Supabase 未設定時
            Exception: 合成或上傳失敗時
        """
        if self._supabase is None:
            raise RuntimeError(
                "Supabase 客戶端未設定，無法上傳音訊。"
                "請確認 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY 環境變數。"
            )

        # 合成音訊
        audio_bytes = await self.synthesize(text)
        if not audio_bytes:
            logger.warning("音訊為空，無法上傳 | session=%s", session_id)
            return ""

        # 檔案路徑：sessions/{session_id}/{message_id}.wav
        file_path = f"sessions/{session_id}/{message_id}.wav"

        try:
            # 上傳至 Supabase Storage
            self._supabase.storage.from_(_STORAGE_BUCKET).upload(
                path=file_path,
                file=audio_bytes,
                file_options={
                    "content-type": "audio/wav",
                    "upsert": "true",
                },
            )

            # 產生簽章 URL
            signed_url_response = self._supabase.storage.from_(
                _STORAGE_BUCKET
            ).create_signed_url(
                path=file_path,
                expires_in=_SIGNED_URL_EXPIRE_SECONDS,
            )

            signed_url = signed_url_response.get("signedURL", "")

            logger.info(
                "TTS 音訊已上傳至 Supabase | session=%s, message=%s, path=%s",
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
        """關閉客戶端連線，釋放資源"""
        transport = self._tts_client.transport
        if hasattr(transport, "close"):
            await transport.close()
        logger.info("TTSPipeline 客戶端已關閉")
