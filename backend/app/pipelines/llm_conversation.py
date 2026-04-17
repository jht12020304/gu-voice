"""
LLM 對話引擎 — OpenAI GPT-4o 結構化問診

負責驅動泌尿科 AI 問診助手的對話邏輯，
遵循 HPI (History of Present Illness) 框架進行結構化問診。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException
from app.core.openai_client import (
    budget_messages,
    call_with_retry,
    get_openai_client,
)
from app.pipelines.prompts.shared import (
    SINGLE_QUESTION_RULE,
    render_hpi_checklist,
    render_red_flags_for_conversation,
)

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
        self._client = get_openai_client()
        self._model = settings.OPENAI_MODEL_CONVERSATION  # default gpt-4o
        self._temperature = settings.OPENAI_TEMPERATURE_CONVERSATION  # 0.7
        self._max_tokens = settings.OPENAI_MAX_TOKENS_CONVERSATION  # 2048
        # reasoning 模型(o1 / o3 / gpt-5 等)專用參數。"none" 代表傳統 chat
        # 模型路徑(gpt-4o),程式會完全不送 reasoning_effort 並改送 temperature。
        self._reasoning_effort = settings.OPENAI_REASONING_EFFORT_CONVERSATION

        logger.info(
            "LLMConversationEngine 初始化 | model=%s, temperature=%.1f, max_tokens=%d, reasoning_effort=%s",
            self._model,
            self._temperature,
            self._max_tokens,
            self._reasoning_effort,
        )

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
        if patient_info.get("family_history"):
            patient_summary_parts.append(f"家族病史：{patient_info['family_history']}")

        patient_section = "\n".join(patient_summary_parts) if patient_summary_parts else "（尚未提供詳細資訊）"
        # HPI 10 欄框架與主訴相關紅旗都從 shared.py 單一來源渲染,
        # 與 SOAP hpi schema、red_flag detector 知識庫對齊(P1-D、P2-E)。
        hpi_section = render_hpi_checklist()
        red_flags_section = render_red_flags_for_conversation(chief_complaint)

        system_prompt = f"""你是一位專業的泌尿科 AI 問診助手，負責協助進行初步問診。

## 角色定位
- 你是泌尿科門診的 AI 問診助手
- 使用繁體中文與病患溝通
- 語氣親切、專業且具同理心

## 病患資訊
{patient_section}

## 主訴
{chief_complaint}

## 主要問診任務（HPI 十欄框架）
根據病患的主訴「{chief_complaint}」，依序收集下列十個 HPI 面向：
{hpi_section}

## 次要補問（HPI 完整度較高後才進入）
當上述 HPI 十欄已大致問完（約 7 成以上），請視對話狀況補問下列臨床文件需要的資訊，
每次仍只問一題，且只在與主訴相關時才問：
- 過往泌尿科相關疾病或手術史
- 目前服用中的藥物（特別是抗凝血劑、利尿劑、攝護腺藥物）
- 已知藥物過敏
- 家族是否有泌尿道癌症、腎結石或攝護腺疾病史
- 相關生活習慣（例如飲水量、咖啡因、吸菸，限與主訴有關聯時）
- 其他系統的不適（review of systems，僅在臨床相關時補問）

若病患於 intake 表單已提供上述資訊，則不需重複詢問，直接進入 HPI。

## 問診準則
- 使用病患能理解的日常用語，避免過度使用醫學專業術語
- 若病患的回答不夠明確，可進行追問以釐清
- 適時表達關心與同理心（例如「我了解這對您來說很不舒服」）
- 不做診斷或治療建議，僅進行症狀收集
- 每次回覆最多 2 句話，請保持簡潔明瞭
- 若偵測紅旗，在句尾加上：「這個症狀需要盡速就醫，請不要等待。」

{SINGLE_QUESTION_RULE}

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
                "呼叫 LLM 生成回應 | session=%s, model=%s, reasoning_effort=%s, messages_count=%d",
                session_id,
                self._model,
                self._reasoning_effort,
                len(messages),
            )

            # 模型能力分兩類:
            #   (a) reasoning 模型 (o1 / o3-mini / gpt-5 系列):可吃 reasoning_effort=
            #       low/medium/high,且此時 API 會拒絕 temperature。
            #   (b) 傳統 chat 模型 (gpt-4o / gpt-4.1 系列):不認識 reasoning_effort 參數,
            #       任何值(包括字面字串 "none")都會被 API 拒絕,但接受 temperature。
            # 約定:OPENAI_REASONING_EFFORT_CONVERSATION="none" 代表「走傳統路徑」,
            # 這時完全不送 reasoning_effort,只送 temperature。
            # P1-#7：送 LLM 前先套 token budget（context_limit - max_tokens - reserve），
            # 超量時保留 system prompt、從頭部丟舊對話。
            budgeted = budget_messages(messages, self._model, self._max_tokens)

            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": budgeted,
                "max_completion_tokens": self._max_tokens,
                "stream": True,
            }
            if self._reasoning_effort and self._reasoning_effort != "none":
                # reasoning 路徑:送 reasoning_effort,不送 temperature
                create_kwargs["reasoning_effort"] = self._reasoning_effort
            else:
                # 傳統路徑:送 temperature,完全不送 reasoning_effort
                create_kwargs["temperature"] = self._temperature

            # 只有 stream 初建失敗（429 / timeout）才重試；一旦開始收 chunk 就不能重試。
            stream = await call_with_retry(
                lambda: self._client.chat.completions.create(**create_kwargs)
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
