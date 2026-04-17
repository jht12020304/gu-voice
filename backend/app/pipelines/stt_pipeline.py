"""
語音轉文字管線 — OpenAI Whisper API

接收完整音訊位元組（webm/opus 格式），呼叫 Whisper-1 轉錄，
回傳繁體中文辨識結果。
"""

import io
import logging
from typing import Any

from app.core.config import Settings
from app.core.openai_client import call_with_retry, get_openai_client

logger = logging.getLogger(__name__)


class STTPipeline:
    """
    OpenAI Whisper 語音辨識管線

    呼叫 Whisper-1 模型進行中文語音轉文字，
    支援 webm/opus 格式（MediaRecorder 預設輸出）。
    """

    def __init__(self, settings: Settings) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_STT_MODEL        # "whisper-1"
        self._language = settings.OPENAI_STT_LANGUAGE  # "zh"

        logger.info(
            "STTPipeline 初始化 (OpenAI Whisper) | model=%s, language=%s",
            self._model,
            self._language,
        )

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str | None = None,
    ) -> dict[str, Any]:
        """
        轉錄完整音訊。

        Args:
            audio_bytes: 完整音訊資料（webm/opus）
            language:    語言代碼，None 時使用設定值（zh）

        Returns:
            {
                "text":       str,    # 辨識文字
                "confidence": float,  # 固定 1.0（Whisper 未提供分數）
                "is_final":   True,
                "words":      [],
            }
        """
        if not audio_bytes:
            return {"text": "", "confidence": 0.0, "is_final": True, "words": []}

        lang = language or self._language

        def _make_file() -> io.BytesIO:
            """每次重試時重建 BytesIO；原 stream 可能已被消耗。"""
            f = io.BytesIO(audio_bytes)
            f.name = "audio.webm"
            return f

        try:
            response = await call_with_retry(
                lambda: self._client.audio.transcriptions.create(
                    model=self._model,
                    file=_make_file(),
                    language=lang,
                    response_format="json",
                )
            )

            text = (response.text or "").strip()

            logger.info(
                "STT 轉錄完成 | lang=%s, chars=%d, preview=%s",
                lang,
                len(text),
                text[:60] if text else "(空)",
            )

            return {
                "text": text,
                "confidence": 1.0,
                "is_final": True,
                "words": [],
            }

        except Exception as exc:
            logger.error(
                "STT 轉錄失敗 | error=%s", str(exc), exc_info=True
            )
            raise

    async def close(self) -> None:
        """OpenAI AsyncClient 無需明確關閉，保留介面一致性。"""
        logger.info("STTPipeline 關閉")
