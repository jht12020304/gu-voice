"""
語音轉文字管線 — OpenAI Whisper API

接收完整音訊位元組（webm/opus 格式），呼叫 Whisper-1 轉錄，
回傳繁體中文辨識結果。
"""

import io
import logging
from typing import Any

from app.core.config import Settings
from app.core.metrics import observe_stt_latency
from app.core.openai_client import call_with_retry, get_openai_client

logger = logging.getLogger(__name__)


# 明確列表保險：若 LANGUAGE_MAP 因任何原因缺項，這組 BCP-47 → ISO-639-1 仍可救援。
# Whisper 僅接受 ISO-639-1（"zh" / "en" / ...），傳 "zh-TW" 會 400。
_BCP47_TO_WHISPER: dict[str, str] = {
    "zh-TW": "zh",
    "en-US": "en",
    "ja-JP": "ja",
    "ko-KR": "ko",
    "vi-VN": "vi",
}


def to_whisper_language(bcp47: str | None) -> str | None:
    """
    把場次的 BCP-47 語言碼轉成 Whisper 認得的 ISO-639-1。

    None / 空字串 / 未知值 → 回 None，讓 Whisper 自動偵測或由 pipeline 預設填補。
    """
    if not bcp47:
        return None
    code = _BCP47_TO_WHISPER.get(bcp47)
    if code:
        return code
    # 無 region 時（"en"）直接當 ISO-639-1；有 region 取前段。
    return bcp47.split("-", 1)[0] if "-" in bcp47 else bcp47


def _detect_audio_filename(audio_bytes: bytes) -> str:
    """
    依 magic bytes 推斷 Whisper 可接受的副檔名。

    Whisper API 以副檔名辨別容器格式，因此 MP4/M4A 必須命名為 .m4a、
    WebM 須 .webm、WAV 須 .wav。若誤標會 400。前端 MIME 順序偏好
    audio/mp4（Chrome 113+/Safari 上會採用），所以 backend 必須認得 MP4。
    """
    if not audio_bytes or len(audio_bytes) < 4:
        return "audio.webm"
    head = audio_bytes[:16]
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio.webm"
    if head.startswith(b"OggS"):
        return "audio.ogg"
    if head.startswith(b"RIFF"):
        return "audio.wav"
    if head.startswith(b"ID3") or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "audio.mp3"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "audio.m4a"
    return "audio.webm"


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

        filename = _detect_audio_filename(audio_bytes)

        def _make_file() -> io.BytesIO:
            """每次重試時重建 BytesIO；原 stream 可能已被消耗。"""
            f = io.BytesIO(audio_bytes)
            f.name = filename
            return f

        try:
            with observe_stt_latency(lang):
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
