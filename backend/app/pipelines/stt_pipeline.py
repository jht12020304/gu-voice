"""
語音轉文字管線 — OpenAI Transcriptions API

接收完整音訊位元組（webm/opus/m4a/wav），呼叫 OpenAI 轉錄，
回傳繁體中文辨識結果。

支援兩個模型世代（依 OPENAI_STT_MODEL 自動切換請求形狀）：
  - gpt-transcribe（2026-08-22 起的預設）：response_format=json ＋
    include[]=logprobs（經 extra_body；SDK 1.58.1 實測可用）。中文輸出一律
    簡體，zh 場次由 OpenCC s2tw 確定性轉台灣繁體。靜音/雜訊模型本身回空字串。
  - whisper-1（回退路徑）：response_format=verbose_json，靜音兜底靠
    segments 的 no_speech_prob / avg_logprob，路徑完整保留。
"""

import io
import logging
import math
from typing import Any

from opencc import OpenCC

from app.core.config import Settings
from app.core.metrics import observe_stt_latency
from app.core.openai_client import call_with_retry, get_openai_client
from app.pipelines.prompts.shared import sanitize_for_prompt

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


def _is_gpt_stt(model: str) -> bool:
    """gpt-transcribe 世代（json + include[]=logprobs）；否則走 whisper-1 verbose_json 路徑。"""
    return (model or "").startswith("gpt-")


# ── 簡→繁（台灣標準）確定性轉換 ─────────────────────────────
# gpt-transcribe 的中文輸出一律簡體（2026-08-22 實測：prompt 給滿繁體語境仍回簡體），
# 而本系統的病患畫面與 SOAP 讀者都是台灣醫病。s2tw 是逐字/異體字層級的確定性映射
# （刻意不用 s2twp 的詞彙改寫，避免動到病患原話的用詞）；已繁體的輸入轉換為恆等，
# 所以 whisper-1 回退路徑同樣安全。純英日韓越文字不含簡體漢字，轉換為 no-op，
# 但仍只對 zh 場次呼叫以省 CPU。
_S2TW = OpenCC("s2tw")


def to_taiwan_traditional(text: str, language: str | None) -> str:
    """zh 場次把（可能是簡體的）轉錄文字轉成台灣繁體；其他語言原樣返回。"""
    if not text or not (language or "").startswith("zh"):
        return text
    return _S2TW.convert(text)


# ── STT 醫療詞彙 keyword hints ──────────────────────────────
# gpt-transcribe 的 prompt 參數可偏置專有名詞辨識（2026-08-22 實測：hint 內含
# 「可邁丁」時，誤聽「可麦丁」被拉回「可迈丁」）。whisper-1 也收 prompt（效果較弱、
# 上限 224 token），兩個世代都傳。
#
# ⚠️ 偏置是雙面刃：hint 裡的詞在音訊模糊時可能被「聽出來」（誘發假陽性）。
# 因此 hint 只收「這位病患自己在表單寫過的詞」（主訴/用藥/過敏/病史/家族史）——
# 病患本來就很可能講到它們——外加極小的固定科別詞，**不放**通用症狀詞庫。
# 病患自由文字先過 sanitize_for_prompt（D-1 偽區段注入防線與 LLM prompt 同一套）。
_STT_HINT_MAX_CHARS = 180  # whisper-1 prompt 上限 224 token；CJK 約 1 字 1 token，留餘裕
_STT_FIXED_TERMS_ZH = "攝護腺、頻尿、血尿"
_STT_FIXED_TERMS_EN = "prostate, urinary frequency, hematuria"


def build_stt_keyword_hint(
    chief_complaint: str | None,
    patient_info: dict[str, Any],
    language: str | None,
) -> str:
    """組出本場次的 STT 詞彙提示（空字串＝不傳 prompt）。

    內容 = 主訴 + 病患表單的用藥/過敏/病史/家族史 + 少量固定科別詞。
    姓名刻意不放（問診中病患幾乎不會唸自己的名字，放了只是多送 PHI）。
    """
    terms: list[str] = []
    if (cc := sanitize_for_prompt(chief_complaint, max_chars=60)):
        terms.append(cc)
    for key in ("medications", "allergies", "medical_history", "family_history"):
        if (value := sanitize_for_prompt(patient_info.get(key), max_chars=60)):
            terms.append(value)

    is_zh = (language or "").startswith("zh")
    terms.append(_STT_FIXED_TERMS_ZH if is_zh else _STT_FIXED_TERMS_EN)

    joined = "、".join(terms) if is_zh else ", ".join(terms)
    if is_zh:
        hint = f"台灣泌尿科門診問診對話。可能提到：{joined}。"
    else:
        hint = f"Urology clinic intake conversation. May mention: {joined}."
    return hint[:_STT_HINT_MAX_CHARS]


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
        # 簡體原文與其 s2tw 轉換形（2026-08-22 雜訊實測 whisper-1 吐出簡體版；
        # zh 場次比對前已過 s2tw，社区→社區，但保留原形兜非 zh 場次與轉換前路徑）
        "字幕由amaraorg社区提供", "字幕由amaraorg社區提供",
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

def _normalize_for_match(text: str) -> str:
    """正規化轉錄文字以比對幻覺片語：轉小寫後**只保留字母數字**（CJK 屬 alnum）。

    移除所有空白與標點——含內部標點：whisper 實際輸出「字幕由Amara.org社群提供」
    帶內部句點，只剝頭尾會讓黑名單條目永遠比對不到（2026-08-22 發現的既有缺陷）。
    比對是與 _HALLUCINATION_NORMALIZED 的**全等**，兩側走同一函式，
    收窄字元集不會誤殺真實回答（片語仍需逐字相同）。
    """
    return "".join(ch for ch in text.lower() if ch.isalnum())


_HALLUCINATION_NORMALIZED: frozenset[str] = frozenset(
    _normalize_for_match(p) for p in _HALLUCINATION_PHRASES
)

# 靜音兜底門檻（取 openai-whisper 預設）：整體 no_speech 機率高且 avg_logprob 很低時，
# 視為「根本沒人說話」。兩條件都要滿足才丟，避免誤殺真實的小聲/簡短回答。
_NO_SPEECH_PROB_THRESHOLD = 0.6
_AVG_LOGPROB_THRESHOLD = -1.0

# 重複迴圈兜底（2026-08-22 實測）：169 秒的重複語句音檔讓 gpt-transcribe 進入
# 解碼重複迴圈，吐出 13,991 字（≈82 字/秒）。人類語速物理上限：中文 ~5 字/秒、
# 英文含空白 ~15 字/秒；25 字/秒已是任何語言的 2 倍以上，超過＝轉錄必為垃圾，
# 整段丟棄讓 AI 自然重問（與片語黑名單同一策略）。只對 ≥10 秒的音訊判定
# （短音訊的比率不穩定，且短音訊不會累積出有害的重複迴圈）。
_MAX_CHARS_PER_SECOND = 25.0
_MIN_DURATION_FOR_RATE_GUARD = 10.0


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
    OpenAI 語音辨識管線

    預設 gpt-transcribe（回退 whisper-1，請求形狀依模型自動切換），
    支援 webm/opus/m4a/wav 格式（MediaRecorder / iOS 錄音輸出）。
    """

    def __init__(self, settings: Settings) -> None:
        self._client = get_openai_client()
        self._model = settings.OPENAI_STT_MODEL        # "gpt-transcribe"（回退 "whisper-1"）
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
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        轉錄完整音訊。

        Args:
            audio_bytes: 完整音訊資料（webm/opus）
            language:    語言代碼，None 時使用設定值（zh）
            prompt:      本場次的醫療詞彙提示（build_stt_keyword_hint 產出）；
                         None / 空字串時不傳。

        Returns:
            {
                "text":       str,          # 辨識文字（zh 場次已轉台灣繁體）
                "confidence": float | None, # whisper-1：segments avg_logprob；
                                            # gpt-transcribe：token logprobs。
                                            # 皆為幾何平均 token 機率（0~1）；
                                            # 來源缺失時為 None（未知，非 1.0）
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

        # 依模型世代組請求：gpt-transcribe 不收 verbose_json（400），
        # 改用 json + include[]=logprobs（extra_body 傳遞，SDK 1.58.1 沒有
        # 型別化的 include 參數但 extra_body 實測可用）；whisper-1 維持
        # verbose_json segments（靜音兜底 + confidence 來源）。
        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "language": lang,
        }
        if prompt:
            request_kwargs["prompt"] = prompt[:_STT_HINT_MAX_CHARS]
        if _is_gpt_stt(self._model):
            request_kwargs["response_format"] = "json"
            request_kwargs["extra_body"] = {"include": ["logprobs"]}
        else:
            request_kwargs["response_format"] = "verbose_json"

        try:
            # #3：用 with_options 覆寫成 STT 專用較長逾時（預設 client 為 60s，長語音會誤逾時重試）。
            stt_client = self._client.with_options(timeout=self._timeout)
            with observe_stt_latency(lang):
                response = await call_with_retry(
                    lambda: stt_client.audio.transcriptions.create(
                        file=_make_file(),
                        **request_kwargs,
                    )
                )

            text = (getattr(response, "text", None) or "").strip()
            # 簡→繁（台灣）轉換要在幻覺片語比對**之前**：簡體幻覺
            # （字幕由Amara.org社区提供）轉換後才能命中黑名單的繁體條目。
            text = to_taiwan_traditional(text, lang)

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
        """判定一段轉錄是否為幻覺 / 靜音 / 重複迴圈，應丟棄。

        三條獨立路徑：
          1. 片語比對：整段正規化後「只等於」已知幻覺片語（謝謝觀看 / Thank you for
             watching …）。這是病患回報症狀（「沒錯」變「謝謝觀看」）的主要兜底。
          2. 語速護欄：字數/秒 > 25 ∧ 音訊 ≥ 10 秒＝解碼重複迴圈（gpt-transcribe
             對長重複音檔實測 82 字/秒），轉錄必為垃圾。
          3. 靜音兜底：verbose_json segments 的整體 no_speech_prob 高且 avg_logprob 低
             （兩條件都成立才丟，避免誤殺真實的小聲/簡短回答）。segments 缺失時
             略過此路徑（gpt-transcribe 靜音由模型本身回空字串）。
        """
        normalized = _normalize_for_match(text)
        if normalized and normalized in _HALLUCINATION_NORMALIZED:
            return True

        # 3. 語速護欄：字數/秒超過人類語速物理上限＝解碼重複迴圈（見常數註解）。
        duration = STTPipeline._audio_duration_seconds(response)
        if (
            duration is not None
            and duration >= _MIN_DURATION_FOR_RATE_GUARD
            and len(text) / duration > _MAX_CHARS_PER_SECOND
        ):
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
    def _audio_duration_seconds(response: Any) -> float | None:
        """自響應取音訊秒數（語速護欄用）。

        gpt-transcribe：usage.seconds（usage.type == "duration"）；
        whisper-1 verbose_json：頂層 duration。都缺回 None（護欄跳過）。
        """
        usage = getattr(response, "usage", None)
        if usage is not None:
            secs = (
                usage.get("seconds")
                if isinstance(usage, dict)
                else getattr(usage, "seconds", None)
            )
            if isinstance(secs, (int, float)) and secs > 0:
                return float(secs)
        dur = getattr(response, "duration", None)
        if isinstance(dur, (int, float)) and dur > 0:
            return float(dur)
        return None

    @staticmethod
    def _token_logprobs(response: Any) -> list[float]:
        """自 gpt-transcribe 的 include[]=logprobs 取出 token logprob 值。

        響應形狀：頂層 `logprobs` 為 [{token, logprob, bytes}, ...]；
        SDK 1.58.1 把未知欄位收進 model_extra，屬性存取可拿到（實測）。
        item 可能是 dict 或 SDK 物件，兩種都支援；缺欄 / 非數值略過。
        """
        items = getattr(response, "logprobs", None) or []
        values: list[float] = []
        for item in items:
            lp = (
                item.get("logprob")
                if isinstance(item, dict)
                else getattr(item, "logprob", None)
            )
            if isinstance(lp, (int, float)):
                values.append(float(lp))
        return values

    @staticmethod
    def _estimate_confidence(response: Any) -> float | None:
        """估算信心分數（0~1）＝幾何平均 token 機率 exp(mean(logprob))。

        來源依模型世代二擇一：
          - whisper-1：verbose_json segments 的 avg_logprob（segment 級平均）
          - gpt-transcribe：include[]=logprobs 的 token 級 logprob
        清晰語音約落在 0.7~0.95；whisper 自身視 avg_logprob < -1.0
        （≈ exp ≈ 0.37）為解碼失敗門檻，故 0.5 以下可視為低信心。
        兩個來源都缺時回 None（未知），呼叫端應存 NULL 而非假裝滿分。
        小數點取 4 位以對齊 conversations.stt_confidence Numeric(5,4)。
        """
        _, avg_logprobs = STTPipeline._segment_stats(response)
        source = avg_logprobs or STTPipeline._token_logprobs(response)
        if not source:
            return None
        mean_lp = sum(source) / len(source)
        return round(max(0.0, min(1.0, math.exp(mean_lp))), 4)

    async def close(self) -> None:
        """OpenAI AsyncClient 無需明確關閉，保留介面一致性。"""
        logger.info("STTPipeline 關閉")
