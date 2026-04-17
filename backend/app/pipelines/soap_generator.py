"""
SOAP 報告生成器 — OpenAI GPT-4o 結構化輸出

將問診對話記錄轉換為標準 SOAP (Subjective, Objective, Assessment, Plan)
格式的醫療報告，供醫師審閱與修改。
"""

import json
import logging
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException
from app.core.openai_client import call_with_retry, get_openai_client
from app.utils.i18n_messages import get_message

logger = logging.getLogger(__name__)

# ── SOAP 生成系統提示詞 ──────────────────────────────────
_SOAP_SYSTEM_PROMPT = """你是資深泌尿科門診臨床文件助理，任務是根據問診對話內容產出一份嚴謹、可供醫師快速審閱的 SOAP 初稿。

## 你的角色
- 你不是最終診斷醫師。
- 你只能依據提供的對話內容整理資訊，不可自行虛構、補齊或推論未被明確提及的病史、理學檢查、檢驗結果或診斷。
- 若資訊不足，物件欄位請填 null、list 欄位請填空陣列 []，不要杜撰，也不要填「未提及」、「無」、空字串。

## 核心原則
1. 嚴格依據對話內容，不得杜撰。
2. 不可將病人的猜測當成醫學事實。
3. 不可將「尚未執行的檢查」寫成已完成的結果。
4. 若病人表達不確定，請保留不確定性。
5. 若對話中有互相矛盾的資訊，請在 clinical_impression 中簡短標示。
6. 優先保留對臨床有價值的資訊，避免冗長重述。
7. 用專業、簡潔、可讀性高的繁體中文撰寫（ICD-10 代碼除外）。
8. 不要輸出多餘前言、解釋、註解，只輸出指定 JSON。

## 泌尿科初診需特別注意的資訊
請優先從對話中辨識並整理下列項目（未提及則填 null 或空陣列）：
- 主訴：頻尿、夜尿、急尿、排尿困難、尿流變細、解尿疼痛、尿失禁、血尿、腰痛、下腹痛、陰囊痛、會陰痛
- 症狀時間軸：何時開始、持續多久、突然或漸進、是否反覆
- 嚴重度與變化：加重、改善、間歇、持續
- 伴隨症狀：發燒、寒顫、噁心、嘔吐、背痛、側腹痛、排尿灼熱、尿液混濁、尿臭、血塊、體重減輕
- 排尿型態：頻率、夜尿次數、尿急、尿痛、解不乾淨、尿滯留感、滴尿、尿流弱
- 血尿細節：肉眼/非肉眼、是否有血塊、是否疼痛
- 疼痛細節：部位、性質、放射、程度、誘發/緩解因子
- 感染相關：過去泌尿道感染、近期抗生素、導尿、發燒
- 結石相關：過往結石、類似發作史
- 攝護腺相關：年長男性下泌尿道症狀、排尿困難、夜尿、尿流弱
- 性與生殖相關：陰莖分泌物、睪丸腫痛、性功能問題（僅限對話有提及）
- 婦女相關：懷孕可能性、月經/陰道出血與泌尿症狀混淆（僅限對話有提及）
- 既往史、用藥史、過敏史、社會史：僅在對話有提及時整理

## 各區塊撰寫規則

### Subjective（主觀）
- chief_complaint：簡潔一句話的主訴。
- hpi 必須為物件（dict），包含 10 個子欄位（onset / location / duration / characteristics / severity / aggravating_factors / relieving_factors / associated_symptoms / timing / context）；每個子欄位為字串或 null。
- past_medical_history / medications / allergies / family_history / social_history / review_of_systems **必須為單一字串或 null**，不要使用 list；可用逗點或短句整理多筆資訊。

### Objective（客觀）
- 問診助手通常無法取得客觀資料。若對話中完全沒有，請把 vital_signs / physical_exam / lab_results / imaging_results **全部填 null**。
- 不得把病人的主觀描述（例如「我自己量體溫 38 度」）誤列為理學檢查；病人自述的數值仍應算在 subjective。
- 每個欄位必須為字串或 null，不可為物件或陣列。

### Assessment（評估）
- differential_diagnoses：以可能性由高至低排列的鑑別診斷陣列，至少 2-3 項；每項需提供 diagnosis、likelihood、reasoning。
- likelihood **只能是 "high"、"moderate"、"low"** 其中之一（注意是 moderate 不是 medium）。
- reasoning 必須引用對話中的具體症狀或病史，不可只寫「臨床常見」這類空話。
- clinical_impression：一段文字總結臨床判斷方向，需保留不確定性；若有紅旗徵象，請在開頭明確標示。
- 不可直接下 definitive diagnosis，除非對話中已有明確既有診斷被病人陳述。

### Plan（計畫）
- recommended_tests：建議檢查列表（**物件陣列**），每項包含 test_name、rationale（一句話原因）、urgency、clinical_reasoning（2-4 句，需引用對話資訊與醫學邏輯）。
- urgency **只能是 "urgent"、"routine"、"elective"** 其中之一。
- treatments、medications、patient_education、referrals 皆為**字串陣列（list[string]）**，不可為物件陣列。
- follow_up 為單一字串。
- diagnostic_reasoning：3-5 句說明整體檢查策略與臨床決策依據，解釋各項檢查之間的邏輯關聯。
- 書寫語氣需為「建議評估／可考慮」，不可寫成「已安排」「已開立」。
- 若有高風險紅旗，Plan 應明確寫出需優先緊急評估。

### 頂層欄位
- summary：3-5 句問診對話摘要（主訴、關鍵病史、重要發現、初步方向），而非僅是診斷摘要。
- icd10_codes：list[string]，保留英文與數字格式，盡可能準確。
- confidence_score：0.0-1.0 的浮點數，反映對話對 **HPI 十欄與鑑別診斷依據** 的完整度。
  family_history / social_history / review_of_systems 若未於對話中收集到屬於正常情況
  （由醫師現場補問），**不應以此壓低分數**。主要扣分項為：HPI 缺漏、主訴模糊、
  鑑別診斷無法從對話內容合理推論。

## 輸出格式
嚴格以下列 JSON schema 回覆，所有 key 必須原封不動（snake_case），禁止新增、刪除或重新命名欄位。所有文字使用繁體中文（ICD-10 代碼除外）。

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
        "test_name": "string",
        "rationale": "string",
        "urgency": "urgent|routine|elective",
        "clinical_reasoning": "string"
      }
    ],
    "treatments": ["string"],
    "medications": ["string"],
    "follow_up": "string",
    "patient_education": ["string"],
    "referrals": ["string"],
    "diagnostic_reasoning": "string"
  },
  "summary": "string",
  "icd10_codes": ["string"],
  "confidence_score": 0.0
}

## 額外限制
- 不可輸出 markdown、程式碼區塊、JSON 以外的任何文字（包含前言、解釋、致謝、致歉）。
- 未提及的物件欄位一律填 null；未提及的 list 欄位請填空陣列 []。不要填「未提及」、「無」、空字串。
- likelihood 只能是 "high"、"moderate"、"low"；urgency 只能是 "urgent"、"routine"、"elective"。拼錯會導致前端顯示異常。
- 所有 list 欄位必須為扁平的字串陣列（除了 differential_diagnoses 與 recommended_tests 是物件陣列）。
"""


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
        self._client = get_openai_client()
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
        language: str | None = None,
    ) -> dict[str, Any]:
        """
        根據對話記錄生成 SOAP 報告

        Args:
            transcript: 對話記錄列表
            patient_info: 病患基本資訊
            chief_complaint: 主訴
            language: session BCP-47 語言碼，決定 SOAP 輸出語言（預設 zh-TW）

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

            # 依 session language 附加輸出語言硬性規定
            # （_SOAP_SYSTEM_PROMPT 原文用繁中撰寫，臨床知識不變；
            # 尾段再疊上當次輸出語言的指示。）
            system_prompt_localized = _SOAP_SYSTEM_PROMPT + get_message(
                "llm.soap_language_instruction", language
            )

            response = await call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt_localized},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                    response_format={"type": "json_object"},
                )
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
