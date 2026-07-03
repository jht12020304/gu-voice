"""
ICD-10 ↔ 症狀對映表（M3）

Purpose
-------
供 `icd10_validator.validate_icd10_codes()` 判斷 LLM 輸出的 ICD-10 代碼
是否與本次 session 的主訴/症狀合理對應。

Design
------
- key 為 snake_case symptom id（通常由 `ChiefComplaint.name_en` 正規化而來，
  亦接受直接使用 UUID string 或常用 slug）。
- value 為該症狀合理的 ICD-10 代碼清單（**僅** 允許白名單子集）。
- 比對採**前綴比對**：若 LLM 輸出 `N39.0` 而對映表登記 `N39`，視為符合。
  理由：LLM 時常會補上 `.0` 細分碼，寫死到 3 位前綴可涵蓋多數泌尿科情境。
- 若 caller 傳入 symptom id 不在表內 → `validate_icd10_codes` 會回 `verified=False`
  但不 strip codes（只是標記未驗證）。
"""

from __future__ import annotations

from typing import Any


# ── 症狀 → 可能 ICD-10 前綴清單 ─────────────────────────────
# 至少 10 個 entry，涵蓋泌尿科常見 chief complaint。
SYMPTOM_TO_ICD10: dict[str, list[str]] = {
    # 排尿困難 / 尿滯留
    "dysuria": ["R30", "N39", "N30"],
    "urinary_retention": ["R33", "N31", "N40"],
    "urinary_difficulty": ["R39", "N40", "N31"],
    # 頻尿 / 夜尿 / 急尿
    "frequency": ["R35", "N32", "N39"],
    "nocturia": ["R35"],
    "urgency": ["R39", "N32"],
    # 尿失禁
    "urinary_incontinence": ["N39", "R32"],
    # 血尿
    "hematuria": ["R31", "N02"],
    # 側腹痛 / 腰痛（結石、腎絞痛）
    "flank_pain": ["N20", "N23", "R10"],
    "renal_colic": ["N20", "N23"],
    # 下腹痛 / 膀胱痛
    "lower_abdominal_pain": ["R10", "N30"],
    # 泌尿道感染
    "uti": ["N39", "N30", "N10"],
    "pyelonephritis": ["N10", "N11", "N12"],
    # 攝護腺相關
    "prostate_issue": ["N40", "N41", "C61"],
    "prostatitis": ["N41"],
    # 陰囊 / 睪丸
    "scrotal_pain": ["N45", "N44"],
    "testicular_pain": ["N45", "N44"],
    # 尿道分泌物 / 性病
    "urethral_discharge": ["N34", "A54", "A56"],
    # 會陰疼痛
    "perineal_pain": ["R10", "N41"],
    # 勃起功能障礙（D6：ED 場次 icd10_codes 曾為空陣列，應接受 N52.x）
    "erectile_dysfunction": ["N52"],
    # PSA 升高（D6：應接受 R97.20）。R97 為 3 碼粗粒度：無法區分
    # R97.20(PSA)/R97.1(CA-125)，E7 決策 4 拍板接受並在此註記。
    "elevated_psa": ["R97"],
}


def resolve_symptom_id(session_obj: Any) -> str | None:
    """
    從 session ORM 物件解析 ICD-10 validator 用的 symptom_id slug（B2 共用：
    Celery `report_queue._async_generate` 與 WS `_generate_soap_report_async` 兩路徑共用）。

    策略：
    1. 優先讀 `chief_complaint.name_en`（英文 slug 最接近 SYMPTOM_TO_ICD10 的 key）。
    2. 退而求其次讀 `chief_complaint.name`（如為中文會 miss，但不 raise）。
    正規化為 snake_case 小寫；若無資料回 None（validator 會視為「未登記」→ unverified）。

    注意：「其他」sentinel 主訴（name_en="Other"）會解析成 "other"，不在對映表內
    → `validate_icd10_codes` 回 `is_verified=False` 但不 strip codes——這是預期的
    graceful 行為，勿為 sentinel 特判。
    """
    cc = getattr(session_obj, "chief_complaint", None)
    if cc is None:
        return None
    raw = getattr(cc, "name_en", None) or getattr(cc, "name", None)
    if not raw:
        return None
    slug = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return slug or None


__all__ = ["SYMPTOM_TO_ICD10", "resolve_symptom_id"]
