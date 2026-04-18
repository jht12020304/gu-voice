"""
Unit tests for `app.pipelines.icd10_validator` (TODO-M3)。

覆蓋情境：
- 空輸入 / None 輸入
- 非白名單代碼會被 strip
- 格式不合法代碼會被 strip
- symptom_id 不在 map → verified=False，但 codes 仍通過白名單
- symptom_id 有登記且全部 codes 命中 → verified=True
- symptom_id 有登記但部分 codes 對不起來 → verified=False
- 前綴比對（N39.0 vs N39）
- 大小寫 / 空白正規化
- 全部非白名單 → 回空 list + verified=False
- 多 code 混合（合法 + 白名單外 + 不合法）
"""

from __future__ import annotations

import pytest

from app.pipelines.icd10_symptom_map import SYMPTOM_TO_ICD10
from app.pipelines.icd10_validator import (
    UROLOGY_ICD10_WHITELIST,
    validate_icd10_codes,
)


# ── 白名單 / 對映表 sanity ─────────────────────────────────


def test_whitelist_has_at_least_20_entries():
    """驗收條件：白名單至少涵蓋 20 個 ICD-10 前綴。"""
    assert len(UROLOGY_ICD10_WHITELIST) >= 20


def test_symptom_map_has_at_least_10_entries():
    """驗收條件：symptom↔ICD 對映表至少 10 個 entry。"""
    assert len(SYMPTOM_TO_ICD10) >= 10


def test_symptom_map_values_are_within_whitelist():
    """symptom map 裡登記的每個前綴都應在白名單，才不會自相矛盾。"""
    for symptom, prefixes in SYMPTOM_TO_ICD10.items():
        for p in prefixes:
            assert p in UROLOGY_ICD10_WHITELIST, (
                f"symptom {symptom!r} 的前綴 {p!r} 不在 UROLOGY_ICD10_WHITELIST"
            )


# ── validate_icd10_codes 行為 ───────────────────────────────


def test_empty_codes_returns_empty_and_false():
    assert validate_icd10_codes([], "hematuria") == ([], False)
    assert validate_icd10_codes(None, "hematuria") == ([], False)


def test_strip_non_whitelisted_codes():
    """非泌尿科碼（J18 肺炎、I10 高血壓）必須被 strip。"""
    codes, verified = validate_icd10_codes(
        ["J18.9", "I10", "N39.0"], symptom_id="uti"
    )
    assert codes == ["N39.0"]
    assert verified is True  # uti 對映含 N39


def test_all_non_whitelisted_returns_empty_and_false():
    codes, verified = validate_icd10_codes(
        ["J18", "I10", "K35"], symptom_id="hematuria"
    )
    assert codes == []
    assert verified is False


def test_invalid_format_codes_are_dropped():
    """格式錯誤（小寫無 letter prefix、非法字元）會被 drop。"""
    codes, verified = validate_icd10_codes(
        ["not-a-code", "123", "", "N20"], symptom_id="renal_colic"
    )
    assert codes == ["N20"]
    assert verified is True


def test_mismatch_symptom_returns_false():
    """codes 在白名單但與 symptom 對不起來 → verified=False。"""
    # `hematuria` map 只有 R31 / N02；給它 N40（BPH）應 mismatch
    codes, verified = validate_icd10_codes(
        ["N40"], symptom_id="hematuria"
    )
    assert codes == ["N40"]
    assert verified is False


def test_partial_mismatch_symptom_returns_false():
    """只要有一個 code 對不起來就 verified=False。"""
    codes, verified = validate_icd10_codes(
        ["R31", "N40"], symptom_id="hematuria"
    )
    assert codes == ["R31", "N40"]
    assert verified is False


def test_symptom_not_registered_returns_filtered_and_false():
    """symptom 不在 map → codes 照回（過濾後），verified=False。"""
    codes, verified = validate_icd10_codes(
        ["N39.0"], symptom_id="something_not_registered"
    )
    assert codes == ["N39.0"]
    assert verified is False


def test_symptom_id_none_returns_filtered_and_false():
    codes, verified = validate_icd10_codes(["N39.0"], symptom_id=None)
    assert codes == ["N39.0"]
    assert verified is False


def test_prefix_match_allows_subdivision_codes():
    """N39.0 前綴 N39 在對映表 → 應命中。"""
    codes, verified = validate_icd10_codes(["N39.0"], symptom_id="uti")
    assert codes == ["N39.0"]
    assert verified is True


def test_case_and_whitespace_normalization():
    """小寫與多餘空白會被正規化。"""
    codes, verified = validate_icd10_codes(
        ["  n20 ", "n23.1"], symptom_id="renal_colic"
    )
    assert codes == ["N20", "N23.1"]
    assert verified is True


def test_mixed_valid_invalid_and_outside_whitelist():
    """驗證綜合情境：合法白名單碼保留、其餘 strip。"""
    codes, verified = validate_icd10_codes(
        ["N20", "J18.9", "invalid", "C64"], symptom_id="flank_pain"
    )
    # flank_pain map = [N20, N23, R10] → C64 不在 → verified=False
    assert codes == ["N20", "C64"]
    assert verified is False


def test_all_match_returns_true():
    codes, verified = validate_icd10_codes(
        ["N20", "N23"], symptom_id="renal_colic"
    )
    assert codes == ["N20", "N23"]
    assert verified is True


@pytest.mark.parametrize(
    "symptom,good_code",
    [
        ("dysuria", "R30"),
        ("frequency", "R35"),
        ("hematuria", "R31"),
        ("prostate_issue", "N40"),
        ("pyelonephritis", "N10"),
        ("scrotal_pain", "N45"),
    ],
)
def test_each_registered_symptom_accepts_its_core_code(symptom, good_code):
    codes, verified = validate_icd10_codes([good_code], symptom_id=symptom)
    assert codes == [good_code]
    assert verified is True
