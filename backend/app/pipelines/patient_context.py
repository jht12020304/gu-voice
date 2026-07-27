"""病患背景資訊（patient_info）組裝——WS 對話路徑與 Celery SOAP 路徑的唯一來源。

歷史上這段邏輯有兩份分岔實作：

- `app/websocket/conversation_handler.py` 有完整版（讀 `sessions.intake_data`，
  組出 medical_history / medications / allergies / family_history），但 gender
  直接把 SQLAlchemy `Gender` enum member 塞進 dict，下游 f-string 在 Python 3.11+
  會輸出 `Gender.MALE` 而不是 `male`。
- `app/tasks/report_queue.py` 有殘缺版（只放 name / gender / age），導致
  `app/pipelines/soap_generator.py` 的 past_medical_history / medications /
  allergies / family_history 四個分支在生產路徑是死碼——實測後果是 SOAP 的
  family_history 寫「未提供」，而 intake 明載「父親：膀胱癌」。

本模組把完整版搬過來當單一來源，並修掉 gender 與「家族史為無」兩個實測缺陷。

注意：分隔符「、」與「無」目前是硬寫中文，非中文場次的 prompt 會出現
`Past medical history: 無`。這是已知缺陷，在地化牽涉 i18n 檔，此處刻意維持現狀。
"""

from __future__ import annotations

from datetime import date
from typing import Any

__all__ = [
    "build_patient_info",
    "calculate_age",
    "format_jsonb_list",
    "format_family_history",
]


def calculate_age(dob: date | None) -> int | None:
    """由出生日期算足歲。dob 為 None 時回 None。

    今年出生（生日已過）會回 0——呼叫端不可用 truthy 判斷有無年齡，
    必須用 `is not None`（`llm_conversation.py` 曾因此讓 age==0 整行消失）。
    """
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def format_jsonb_list(items: Any) -> str | None:
    """把 JSONB 清單（病史／用藥／過敏）壓成單行字串，空值回 None。"""
    if not items:
        return None
    if isinstance(items, list):
        parts = []
        for item in items:
            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("medication")
                    or item.get("condition")
                    or item.get("allergen")
                    or str(item)
                )
                parts.append(name)
            else:
                parts.append(str(item))
        return "、".join(parts) if parts else None
    return str(items)


def format_family_history(items: Any) -> str | None:
    """把家族史清單壓成「關係：病名」單行字串，空值回 None。"""
    if not items or not isinstance(items, list):
        return None
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        relation = item.get("relation")
        condition = item.get("condition")
        if relation and condition:
            parts.append(f"{relation}：{condition}")
        elif condition:
            parts.append(str(condition))
    return "、".join(parts) if parts else None


def build_patient_info(patient: Any, intake_data: dict | None) -> dict[str, Any]:
    """組 patient_info。patient 可為 None（回空 dict）。

    回傳 key: name, age, gender, medical_history, medications, allergies, family_history

    四類病史優先取本場次 intake；intake 沒填才 fallback 到 `patients` 表上的長期資料。
    `no_*` 旗標為 True 時明確回「無」，讓 LLM 分得清「已表明沒有」與「還沒問」——
    否則 §3b 必問的泌尿癌家族史會被重問一次（實測）。
    """
    if patient is None:
        return {}

    intake = intake_data or {}

    intake_summary = {
        "medical_history": (
            "無"
            if intake.get("no_past_medical_history")
            else format_jsonb_list(intake.get("medical_history"))
        ),
        "medications": (
            "無"
            if intake.get("no_current_medications")
            else format_jsonb_list(intake.get("current_medications"))
        ),
        "allergies": (
            "無"
            if intake.get("no_known_allergies")
            else format_jsonb_list(intake.get("allergies"))
        ),
        "family_history": (
            "無"
            if intake.get("no_family_history")
            else format_family_history(intake.get("family_history"))
        ),
    }

    # gender 是 SQLAlchemy `Gender` enum member。Python 3.11+ 的 str-Enum
    # f-string 會輸出 `Gender.MALE`，必須取 .value 拿內部碼（male/female/other）。
    gender = getattr(patient, "gender", None)
    gender_value = getattr(gender, "value", gender)

    return {
        "name": getattr(patient, "name", None),
        "age": calculate_age(getattr(patient, "date_of_birth", None)),
        "gender": gender_value,
        "medical_history": intake_summary["medical_history"]
        or format_jsonb_list(getattr(patient, "medical_history", None)),
        "medications": intake_summary["medications"]
        or format_jsonb_list(getattr(patient, "current_medications", None)),
        "allergies": intake_summary["allergies"]
        or format_jsonb_list(getattr(patient, "allergies", None)),
        "family_history": intake_summary["family_history"],
        # 「本次場次 intake 的原值」——**不含** patients 表 fallback。
        # 上面四個扁平欄位為了餵 prompt 會在 intake 空白時 fallback 到 patients
        # 表的長期資料（可能是幾個月前建檔），所以扁平值分不出「這次填的」與
        # 「病歷上本來就有的」。§3b 關鍵風險因子必問是**安全不變式**，不能被舊
        # 資料關掉，因此 llm_conversation.session_intake_fields() 只採信這個子
        # dict。key 名稱＝llm_conversation.INTAKE_SOURCE_KEY。
        # ⚠️ 這裡**只能**放 intake_summary，一旦混入 patients 表 fallback，§3b
        #    的安全 gate 就會被舊病歷靜默關掉（test_patient_context.py 有釘住）。
        "intake_fields": dict(intake_summary),
    }
