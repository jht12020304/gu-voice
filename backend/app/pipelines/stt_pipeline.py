"""
語音轉文字管線 — OpenAI Whisper API

接收完整音訊位元組（webm/opus 格式），呼叫 Whisper-1 轉錄，
回傳繁體中文辨識結果。
"""

import io
import logging
import math
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


# ── 幻覺過濾 ────────────────────────────────────────────────
# Whisper 在「靜音 / 極短（句首被吃掉的 2-3 字回答）/ 雜訊」音訊上，會吐出訓練語料
# （大量 YouTube 字幕）裡的高頻句子，與病患實際所說完全無關。最典型的是中文「謝謝觀看」、
# 英文「Thank you for watching」。問診情境下病患不可能對 AI 說這些。
# 整段轉錄正規化後若「只等於」下列任一片語 → 判定為幻覺、回空字串，讓上游當成「沒聽清楚」
# （AI 會自然再問一次），而不是拿幻覺去跑紅旗篩檢 / LLM（病患回報「沒錯」變「謝謝觀看」）。
_HALLUCINATION_PHRASES: frozenset[str] = frozenset(
    {
        # ── 中文（最常見，正規化會去空白/標點，故收無空白版本）──
        "謝謝觀看", "謝謝大家觀看", "謝謝大家", "謝謝您的觀看", "謝謝你的觀看",
        "謝謝收看", "感謝觀看", "感謝收看", "感謝您的觀看", "感謝您的收看",
        "請訂閱", "請按贊訂閱", "記得訂閱", "訂閱我的頻道", "請訂閱我的頻道",
        "請不吝點贊訂閱轉發打賞支持明鏡與點點欄目", "明鏡需要您的支持", "點點欄目",
        "下次再見", "我們下次再見", "我們下集再見", "謝謝大家的收看我們下次再見",
        "字幕由amaraorg社群提供", "字幕志工", "中文字幕由志願者提供",
        # ── 英文 ──
        "thank you for watching", "thanks for watching",
        "thank you for watching this video", "please subscribe",
        "please subscribe to my channel", "subscribe to my channel",
        "see you next time", "see you in the next video",
        # ── 日文 ──
        "ご視聴ありがとうございました", "ご視聴ありがとうございます",
        "チャンネル登録お願いします",
        # ── 韓文 ──
        "시청해주셔서감사합니다", "구독과좋아요부탁드립니다",
    }
)

_PUNCT_STRIP = "。，！？、；：…~～「」『』（）()\"'《》【】 \t\n　.!?,;:"


def _normalize_for_match(text: str) -> str:
    """正規化轉錄文字以比對幻覺片語：去頭尾標點/空白、英文轉小寫、移除所有內部空白。

    英文片語以「無空白」形式比對（"Thank you for watching." → "thankyouforwatching"），
    與下方預先正規化的 _HALLUCINATION_NORMALIZED 對齊。
    """
    t = text.strip().strip(_PUNCT_STRIP).lower()
    return "".join(t.split())


_HALLUCINATION_NORMALIZED: frozenset[str] = frozenset(
    _normalize_for_match(p) for p in _HALLUCINATION_PHRASES
)

# 靜音兜底門檻（取 openai-whisper 預設）：整體 no_speech 機率高且 avg_logprob 很低時，
# 視為「根本沒人說話」。兩條件都要滿足才丟，避免誤殺真實的小聲/簡短回答。
_NO_SPEECH_PROB_THRESHOLD = 0.6
_AVG_LOGPROB_THRESHOLD = -1.0


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
        # #3：STT 專用逾時（長語音轉錄 >60s 預設 client 逾時 → 不該誤判重試）
        self._timeout = getattr(settings, "OPENAI_STT_TIMEOUT_SECONDS", 120.0)

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
                "text":       str,          # 辨識文字
                "confidence": float | None, # 由 verbose_json segments 的 avg_logprob
                                            # 估算（幾何平均 token 機率，0~1）；
                                            # segments 缺失時為 None（未知，非 1.0）
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
            # #3：用 with_options 覆寫成 STT 專用較長逾時（預設 client 為 60s，長語音會誤逾時重試）。
            stt_client = self._client.with_options(timeout=self._timeout)
            with observe_stt_latency(lang):
                response = await call_with_retry(
                    lambda: stt_client.audio.transcriptions.create(
                        model=self._model,
                        file=_make_file(),
                        language=lang,
                        # verbose_json 多回 segments（含 no_speech_prob / avg_logprob），
                        # 供下方靜音兜底判定；text 取法不變。
                        response_format="verbose_json",
                    )
                )

            text = (getattr(response, "text", None) or "").strip()

            # ── 幻覺 / 靜音過濾（醫療安全：不要拿幻覺去跑紅旗篩檢 / LLM）──────
            # PHI：log 不輸出對話原文（含被丟棄的幻覺片段），只留長度供排查。
            if text and self._is_hallucination(text, response):
                logger.info(
                    "STT 判定為幻覺/靜音，丟棄該段 | lang=%s, dropped_chars=%d",
                    lang,
                    len(text),
                )
                return {"text": "", "confidence": 0.0, "is_final": True, "words": []}

            confidence = self._estimate_confidence(response)
            logger.info(
                "STT 轉錄完成 | lang=%s, chars=%d, confidence=%s",
                lang,
                len(text),
                f"{confidence:.4f}" if confidence is not None else "n/a",
            )

            return {
                "text": text,
                "confidence": confidence,
                "is_final": True,
                "words": [],
            }

        except Exception as exc:
            logger.error(
                "STT 轉錄失敗 | error=%s", str(exc), exc_info=True
            )
            raise

    @staticmethod
    def _is_hallucination(text: str, response: Any) -> bool:
        """判定一段轉錄是否為 Whisper 幻覺 / 靜音，應丟棄。

        兩條獨立路徑：
          1. 片語比對：整段正規化後「只等於」已知幻覺片語（謝謝觀看 / Thank you for
             watching …）。這是病患回報症狀（「沒錯」變「謝謝觀看」）的主要兜底。
          2. 靜音兜底：verbose_json segments 的整體 no_speech_prob 高且 avg_logprob 低
             （兩條件都成立才丟，避免誤殺真實的小聲/簡短回答）。segments 缺失時略過此路徑。
        """
        normalized = _normalize_for_match(text)
        if normalized and normalized in _HALLUCINATION_NORMALIZED:
            return True

        no_speech_probs, avg_logprobs = STTPipeline._segment_stats(response)

        if no_speech_probs and avg_logprobs:
            mean_nsp = sum(no_speech_probs) / len(no_speech_probs)
            mean_alp = sum(avg_logprobs) / len(avg_logprobs)
            if mean_nsp >= _NO_SPEECH_PROB_THRESHOLD and mean_alp < _AVG_LOGPROB_THRESHOLD:
                return True

        return False

    @staticmethod
    def _segment_stats(response: Any) -> tuple[list[float], list[float]]:
        """自 verbose_json segments 取出 (no_speech_probs, avg_logprobs)。

        segment 可能是 dict（raw JSON）或 SDK 物件，兩種取法都支援；
        缺欄 / 非數值一律略過，回傳兩個可能為空的 list。
        """
        segments = getattr(response, "segments", None) or []
        no_speech_probs: list[float] = []
        avg_logprobs: list[float] = []
        for seg in segments:
            nsp = (
                seg.get("no_speech_prob")
                if isinstance(seg, dict)
                else getattr(seg, "no_speech_prob", None)
            )
            alp = (
                seg.get("avg_logprob")
                if isinstance(seg, dict)
                else getattr(seg, "avg_logprob", None)
            )
            if isinstance(nsp, (int, float)):
                no_speech_probs.append(float(nsp))
            if isinstance(alp, (int, float)):
                avg_logprobs.append(float(alp))
        return no_speech_probs, avg_logprobs

    @staticmethod
    def _estimate_confidence(response: Any) -> float | None:
        """由 segments 的 avg_logprob 估算信心分數（0~1）。

        Whisper API 不直接回傳 confidence；業界慣用 proxy 是
        exp(mean(avg_logprob))＝幾何平均 token 機率：
        清晰語音約落在 0.7~0.95，Whisper 自身視 avg_logprob < -1.0
        （≈ exp ≈ 0.37）為解碼失敗門檻，故 0.5 以下可視為低信心。
        segments 缺失時回 None（未知），呼叫端應存 NULL 而非假裝滿分。
        小數點取 4 位以對齊 conversations.stt_confidence Numeric(5,4)。
        """
        _, avg_logprobs = STTPipeline._segment_stats(response)
        if not avg_logprobs:
            return None
        mean_alp = sum(avg_logprobs) / len(avg_logprobs)
        return round(max(0.0, min(1.0, math.exp(mean_alp))), 4)

    async def close(self) -> None:
        """OpenAI AsyncClient 無需明確關閉，保留介面一致性。"""
        logger.info("STTPipeline 關閉")
