"""
語音轉文字管線 — Google Cloud Speech-to-Text v2 (Chirp 模型)

提供即時串流語音辨識功能，針對泌尿科醫學術語進行最佳化。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from google.api_core import exceptions as gcp_exceptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech

from app.core.config import Settings

logger = logging.getLogger(__name__)

# ── 泌尿科醫學術語增強列表 ───────────────────────────────
_UROLOGY_BOOST_PHRASES: list[str] = [
    # 常見症狀
    "血尿", "頻尿", "排尿困難", "尿失禁", "夜尿", "急尿",
    "尿滯留", "尿道灼熱", "尿道疼痛", "尿流細小", "殘尿感",
    "尿中帶血", "解尿疼痛", "小便疼痛", "漏尿",
    # 解剖部位
    "攝護腺", "膀胱", "腎臟", "輸尿管", "尿道", "睪丸",
    "副睪", "陰囊", "腎盂", "腎上腺", "前列腺",
    # 疾病名稱
    "攝護腺肥大", "攝護腺癌", "膀胱癌", "腎結石", "輸尿管結石",
    "膀胱結石", "尿路感染", "膀胱炎", "腎盂腎炎", "前列腺炎",
    "泌尿道感染", "腎細胞癌", "膀胱過動症", "尿道狹窄",
    "精索靜脈曲張", "隱睪症", "包皮過長", "包莖",
    # 檢查與治療
    "PSA", "攝護腺特異抗原", "膀胱鏡", "尿路動力學",
    "經尿道攝護腺切除", "體外震波碎石", "達文西手術",
    "尿流速檢查", "餘尿測量", "腎功能", "肌酸酐",
    "超音波", "電腦斷層", "磁振造影",
    # 嚴重度描述
    "劇烈疼痛", "持續性", "間歇性", "突然發作", "逐漸惡化",
]

# ── 最大重試次數 ─────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0


class STTPipeline:
    """
    Google Cloud Speech-to-Text v2 串流辨識管線

    使用 Chirp 模型進行高品質中文語音辨識，
    並透過醫學術語增強提高泌尿科專業用語的辨識準確度。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 Google Cloud Speech 客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        self._project_id = settings.GOOGLE_CLOUD_PROJECT_ID
        self._model = settings.GOOGLE_STT_MODEL  # chirp_2
        self._sample_rate = settings.GOOGLE_STT_SAMPLE_RATE  # 16000
        self._client: SpeechAsyncClient | None = None

        logger.info(
            "STTPipeline 初始化 | project=%s, model=%s, sample_rate=%d",
            self._project_id,
            self._model,
            self._sample_rate,
        )

    async def _get_client(self) -> SpeechAsyncClient:
        """取得或建立 Speech 非同步客戶端（延遲初始化）"""
        if self._client is None:
            try:
                self._client = SpeechAsyncClient()
                logger.info("Google Cloud Speech 非同步客戶端已建立")
            except Exception as e:
                logger.warning("無法初始化 Google Cloud Speech，將禁用語音功能: %s", str(e))
                # 重新拋出或回傳 None，這裡如果沒網路會無法建立 stream_recognize
                raise
        return self._client

    def _build_recognition_config(
        self, language: str = "zh-TW"
    ) -> cloud_speech.RecognitionConfig:
        """
        建立辨識設定，包含 Chirp 模型與醫學術語增強

        Args:
            language: 主要語言代碼

        Returns:
            RecognitionConfig 實例
        """
        # 語言代碼列表（主要語言 + 英文作為備用）
        language_codes = [language]
        if "en" not in language.lower():
            language_codes.append("en-US")

        # 建立醫學術語增強短語集
        phrase_set = cloud_speech.SpeechAdaptation.AdaptationPhraseSet(
            inline_phrase_set=cloud_speech.PhraseSet(
                phrases=[
                    cloud_speech.PhraseSet.Phrase(value=phrase, boost=20.0)
                    for phrase in _UROLOGY_BOOST_PHRASES
                ]
            )
        )

        # 語音適應配置
        adaptation = cloud_speech.SpeechAdaptation(
            phrase_sets=[phrase_set],
        )

        config = cloud_speech.RecognitionConfig(
            explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self._sample_rate,
                audio_channel_count=1,
            ),
            language_codes=language_codes,
            model=self._model,
            adaptation=adaptation,
            features=cloud_speech.RecognitionFeatures(
                enable_automatic_punctuation=True,
                enable_word_confidence=True,
            ),
        )

        return config

    def _build_streaming_config(
        self, language: str = "zh-TW"
    ) -> cloud_speech.StreamingRecognitionConfig:
        """
        建立串流辨識設定

        Args:
            language: 主要語言代碼

        Returns:
            StreamingRecognitionConfig 實例
        """
        recognition_config = self._build_recognition_config(language)
        recognizer_path = (
            f"projects/{self._project_id}/locations/global/recognizers/_"
        )

        return cloud_speech.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=cloud_speech.StreamingRecognitionFeatures(
                interim_results=True,  # 啟用中間結果
            ),
        )

    async def stream_recognize(
        self,
        audio_generator: AsyncGenerator[bytes, None],
        language: str = "zh-TW",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        串流語音辨識 — 接收音訊片段，即時產出辨識結果

        Args:
            audio_generator: 非同步音訊位元組產生器
            language: 語言代碼，預設 zh-TW

        Yields:
            辨識結果字典：
            {
                "text": str,          # 辨識文字
                "confidence": float,   # 信心分數 (0.0 ~ 1.0)
                "is_final": bool,      # 是否為最終結果
                "words": list[dict],   # 字詞級別資訊
            }
        """
        retry_count = 0

        while retry_count <= _MAX_RETRIES:
            try:
                client = await self._get_client()
                streaming_config = self._build_streaming_config(language)
                recognizer_path = (
                    f"projects/{self._project_id}/locations/global/recognizers/_"
                )

                # 建立請求產生器：第一個請求帶設定，後續只帶音訊
                async def request_generator() -> (
                    AsyncGenerator[cloud_speech.StreamingRecognizeRequest, None]
                ):
                    # 首次請求：傳送辨識設定
                    yield cloud_speech.StreamingRecognizeRequest(
                        recognizer=recognizer_path,
                        streaming_config=streaming_config,
                    )

                    # 後續請求：傳送音訊資料
                    async for chunk in audio_generator:
                        if chunk:
                            yield cloud_speech.StreamingRecognizeRequest(
                                audio=chunk,
                            )

                # 發起串流辨識
                responses = await client.streaming_recognize(
                    requests=request_generator()
                )

                # 處理辨識回應
                async for response in responses:
                    for result in response.results:
                        if not result.alternatives:
                            continue

                        best_alternative = result.alternatives[0]

                        # 提取字詞級別資訊
                        words = []
                        for word_info in best_alternative.words:
                            words.append(
                                {
                                    "word": word_info.word,
                                    "confidence": word_info.confidence,
                                    "start_offset": (
                                        word_info.start_offset.total_seconds()
                                        if word_info.start_offset
                                        else None
                                    ),
                                    "end_offset": (
                                        word_info.end_offset.total_seconds()
                                        if word_info.end_offset
                                        else None
                                    ),
                                }
                            )

                        yield {
                            "text": best_alternative.transcript,
                            "confidence": best_alternative.confidence,
                            "is_final": result.is_final,
                            "words": words,
                        }

                # 成功完成，跳出重試迴圈
                break

            except gcp_exceptions.ServiceUnavailable as exc:
                retry_count += 1
                if retry_count > _MAX_RETRIES:
                    logger.error(
                        "STT 串流辨識失敗，已達最大重試次數 | retries=%d, error=%s",
                        _MAX_RETRIES,
                        str(exc),
                    )
                    raise
                logger.warning(
                    "STT 暫時性錯誤，準備重試 | retry=%d/%d, error=%s",
                    retry_count,
                    _MAX_RETRIES,
                    str(exc),
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS * retry_count)

            except gcp_exceptions.DeadlineExceeded as exc:
                retry_count += 1
                if retry_count > _MAX_RETRIES:
                    logger.error(
                        "STT 串流辨識逾時，已達最大重試次數 | retries=%d, error=%s",
                        _MAX_RETRIES,
                        str(exc),
                    )
                    raise
                logger.warning(
                    "STT 逾時錯誤，準備重試 | retry=%d/%d, error=%s",
                    retry_count,
                    _MAX_RETRIES,
                    str(exc),
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS * retry_count)

            except gcp_exceptions.InvalidArgument as exc:
                # 參數錯誤不重試
                logger.error("STT 參數錯誤（不重試）| error=%s", str(exc))
                raise

            except Exception as exc:
                logger.error(
                    "STT 串流辨識發生未預期錯誤 | error=%s", str(exc), exc_info=True
                )
                raise

    async def close(self) -> None:
        """關閉客戶端連線，釋放資源"""
        if self._client is not None:
            transport = self._client.transport
            if hasattr(transport, "close"):
                await transport.close()
            self._client = None
            logger.info("STTPipeline 客戶端已關閉")
