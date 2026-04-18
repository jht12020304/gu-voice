"""
高階督導模型 (Supervisor Engine)

負責在語音對話流程的背景非同步執行，分析病患的完整對話歷史，
產出「下一步發問建議 (next_focus)」與「缺失問診維度 (missing_hpi)」，
並寫入 Redis 快取供前線 Conversation Worker 動態讀取。

設計筆記:
- Supervisor 能力應 >= Conversation(被督導者)。目前 default 與 Conversation
  同走 gpt-4o(OPENAI_MODEL_SUPERVISOR 可在 .env 獨立升級);未來若取得
  reasoning 模型 access,在 .env 把 OPENAI_MODEL_SUPERVISOR 切過去並設
  OPENAI_REASONING_EFFORT_SUPERVISOR=medium 即可,不用動程式。
- next_focus 必須只有一個問題,否則會與 Conversation 的「一次只問一個問題」
  硬性規則衝突,導致 AI 在下一輪自我矛盾(塞多問題或違反字數限制)。
- missing_hpi 的合法值由 HPI_FIELD_IDS(shared.py)單一來源定義。
"""

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException
from app.core.openai_client import call_with_retry, get_openai_client
from app.pipelines.prompts.shared import (
    HPI_FIELD_IDS,
    SINGLE_QUESTION_RULE,
    render_hpi_checklist,
)
from app.utils.i18n_messages import get_message as _i18n_get


# BCP-47 → 人類語言名稱，用在 Supervisor 的 next_focus 輸出語言規則。
# 即使未來新增 locale，這裡只要加一列；fallback 走 English。
_LANGUAGE_DISPLAY: dict[str, str] = {
    "zh-TW": "Traditional Chinese (繁體中文)",
    "en-US": "US English",
    "ja-JP": "Japanese (日本語)",
    "ko-KR": "Korean (한국어)",
    "vi-VN": "Vietnamese (tiếng Việt)",
}

logger = logging.getLogger(__name__)

# SUPERVISOR_SYSTEM_PROMPT 使用 f-string 在模組載入時渲染 HPI 清單與單問題規則,
# 之後 .replace() 注入 patient_info_str 與 chief_complaint 兩個動態欄位。
SUPERVISOR_SYSTEM_PROMPT = f"""你是一位泌尿科資深主治醫師(Supervisor)。你的任務是在背景監督你的 AI 實習醫師與病患的問診過程。

## 背景資訊
- 病患基本資訊:{{patient_info_str}}
- 主訴:{{chief_complaint}}

## 實習醫師的問診任務(HPI 十欄框架)
{render_hpi_checklist()}

## 你的任務
閱讀下方的【當前對話紀錄】,評估實習醫師目前已經收集到哪些 HPI 資訊,還有哪些「關鍵且尚未收集」的資訊。
請給出明確指令告訴實習醫師「下一步具體該問什麼」,讓他在下一句話中執行。

## next_focus 書寫的硬性規則(極重要)
- **只能是一個問題**,不可把多個問題塞在同一條 next_focus 裡讓病患一次回答。
  - ❌ 錯誤示範:「請詢問病患血尿是否合併疼痛、是否有血塊、以及何時開始」
  - ✅ 正確示範:「請詢問病患血尿時是否伴隨疼痛」
- 必須是具體、可立即執行的指示,而非抽象建議。
  - ❌ 「請更深入詢問疼痛」→ ✅ 「請詢問疼痛是否會放射到鼠蹊部」
- 若目前 HPI 某一項尚未完成,繼續追問該項;完成後才移動到下一項。
- 若實習醫師問錯方向或重複問已得到答案的項目,next_focus 要明確拉回正確方向。
- next_focus 最大長度 60 個中文字以內,保持精簡。

{SINGLE_QUESTION_RULE}

## missing_hpi 的合法值(snake_case)
missing_hpi 陣列中的每一項必須是下列 id 字串之一,不可使用中文或其他拼法:
{", ".join(HPI_FIELD_IDS)}

## 回覆格式
請嚴格以下列 JSON 回覆,不可包含其餘文字:

{{{{
  "next_focus": "string(單一具體指令,最多 60 字)",
  "missing_hpi": ["string(上方合法 id,例如 'severity'、'associated_symptoms')"],
  "hpi_completion_percentage": 0
}}}}

hpi_completion_percentage 為 0-100 的整數,評估 HPI 十欄的整體完整度。
"""

class SupervisorEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = get_openai_client()
        self._model = settings.OPENAI_MODEL_SUPERVISOR
        self._reasoning_effort = settings.OPENAI_REASONING_EFFORT_SUPERVISOR
        self._max_tokens = settings.OPENAI_MAX_TOKENS_SUPERVISOR
        # reasoning_effort != "none" 時 API 會拒絕 temperature,走 reasoning
        # 路徑就不帶 temperature;fallback 到 "none"(目前 default)才用 0.2。
        self._temperature = 0.2

        logger.info(
            "SupervisorEngine 初始化 | model=%s, reasoning_effort=%s, max_tokens=%d",
            self._model,
            self._reasoning_effort,
            self._max_tokens,
        )

    async def analyze_next_step(
        self,
        session_id: str,
        conversation_history: list[dict[str, Any]],
        chief_complaint: str,
        patient_info: dict[str, Any],
        redis: Redis,
        language: str | None = None,
    ) -> None:
        """
        非同步分析對話歷史，找出下一步指引並存入 Redis。

        Args:
            session_id: 場次 ID
            conversation_history: 對話紀錄
            chief_complaint: 主訴
            patient_info: 病患資訊
            redis: Redis 客戶端
            language: BCP-47 場次語言；用來鎖 next_focus 輸出語言
                      （避免 Supervisor 寫中文指令回饋到 Conversation LLM 的英文輸出）。
        """
        if not conversation_history:
            return

        # 組合病患資訊
        patient_parts: list[str] = [
            f"年齡：{patient_info.get('age', '未知')}",
            f"性別：{patient_info.get('gender', '未知')}",
        ]
        patient_info_str = " / ".join(patient_parts)

        # 格式化對話
        transcript_lines = []
        for entry in conversation_history:
            role = "病患" if entry.get("role") in ("patient", "user") else "AI"
            content = entry.get("content", "")
            transcript_lines.append(f"{role}: {content}")
        transcript_text = "\n".join(transcript_lines)

        user_message = f"【當前對話紀錄】\n{transcript_text}\n\n請以 JSON 格式提供指導。"

        system_prompt = SUPERVISOR_SYSTEM_PROMPT.replace(
            "{patient_info_str}", patient_info_str
        ).replace(
            "{chief_complaint}", chief_complaint
        )

        # 把場次語言硬性規則附加到 system prompt 尾段，讓 next_focus 跟輸出語言一致。
        # 否則 Supervisor 會永遠寫中文指令 → 灌進 Conversation LLM system prompt 後
        # 部分情況下 Conversation LLM 會「順著中文指令」回中文，即使已有硬性輸出規則。
        if language:
            language_display = _LANGUAGE_DISPLAY.get(language, language)
            system_prompt += (
                f"\n\n## next_focus 輸出語言（硬性規定）\n"
                f"- 該場次病患使用 {language_display}，next_focus 內容必須以 {language_display} 撰寫。\n"
                f"- 長度限制依 {language_display} 語感調整為合理的短句（約 60 字元內）。\n"
                f"- missing_hpi 陣列仍使用下方指定的 snake_case id，不翻譯。"
            )

        try:
            logger.info("Supervisor [%s] 啟動背景分析...", session_id)
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "response_format": {"type": "json_object"},
                "max_completion_tokens": self._max_tokens,
            }
            if self._reasoning_effort and self._reasoning_effort != "none":
                create_kwargs["reasoning_effort"] = self._reasoning_effort
            else:
                create_kwargs["temperature"] = self._temperature
            response = await call_with_retry(
                lambda: self._client.chat.completions.create(**create_kwargs)
            )

            raw_content = response.choices[0].message.content or "{}"
            result = json.loads(raw_content)

            # 將結果存入 Redis
            redis_key = f"{self._settings.REDIS_KEY_PREFIX}session:{session_id}:supervisor_guidance"
            await redis.setex(
                redis_key, 
                1800,  # 30分鐘過期
                json.dumps(result, ensure_ascii=False)
            )

            logger.info(
                "Supervisor [%s] 指導已更新: %s (HPI 完整度: %s%%)",
                session_id,
                result.get("next_focus"),
                result.get("hpi_completion_percentage")
            )

        except Exception as exc:
            logger.error("Supervisor [%s] 分析失敗: %s", session_id, str(exc))
