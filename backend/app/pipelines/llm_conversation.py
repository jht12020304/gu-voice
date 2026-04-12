"""
LLM 對話引擎 — OpenAI GPT-4o 結構化問診

負責驅動泌尿科 AI 問診助手的對話邏輯，
遵循 HPI (History of Present Illness) 框架進行結構化問診。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException

logger = logging.getLogger(__name__)


class LLMConversationEngine:
    """
    OpenAI GPT-4o 對話引擎

    根據病患主訴驅動結構化問診流程，
    一次一個問題地引導病患描述症狀細節。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 OpenAI 非同步客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL_CONVERSATION  # gpt-4o
        self._temperature = settings.OPENAI_TEMPERATURE_CONVERSATION  # 0.7
        self._max_tokens = settings.OPENAI_MAX_TOKENS_CONVERSATION  # 512

        logger.info(
            "LLMConversationEngine 初始化 | model=%s, temperature=%.1f, max_tokens=%d",
            self._model,
            self._temperature,
            self._max_tokens,
        )

    def _get_complaint_red_flags(self, chief_complaint: str) -> str:
        """根據主訴取得對應的紅旗症狀列表"""
        RED_FLAGS_BY_COMPLAINT = {
            "血尿": [
                "大量血尿或有血塊",
                "排尿時伴隨劇烈疼痛或完全無法排尿",
                "合併發燒、畏寒（可能尿路感染合併菌血症）",
                "不明原因體重下降超過 3 公斤",
            ],
            "腰痛": [
                "劇烈單側腰痛合併噁心嘔吐（可能腎結石）",
                "腰痛合併發燒超過 38.5°C",
                "腰痛合併肉眼可見血尿",
                "有腎移植病史",
            ],
            "腰痛（腎臟區域）": [
                "劇烈單側腰痛合併噁心嘔吐（可能腎結石）",
                "腰痛合併發燒超過 38.5°C",
                "腰痛合併肉眼可見血尿",
                "有腎移植病史",
            ],
            "頻尿": [
                "完全無法排尿（急性尿滯留）",
                "合併高燒寒顫",
                "持續血尿",
                "老年男性合併下腹脹痛",
            ],
            "排尿困難": [
                "完全無法排尿（急性尿滯留）",
                "合併高燒寒顫",
                "持續血尿",
                "老年男性合併下腹脹痛",
            ],
            "睪丸疼痛": [
                "突然雙側劇烈疼痛（睪丸扭轉，6 小時黃金期）",
                "睪丸明顯腫脹變形",
                "合併噁心嘔吐",
            ],
        }

        # 基礎通用紅旗
        general_flags = [
            "大量血尿或血塊",
            "無法排尿（急性尿滯留）",
            "劇烈腰部或腹部疼痛合併發燒",
            "睪丸突然劇烈疼痛（可能為睪丸扭轉）",
            "尿路感染症狀合併高燒、寒顫",
            "不明原因體重急速下降"
        ]

        # 找出是否有吻合的特化紅旗
        matched_flags = general_flags
        for key, flags in RED_FLAGS_BY_COMPLAINT.items():
            if key in chief_complaint:
                matched_flags = flags
                break

        return "\n".join(f"- {flag}" for flag in matched_flags)

    def build_system_prompt(
        self, chief_complaint: str, patient_info: dict[str, Any]
    ) -> str:
        """
        根據主訴與病患資訊建構系統提示詞

        Args:
            chief_complaint: 病患主訴（例如「血尿」、「頻尿」）
            patient_info: 病患基本資訊（姓名、年齡、性別、病史等）

        Returns:
            完整系統提示詞字串
        """
        # 組合病患資訊摘要
        patient_summary_parts: list[str] = []
        if patient_info.get("name"):
            patient_summary_parts.append(f"姓名：{patient_info['name']}")
        if patient_info.get("age"):
            patient_summary_parts.append(f"年齡：{patient_info['age']} 歲")
        if patient_info.get("gender"):
            gender_map = {"male": "男性", "female": "女性", "other": "其他"}
            patient_summary_parts.append(
                f"性別：{gender_map.get(patient_info['gender'], patient_info['gender'])}"
            )
        if patient_info.get("medical_history"):
            patient_summary_parts.append(f"過去病史：{patient_info['medical_history']}")
        if patient_info.get("medications"):
            patient_summary_parts.append(f"目前用藥：{patient_info['medications']}")
        if patient_info.get("allergies"):
            patient_summary_parts.append(f"過敏史：{patient_info['allergies']}")

        patient_section = "\n".join(patient_summary_parts) if patient_summary_parts else "（尚未提供詳細資訊）"
        red_flags_section = self._get_complaint_red_flags(chief_complaint)

        system_prompt = f"""你是一位專業的泌尿科 AI 問診助手，負責協助進行初步問診。

## 角色定位
- 你是泌尿科門診的 AI 問診助手
- 使用繁體中文與病患溝通
- 語氣親切、專業且具同理心

## 病患資訊
{patient_section}

## 主訴
{chief_complaint}

## 問診任務
根據病患的主訴「{chief_complaint}」，遵循 HPI（現病史）框架進行結構化問診：

1. **Onset（發生時間）**：症狀何時開始？突然還是漸進式？
2. **Location（位置）**：確切的不適部位在哪裡？
3. **Duration（持續時間）**：症狀持續多久？是持續性還是間歇性？
4. **Characteristics（特徵）**：症狀的性質是什麼？（例如疼痛的類型）
5. **Severity（嚴重度）**：以 1-10 分評估嚴重程度
6. **Aggravating / Relieving factors（加重／緩解因素）**：什麼會使症狀加重或減輕？
7. **Associated symptoms（伴隨症狀）**：是否有其他伴隨的症狀？
8. **Timing（時間模式）**：症狀在什麼時候特別明顯？（如夜間、排尿時）
9. **Context（背景）**：症狀發生的背景脈絡？（如受傷、手術後）

## 問診準則
- **一次只問一個問題**，避免同時提出多個問題造成病患混淆
- 使用病患能理解的日常用語，避免過度使用醫學專業術語
- 若病患的回答不夠明確，可進行追問以釐清
- 適時表達關心與同理心（例如「我了解這對您來說很不舒服」）
- 不做診斷或治療建議，僅進行症狀收集
- 每次回覆最多 2 句話，請保持簡潔明瞭
- 若偵測紅旗，在句尾加上：「這個症狀需要盡速就醫，請不要等待。」

## 紅旗症狀注意
請特別留意以下可能需要緊急處理的紅旗症狀：
{red_flags_section}

若偵測到紅旗症狀，請在回覆中明確提醒病患盡速就醫。

## 回覆格式
- 使用自然、口語化的繁體中文
- 每次回覆簡潔明瞭，通常 1-3 句話
- 不使用 markdown 格式（不加粗、不用清單）或特殊符號
- 不說「好的」「了解」等空洞開場白，直接進入問題"""

        return system_prompt

    def format_messages(
        self, history: list[dict[str, Any]], system_prompt: str, supervisor_guidance: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        """
        將對話歷史格式化為 OpenAI Chat Completions API 的訊息格式

        Args:
            history: 對話歷史列表，每筆包含 role 和 content
            system_prompt: 系統提示詞
            supervisor_guidance: 來自 Supervisor 的動態指導

        Returns:
            格式化後的訊息列表
        """
        final_system_prompt = system_prompt

        if supervisor_guidance:
            next_focus = supervisor_guidance.get("next_focus", "")
            if next_focus:
                final_system_prompt += f"\n\n## 👨‍⚕️ 來自資深醫師的即時指導（請優先執行）\n{next_focus}"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": final_system_prompt}
        ]

        for entry in history:
            role = entry.get("role", "user")
            content = entry.get("content", "")

            # 將內部角色對應到 OpenAI API 角色
            if role in ("patient", "user"):
                messages.append({"role": "user", "content": content})
            elif role in ("assistant", "ai"):
                messages.append({"role": "assistant", "content": content})
            # system 角色的歷史訊息跳過（系統提示已在最前面）

        return messages

    async def generate_response(
        self,
        messages: list[dict[str, str]],
        session_context: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """
        呼叫 OpenAI Chat Completions API 串流生成回應

        Args:
            messages: 格式化後的訊息列表（含 system prompt）
            session_context: 場次上下文資訊（用於日誌記錄等）

        Yields:
            回應文字片段（逐 chunk 產出）

        Raises:
            AIServiceUnavailableException: OpenAI API 不可用時
        """
        session_id = session_context.get("session_id", "unknown")

        try:
            logger.info(
                "呼叫 LLM 生成回應 | session=%s, model=%s, messages_count=%d",
                session_id,
                self._model,
                len(messages),
            )

            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_completion_tokens=self._max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text_piece = chunk.choices[0].delta.content
                    yield text_piece

        except Exception as exc:
            logger.error(
                "LLM 回應生成失敗 | session=%s, error=%s",
                session_id,
                str(exc),
                exc_info=True,
            )
            raise AIServiceUnavailableException(
                message="AI 對話服務暫時不可用，請稍後重試",
                details={"session_id": session_id, "error": str(exc)},
            )
