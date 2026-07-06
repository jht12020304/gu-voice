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
    render_critical_risk_factor_items,
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
- 病患已明確表示不知道、記不得或無法回答的項目,**不得**再讓 next_focus 指向它
  (換句話、換角度重問同樣禁止),一律改問其他尚未覆蓋的面向。
- 【背景資訊】中標註「intake 已提供」的過去病史/用藥/過敏/家族史屬既有資料,
  next_focus **不得**要求病患重述這些已知項目(它們也不屬 HPI 十欄);若臨床上需要
  釐清細節,才可針對「與本主訴直接相關」的單一具體點追問。
- next_focus 最大長度 60 個中文字以內,保持精簡。

## 病患表示「不知道」的處理(硬性規則)
病患對某一欄明確表示不知道、記不得、不確定或無法回答時,該欄視為**已盡力採集**:
- 從 missing_hpi 陣列中**移除**該欄,不要讓它一直留在缺失清單裡。
- next_focus **不得**再指向該欄(包括換句話重問)。
- hpi_completion_percentage **不因此壓低**——無法取得的資訊視同已覆蓋。

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

## hpi_completion_percentage 評分準則(重要,務必誠實評分)
- 只評估上方「HPI 十欄」的覆蓋程度,**不要**因為次要補問(藥物史/家族史/生活習慣/RoS)
  尚未問完就壓低分數——那些不屬於 HPI 十欄。
- 當十欄裡與本主訴**臨床相關**的項目已大致問到答案、或病患已明確表示不知道,即應給 **80 以上**;
  十欄都問到(或已盡力採集)給 90+。
- 不可為了讓問診繼續而刻意低估;系統會在完整度達標時自動收尾,讓病患不必一直被追問。
- 當完整度已達 80 以上、沒有臨床上必要的新問題時,next_focus 可改為「做一次簡短確認後收尾」,
  不要硬擠出可有可無的問題。
"""


# P0-1：把 patient_info（含 intake 已提供的病史/用藥/過敏/家族史）組成 Supervisor
# 背景資訊字串。抽成純函式以便單元測試（不需 mock OpenAI/Redis）。intake 欄位標註
# 「intake 已提供」讓 Supervisor prompt 的護欄能明確不重問已知項。
_INTAKE_CONTEXT_FIELDS: list[tuple[str, str]] = [
    ("medical_history", "過去病史"),
    ("medications", "目前用藥"),
    ("allergies", "過敏史"),
    ("family_history", "家族史"),
]


def build_patient_info_str(patient_info: dict[str, Any]) -> str:
    """組合 Supervisor 背景用的病患資訊字串（age/gender + intake 已提供項）。"""
    parts: list[str] = [
        f"年齡：{patient_info.get('age', '未知')}",
        f"性別：{patient_info.get('gender', '未知')}",
    ]
    for key, label in _INTAKE_CONTEXT_FIELDS:
        val = patient_info.get(key)
        if val:
            parts.append(f"{label}（intake 已提供）：{val}")
    return " / ".join(parts)


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

        # 組合病患資訊（P0-1）：analyze_next_step 早已收到完整 patient_info
        # （conversation_handler _validate_session 組好，與 build_system_prompt 同源），
        # 此前僅用 age/gender，現改用 build_patient_info_str 一併帶入 intake 已提供項。
        patient_info_str = build_patient_info_str(patient_info)

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

        # §3b：特定高風險主訴(血尿 / PSA / ED)在關鍵風險因子問到之前不得判「完整可收尾」。
        # 與上方「不因次要補問未問完壓低分數」的規則搭配:這些風險因子被提升為與 HPI 十欄
        # 同級,故可 gate 完整度;但仍遵守 don't-know 不變式——病患一旦回答或表示不知道即
        # 視為已採集,不再壓低、不再重問。無匹配主訴則不附加(其他主訴行為完全不變)。
        risk_factor_items = render_critical_risk_factor_items(chief_complaint)
        if risk_factor_items:
            system_prompt += (
                "\n\n## 本主訴的關鍵風險因子(與 HPI 十欄同級,收尾前必問)\n"
                "下列風險因子對本主訴的惡性 / 心血管風險分層至關重要,與 HPI 十欄同級:\n"
                f"{risk_factor_items}\n"
                "- 在這些風險因子**尚未問到**(病患既未回答、也未表示不知道)之前,"
                "hpi_completion_percentage **不得評為 80 以上**,next_focus 應優先安排"
                "詢問尚未問到的風險因子(每次一題)。\n"
                "- 一旦病患已回答、或已明確表示不知道 / 沒有,即視為**已盡力採集**:"
                "不再壓低分數、next_focus 不再指向該項(與 don't-know 規則一致)。"
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
