"""
高階督導模型 (Supervisor Engine) — OpenAI GPT-5.4

負責在語音對話流程的背景非同步執行，分析病患的完整對話歷史，
產出「下一步發問建議 (next_focus)」與「缺失問診維度 (missing_hpi)」，
並寫入 Redis 快取供前線 gpt-5.4-mini (Worker) 動態讀取。
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """你是一位泌尿科資深主治醫師（Supervisor）。你的任務是「在背景監督」你的 AI 實習醫師與病患的問診過程。

## 背景資訊
- 病患基本資訊：{patient_info_str}
- 主訴：{chief_complaint}

## 實習醫師的問診任務 (HPI)
1. Onset（發生時間）
2. Location（位置）
3. Duration（持續時間）
4. Characteristics（特徵）
5. Severity（嚴重度）
6. Aggravating / Relieving factors（加重 / 緩解因素）
7. Associated symptoms（伴隨症狀）
8. Timing（時間模式）
9. Context（背景）

## 你的任務
閱讀下方的【當前對話紀錄】，評估實習醫師目前已經收集到哪些 HPI 資訊，還有哪些「關鍵且尚未收集」的資訊。
請給出明確指令告訴實習醫師「下一步具體該問什麼」，讓他在下一句話中執行。

請嚴格遵循 JSON 格式回覆，不可包含其餘文字：
```json
{
  "next_focus": "string (給實習醫師看的簡短指示，例如：'病患尚未說明血尿是否伴隨疼痛，請詢問這點')",
  "missing_hpi": ["string (上面 9 點中還缺少的項目，例如 'Severity', 'Associated symptoms')"],
  "hpi_completion_percentage": 0 (0到100的整數，評估 HPI 完整度)
}
```
"""

class SupervisorEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = getattr(settings, "OPENAI_MODEL_SUPERVISOR", "gpt-5.4")
        self._temperature = 0.2

        logger.info(
            "SupervisorEngine 初始化 | model=%s, temperature=%.1f",
            self._model,
            self._temperature,
        )

    async def analyze_next_step(
        self,
        session_id: str,
        conversation_history: list[dict[str, Any]],
        chief_complaint: str,
        patient_info: dict[str, Any],
        redis: Redis,
    ) -> None:
        """
        非同步分析對話歷史，找出下一步指引並存入 Redis。

        Args:
            session_id: 場次 ID
            conversation_history: 對話紀錄
            chief_complaint: 主訴
            patient_info: 病患資訊
            redis: Redis 客戶端
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

        try:
            logger.info("Supervisor [%s] 啟動背景分析...", session_id)
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=self._temperature,
                response_format={"type": "json_object"},
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
