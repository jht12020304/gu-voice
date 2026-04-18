"""
ICD-10 驗證層（TODO-M3）

LLM 產出的 ICD-10 代碼偶爾會 hallucinate 非泌尿科範疇或與主訴無關的碼；
本模組提供兩道防線：

1. 泌尿科白名單 (`UROLOGY_ICD10_WHITELIST`)：
   - 僅保留泌尿相關 ICD-10 前綴（N00–N99 腎泌尿疾病、R30–R39 泌尿症狀、
     C60–C68 泌尿生殖系惡性腫瘤、A54/A56 淋病/披衣菌、N40-N51 男性器官等）。
   - LLM 吐出「J18 肺炎」「I10 高血壓」這類外科無關碼會被 strip。

2. Symptom ↔ ICD 對映 (`icd10_symptom_map.SYMPTOM_TO_ICD10`)：
   - 若本次 session symptom id 有登記，檢查過濾後的每個 code 是否至少有一個
     命中對映表的前綴；全部對不上 → `is_verified=False`。
   - symptom id 不在對映表（或 caller 未傳） → `is_verified=False`（無法確認），
     但過濾後的 codes 仍然回傳。

Public API
----------
- `validate_icd10_codes(codes, symptom_id) -> (filtered_codes, is_verified)`
- `UROLOGY_ICD10_WHITELIST: set[str]`（以 ICD-10 3 位前綴儲存）
"""

from __future__ import annotations

import logging
import re

from app.pipelines.icd10_symptom_map import SYMPTOM_TO_ICD10

logger = logging.getLogger(__name__)


# ── 泌尿科 ICD-10 3 位前綴白名單 ──────────────────────────
# 採「前綴比對」：只要 input code 的前 3 碼（去除 `.` 後）在此 set 內即放行。
# 這樣 N39.0、N20 皆可命中；無需枚舉所有細分碼。
UROLOGY_ICD10_WHITELIST: set[str] = {
    # 腎臟疾病 N00–N19
    "N00",  # 急性腎炎症候群
    "N01",  # 快速進行性腎炎症候群
    "N02",  # 反覆持續血尿
    "N03",  # 慢性腎炎症候群
    "N04",  # 腎病症候群
    "N05",
    "N06",
    "N07",
    "N08",
    "N10",  # 急性腎盂腎炎
    "N11",  # 慢性腎盂腎炎
    "N12",  # 腎盂腎炎 NOS
    "N13",  # 阻塞性與反流性腎病
    "N14",
    "N15",
    "N16",
    "N17",  # 急性腎衰竭
    "N18",  # 慢性腎臟病
    "N19",  # 未特定腎衰竭
    # 泌尿道結石 N20–N23
    "N20",
    "N21",
    "N22",
    "N23",  # 腎絞痛 NOS
    # 腎與輸尿管其他疾患 N25–N29
    "N25",
    "N26",
    "N27",
    "N28",
    "N29",
    # 膀胱與尿道疾患 N30–N39
    "N30",  # 膀胱炎
    "N31",  # 神經性膀胱
    "N32",
    "N33",
    "N34",  # 尿道炎
    "N35",
    "N36",
    "N37",
    "N39",  # UTI NOS、尿失禁
    # 男性生殖器 N40–N51
    "N40",  # BPH
    "N41",  # 攝護腺發炎
    "N42",
    "N43",
    "N44",  # 睪丸扭轉
    "N45",  # 睪丸炎 / 副睪炎
    "N46",  # 男性不孕
    "N47",
    "N48",
    "N49",
    "N50",
    "N51",
    # 泌尿症狀 R30–R39
    "R30",  # 排尿疼痛
    "R31",  # 血尿
    "R32",  # 尿失禁 NOS
    "R33",  # 尿滯留
    "R34",  # 無尿與少尿
    "R35",  # 頻尿 / 夜尿
    "R36",  # 尿道分泌物
    "R37",
    "R39",  # 其他泌尿系統症狀
    # 下腹痛（泌尿相關鑑別）
    "R10",
    # 泌尿生殖系惡性腫瘤 C60–C68
    "C60",  # 陰莖癌
    "C61",  # 攝護腺癌
    "C62",  # 睪丸癌
    "C63",
    "C64",  # 腎癌
    "C65",  # 腎盂癌
    "C66",  # 輸尿管癌
    "C67",  # 膀胱癌
    "C68",  # 其他泌尿器官癌
    # 性傳染病（泌尿門診常見鑑別）
    "A54",  # 淋病
    "A56",  # 披衣菌感染
    # 先天泌尿畸形
    "Q60",
    "Q61",
    "Q62",
    "Q63",
    "Q64",
}


_CODE_PATTERN = re.compile(r"^[A-Z]\d{2}(?:\.\d+[A-Za-z]?)?$")


def _normalize_code(code: str) -> str | None:
    """正規化 ICD-10 code：去空白、轉大寫、校驗格式。不合法回 None。"""
    if not isinstance(code, str):
        return None
    cleaned = code.strip().upper().replace(" ", "")
    if not cleaned:
        return None
    if not _CODE_PATTERN.match(cleaned):
        return None
    return cleaned


def _prefix3(code: str) -> str:
    """取前 3 碼（Letter + 2 digits），供白名單與 symptom map 比對。"""
    return code[:3]


def validate_icd10_codes(
    codes: list[str] | None,
    symptom_id: str | None,
) -> tuple[list[str], bool]:
    """
    驗證並過濾 LLM 產出的 ICD-10 代碼。

    Args:
        codes: LLM 輸出的 ICD-10 代碼清單（可能含 hallucination）。
        symptom_id: 本次 session 對應的 symptom identifier
            （snake_case slug，見 `icd10_symptom_map`）。
            若 None 或未登記於對映表，`is_verified` 必為 False。

    Returns:
        (filtered_codes, is_verified):
            - filtered_codes: 通過白名單過濾後、格式正確的 ICD-10 碼清單
              （保留原大小寫與小數點）。
            - is_verified: True 代表所有 filtered_codes 都與 symptom_id
              對映表匹配；False 代表 symptom 未登記、或至少一個 code
              對不起來、或輸入為空。

    Behavior
    --------
    - 空輸入 (`codes=None` 或 `[]`) → ([], False)。
    - 格式不合法的 code 會被 drop（log debug）。
    - 白名單外的 code 會被 strip（log info）。
    - symptom_id 不在對映表 → 過濾後 codes 照回，但 is_verified=False。
    - 有 symptom 且 codes 全部命中對映表前綴 → is_verified=True。
    """
    if not codes:
        return [], False

    normalized: list[str] = []
    for raw in codes:
        norm = _normalize_code(raw)
        if norm is None:
            logger.debug("icd10_validator: drop invalid code=%r", raw)
            continue
        normalized.append(norm)

    # 白名單過濾
    filtered: list[str] = []
    for code in normalized:
        if _prefix3(code) in UROLOGY_ICD10_WHITELIST:
            filtered.append(code)
        else:
            logger.info(
                "icd10_validator: strip non-urology code=%s (symptom=%s)",
                code,
                symptom_id,
            )

    if not filtered:
        return [], False

    # Symptom 對映驗證
    if not symptom_id:
        return filtered, False
    allowed_prefixes = SYMPTOM_TO_ICD10.get(symptom_id)
    if not allowed_prefixes:
        logger.debug(
            "icd10_validator: symptom_id=%r not registered in SYMPTOM_TO_ICD10",
            symptom_id,
        )
        return filtered, False

    allowed_set = {p.upper() for p in allowed_prefixes}
    all_match = all(_prefix3(code) in allowed_set for code in filtered)
    return filtered, bool(all_match)


__all__ = [
    "UROLOGY_ICD10_WHITELIST",
    "validate_icd10_codes",
]
