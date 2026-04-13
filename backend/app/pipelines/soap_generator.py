"""
SOAP 報告生成器 — OpenAI GPT-4o 結構化輸出

將問診對話記錄轉換為標準 SOAP (Subjective, Objective, Assessment, Plan)
格式的醫療報告，供醫師審閱與修改。
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException

logger = logging.getLogger(__name__)

# ── SOAP 生成系統提示詞 ──────────────────────────────────
_SOAP_SYSTEM_PROMPT = """你是一位資深泌尿科專科醫師，正在根據 AI 問診對話記錄撰寫 SOAP 格式的醫療記錄。

## 任務
根據以下問診對話記錄，產生一份完整的 SOAP 醫療報告。

## SOAP 格式要求

### Subjective（主觀）
從病患描述中擷取：
- chief_complaint: 主訴（簡潔一句話）
- hpi: 現病史，包含以下子項目（若對話中有提及）：
  - onset: 發生時間
  - location: 位置
  - duration: 持續時間
  - characteristics: 特徵描述
  - severity: 嚴重度（1-10 分或描述性文字）
  - aggravating_factors: 加重因素
  - relieving_factors: 緩解因素
  - associated_symptoms: 伴隨症狀
  - timing: 時間模式
  - context: 發生背景
- past_medical_history: 過去病史
- medications: 目前用藥
- allergies: 過敏史
- family_history: 家族史
- social_history: 社會史
- review_of_systems: 系統回顧

### Objective（客觀）
- vital_signs: 生命徵象（若有提及）
- physical_exam: 理學檢查發現（若有提及）
- lab_results: 實驗室檢查結果（若有提及）
- imaging_results: 影像學檢查結果（若有提及）
- 注意：問診助手通常無法取得客觀資料，可標記為「待醫師補充」

### Assessment（評估）
- differential_diagnoses: 鑑別診斷列表（按可能性由高至低排列），每項包含：
  - diagnosis: 診斷名稱
  - likelihood: 可能性（high/moderate/low）
  - reasoning: 推理依據
- clinical_impression: 臨床印象摘要

### Plan（計畫）
- recommended_tests: 建議檢查列表（結構化物件，含詳細臨床推理）
- treatments: 建議治療
- medications: 建議用藥
- follow_up: 追蹤計畫
- patient_education: 衛教內容
- referrals: 轉介建議
- diagnostic_reasoning: 整體診斷推理說明（為什麼選擇這組檢查方案，臨床思路是什麼）

## 回覆格式
請以嚴格的 JSON 格式回覆，結構如下。所有文字使用繁體中文。

```json
{
  "subjective": {
    "chief_complaint": "string",
    "hpi": {
      "onset": "string or null",
      "location": "string or null",
      "duration": "string or null",
      "characteristics": "string or null",
      "severity": "string or null",
      "aggravating_factors": "string or null",
      "relieving_factors": "string or null",
      "associated_symptoms": "string or null",
      "timing": "string or null",
      "context": "string or null"
    },
    "past_medical_history": "string or null",
    "medications": "string or null",
    "allergies": "string or null",
    "family_history": "string or null",
    "social_history": "string or null",
    "review_of_systems": "string or null"
  },
  "objective": {
    "vital_signs": "string or null",
    "physical_exam": "string or null",
    "lab_results": "string or null",
    "imaging_results": "string or null"
  },
  "assessment": {
    "differential_diagnoses": [
      {
        "diagnosis": "string",
        "likelihood": "high|moderate|low",
        "reasoning": "string"
      }
    ],
    "clinical_impression": "string"
  },
  "plan": {
    "recommended_tests": [
      {
        "test_name": "string (檢查名稱)",
        "rationale": "string (簡短原因，一句話)",
        "urgency": "urgent|routine|elective",
        "clinical_reasoning": "string (詳細臨床推理：根據對話中哪些資訊、結合哪些臨床指引或醫學邏輯，為什麼建議此項檢查，2-4 句話)"
      }
    ],
    "treatments": ["string"],
    "medications": ["string"],
    "follow_up": "string",
    "patient_education": ["string"],
    "referrals": ["string"],
    "diagnostic_reasoning": "string (整體檢查策略的臨床推理：說明基於此病患的臨床特徵組合，為什麼採用這樣的檢查方案，各項檢查之間的邏輯關聯，3-5 句話)"
  },
  "summary": "string (問診對話摘要：用 3-5 句話概述整段問診過程的重點，包含主訴、關鍵病史、重要發現、以及初步評估方向)",
  "icd10_codes": ["string (相關 ICD-10 代碼)"],
  "confidence_score": 0.0
}
```

## 注意事項
- 若對話中未提及某項資訊，該欄位填入 null 而非猜測
- confidence_score (0.0-1.0) 反映對話完整度與報告品質的自我評估
- 鑑別診斷應根據對話內容合理推論，至少列出 2-3 項
- ICD-10 代碼應盡可能準確
- recommended_tests 的 clinical_reasoning 必須引用對話中的具體資訊，說明推理過程
- diagnostic_reasoning 必須解釋各項檢查之間的邏輯關聯與臨床決策依據
- summary 應為問診對話的摘要，而非僅是診斷摘要
- 所有內容使用繁體中文（ICD-10 代碼除外）"""


class SOAPGenerator:
    """
    SOAP 醫療報告生成器

    使用 OpenAI GPT-4o 模型，從問診對話記錄中
    擷取結構化資訊並生成標準 SOAP 格式報告。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 OpenAI 客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL_SOAP  # gpt-4o
        self._temperature = settings.OPENAI_TEMPERATURE_SOAP  # 0.3
        self._max_tokens = settings.OPENAI_MAX_TOKENS_SOAP  # 4096

        logger.info(
            "SOAPGenerator 初始化 | model=%s, temperature=%.1f, max_tokens=%d",
            self._model,
            self._temperature,
            self._max_tokens,
        )

    def _format_transcript(self, transcript: list[dict[str, Any]]) -> str:
        """
        將對話記錄格式化為可讀文字

        Args:
            transcript: 對話記錄列表，每筆包含 role 和 content

        Returns:
            格式化後的對話文字
        """
        lines: list[str] = []
        for entry in transcript:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            timestamp = entry.get("timestamp", "")

            # 角色名稱中文化
            role_label = {
                "patient": "病患",
                "user": "病患",
                "assistant": "AI 助手",
                "ai": "AI 助手",
                "system": "系統",
            }.get(role, role)

            time_str = f" [{timestamp}]" if timestamp else ""
            lines.append(f"{role_label}{time_str}：{content}")

        return "\n".join(lines)

    async def generate(
        self,
        transcript: list[dict[str, Any]],
        patient_info: dict[str, Any],
        chief_complaint: str,
    ) -> dict[str, Any]:
        """
        根據對話記錄生成 SOAP 報告

        Args:
            transcript: 對話記錄列表
            patient_info: 病患基本資訊
            chief_complaint: 主訴

        Returns:
            結構化 SOAP 報告字典：
            {
                "subjective": {...},
                "objective": {...},
                "assessment": {...},
                "plan": {...},
                "summary": str,
                "icd10_codes": list[str],
                "confidence_score": float,
            }

        Raises:
            AIServiceUnavailableException: OpenAI API 不可用時
        """
        # 組合病患資訊
        patient_parts: list[str] = []
        if patient_info.get("name"):
            patient_parts.append(f"姓名：{patient_info['name']}")
        if patient_info.get("age"):
            patient_parts.append(f"年齡：{patient_info['age']} 歲")
        if patient_info.get("gender"):
            gender_map = {"male": "男性", "female": "女性", "other": "其他"}
            patient_parts.append(
                f"性別：{gender_map.get(patient_info['gender'], patient_info['gender'])}"
            )
        if patient_info.get("medical_history"):
            patient_parts.append(f"過去病史：{patient_info['medical_history']}")
        if patient_info.get("medications"):
            patient_parts.append(f"目前用藥：{patient_info['medications']}")
        if patient_info.get("allergies"):
            patient_parts.append(f"過敏史：{patient_info['allergies']}")
        if patient_info.get("family_history"):
            patient_parts.append(f"家族病史：{patient_info['family_history']}")

        patient_text = "\n".join(patient_parts) if patient_parts else "（未提供）"
        transcript_text = self._format_transcript(transcript)

        user_message = f"""## 病患基本資訊
{patient_text}

## 主訴
{chief_complaint}

## 問診對話記錄
{transcript_text}

請根據以上資訊產生完整的 SOAP 報告。"""

        try:
            logger.info(
                "開始生成 SOAP 報告 | chief_complaint=%s, transcript_length=%d",
                chief_complaint,
                len(transcript),
            )

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SOAP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=self._temperature,
                max_completion_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )

            raw_content = response.choices[0].message.content or "{}"
            soap_report = json.loads(raw_content)

            # 驗證並補齊必要欄位
            soap_report = self._validate_and_fill(soap_report, chief_complaint)

            logger.info(
                "SOAP 報告生成完成 | confidence=%.2f, diagnoses_count=%d",
                soap_report.get("confidence_score", 0),
                len(
                    soap_report.get("assessment", {}).get(
                        "differential_diagnoses", []
                    )
                ),
            )

            return soap_report

        except json.JSONDecodeError as exc:
            logger.error("SOAP 報告 JSON 解析失敗 | error=%s", str(exc))
            raise AIServiceUnavailableException(
                message="SOAP 報告生成失敗：回應格式異常",
                details={"error": str(exc)},
            )

        except Exception as exc:
            logger.error(
                "SOAP 報告生成失敗 | error=%s", str(exc), exc_info=True
            )
            raise AIServiceUnavailableException(
                message="SOAP 報告生成服務暫時不可用，請稍後重試",
                details={"error": str(exc)},
            )

    @staticmethod
    def _validate_and_fill(
        report: dict[str, Any], chief_complaint: str
    ) -> dict[str, Any]:
        """
        驗證 SOAP 報告結構並補齊缺失欄位

        Args:
            report: 原始報告字典
            chief_complaint: 主訴（用於補齊）

        Returns:
            驗證並補齊後的報告字典
        """
        # 確保頂層結構完整
        if "subjective" not in report:
            report["subjective"] = {}
        if "objective" not in report:
            report["objective"] = {}
        if "assessment" not in report:
            report["assessment"] = {}
        if "plan" not in report:
            report["plan"] = {}

        # Subjective 補齊
        subj = report["subjective"]
        if not subj.get("chief_complaint"):
            subj["chief_complaint"] = chief_complaint
        if "hpi" not in subj:
            subj["hpi"] = {}
        hpi_fields = [
            "onset", "location", "duration", "characteristics",
            "severity", "aggravating_factors", "relieving_factors",
            "associated_symptoms", "timing", "context",
        ]
        for field in hpi_fields:
            if field not in subj["hpi"]:
                subj["hpi"][field] = None

        # Objective 補齊
        obj = report["objective"]
        for field in ["vital_signs", "physical_exam", "lab_results", "imaging_results"]:
            if field not in obj:
                obj[field] = None

        # Assessment 補齊
        assess = report["assessment"]
        if "differential_diagnoses" not in assess:
            assess["differential_diagnoses"] = []
        if "clinical_impression" not in assess:
            assess["clinical_impression"] = ""

        # Plan 補齊
        plan = report["plan"]
        for field in [
            "recommended_tests", "treatments", "medications",
            "follow_up", "patient_education", "referrals",
        ]:
            if field not in plan:
                plan[field] = [] if field != "follow_up" else None
        if "diagnostic_reasoning" not in plan:
            plan["diagnostic_reasoning"] = None

        # 確保 recommended_tests 為結構化物件陣列
        if isinstance(plan.get("recommended_tests"), list):
            normalized_tests = []
            for item in plan["recommended_tests"]:
                if isinstance(item, str):
                    # 舊格式：純字串 → 轉為物件
                    normalized_tests.append({
                        "test_name": item,
                        "rationale": "",
                        "urgency": "routine",
                        "clinical_reasoning": "",
                    })
                elif isinstance(item, dict):
                    item.setdefault("test_name", item.get("name", ""))
                    item.setdefault("rationale", "")
                    item.setdefault("urgency", "routine")
                    item.setdefault("clinical_reasoning", "")
                    normalized_tests.append(item)
            plan["recommended_tests"] = normalized_tests

        # 頂層欄位
        if "summary" not in report:
            report["summary"] = ""
        if "icd10_codes" not in report:
            report["icd10_codes"] = []
        if "confidence_score" not in report:
            report["confidence_score"] = 0.0

        # 確保 confidence_score 為合法數值
        try:
            score = float(report["confidence_score"])
            report["confidence_score"] = max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            report["confidence_score"] = 0.0

        return report
