"""單元測試：patient_context.build_patient_info（WS 與 Celery SOAP 的共用 builder）。

守護三個真跑實測抓到的缺陷：
- gender 必須輸出 `male` 而非 `Gender.MALE`（WS 那份漏了 .value）。
- intake 的四類病史必須進 patient_info（Celery 那份只放 name/gender/age，
  害 soap_generator 的四個分支變死碼）。
- `no_family_history` 為 True 要回「無」，讓 LLM 分得清「已表明沒有」與「還沒問」。
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.models.enums import Gender
from app.pipelines.patient_context import (
    build_patient_info,
    calculate_age,
    format_family_history,
    format_jsonb_list,
)


def make_patient(**overrides):
    """最小 patient stub——builder 只用 getattr，不需要真 ORM instance。"""
    attrs = {
        "name": "王大明",
        "gender": Gender.MALE,
        "date_of_birth": date(1958, 3, 12),
        "medical_history": None,
        "current_medications": None,
        "allergies": None,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


# --------------------------------------------------------------------------
# intake 四類都有值
# --------------------------------------------------------------------------


def test_intake_all_four_categories_are_joined():
    """intake 四類都有值 → 四個欄位都正確串接（Celery 路徑原本整組遺失）。"""
    info = build_patient_info(
        make_patient(),
        {
            "medical_history": [
                {"condition": "高血壓", "years_ago": "5"},
                {"condition": "糖尿病"},
            ],
            "current_medications": [
                {"name": "amlodipine 5mg"},
                {"name": "metformin 500mg"},
            ],
            "allergies": [{"allergen": "盤尼西林"}],
            "family_history": [
                {"relation": "父親", "condition": "膀胱癌"},
                {"relation": "母親", "condition": "糖尿病"},
            ],
        },
    )

    assert info["medical_history"] == "高血壓、糖尿病"
    assert info["medications"] == "amlodipine 5mg、metformin 500mg"
    assert info["allergies"] == "盤尼西林"
    # 實測回歸：SOAP 曾寫「未提供」而 intake 明載父親膀胱癌。
    assert info["family_history"] == "父親：膀胱癌、母親：糖尿病"


def test_returns_exactly_the_documented_keys():
    """回傳 key 契約固定，下游 prompt builder 依賴這些 key。

    `intake_fields` 於 2026-07-27 Gate 加入：扁平四欄會 fallback 到 patients 表，
    分不出來源；§3b 安全 gate 只能吃「本次場次 intake」，故另開一個來源標記
    （語意與不變式見本檔末段的 intake_fields 測試群）。
    """
    info = build_patient_info(make_patient(), {})
    assert set(info) == {
        "name",
        "age",
        "gender",
        "medical_history",
        "medications",
        "allergies",
        "intake_fields",
        "family_history",
    }


# --------------------------------------------------------------------------
# no_* 旗標
# --------------------------------------------------------------------------


def test_no_flags_render_none_marker():
    """no_* 旗標為 True → 回「無」，且不得 fallback 到 patients 表的舊資料。"""
    info = build_patient_info(
        make_patient(
            medical_history=[{"condition": "舊資料不該出現"}],
            current_medications=[{"name": "舊藥不該出現"}],
            allergies=[{"allergen": "舊過敏不該出現"}],
        ),
        {
            "no_past_medical_history": True,
            "no_current_medications": True,
            "no_known_allergies": True,
            "no_family_history": True,
        },
    )

    assert info["medical_history"] == "無"
    assert info["medications"] == "無"
    assert info["allergies"] == "無"
    assert info["family_history"] == "無"


def test_no_family_history_flag_beats_stale_list():
    """新增的 no_family_history 旗標優先於清單內容（勾了沒有就是沒有）。"""
    info = build_patient_info(
        make_patient(),
        {"no_family_history": True, "family_history": [{"relation": "父親", "condition": "膀胱癌"}]},
    )
    assert info["family_history"] == "無"


def test_family_history_absent_stays_none_without_flag():
    """沒勾旗標也沒填 → None（呼叫端才會整行不寫，代表「還沒問」）。"""
    info = build_patient_info(make_patient(), {"family_history": []})
    assert info["family_history"] is None


# --------------------------------------------------------------------------
# intake 空 → fallback 到 patients 表
# --------------------------------------------------------------------------


@pytest.mark.parametrize("intake", [None, {}])
def test_empty_intake_falls_back_to_patient_columns(intake):
    """intake 空（None 或 {}）→ fallback 到 patients.* 長期資料。"""
    info = build_patient_info(
        make_patient(
            medical_history=[{"condition": "攝護腺肥大"}],
            current_medications=[{"medication": "tamsulosin"}],
            allergies=[{"allergen": "顯影劑"}],
        ),
        intake,
    )

    assert info["medical_history"] == "攝護腺肥大"
    assert info["medications"] == "tamsulosin"
    assert info["allergies"] == "顯影劑"
    # patients 表沒有 family_history 欄位，無從 fallback。
    assert info["family_history"] is None


def test_intake_values_win_over_patient_columns():
    """intake 有值時蓋過 patients 表（本次問診為準）。"""
    info = build_patient_info(
        make_patient(medical_history=[{"condition": "舊病史"}]),
        {"medical_history": [{"condition": "新病史"}]},
    )
    assert info["medical_history"] == "新病史"


# --------------------------------------------------------------------------
# gender：實測抓到的 Gender.MALE bug
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gender_enum,expected",
    [(Gender.MALE, "male"), (Gender.FEMALE, "female"), (Gender.OTHER, "other")],
)
def test_gender_enum_serialises_to_internal_code(gender_enum, expected):
    """Gender enum member 要輸出內部碼字串，不能是 `Gender.MALE`（Python 3.11+ 實測）。"""
    info = build_patient_info(make_patient(gender=gender_enum), {})
    assert info["gender"] == expected
    assert f"{info['gender']}" == expected
    assert "Gender." not in f"{info['gender']}"


def test_gender_none_stays_none():
    """gender 為 None 時保持 None，不得變成字串 "None"。"""
    info = build_patient_info(make_patient(gender=None), {})
    assert info["gender"] is None


def test_gender_plain_string_passes_through():
    """已是字串（例如非 ORM 來源）時原樣通過。"""
    info = build_patient_info(make_patient(gender="female"), {})
    assert info["gender"] == "female"


# --------------------------------------------------------------------------
# age
# --------------------------------------------------------------------------


def test_age_birthday_already_passed():
    """今年生日已過 → 足歲不減一。"""
    today = date.today()
    dob = date(today.year - 40, 1, 1)
    if (today.month, today.day) < (1, 1):  # pragma: no cover - 不可能成立
        pytest.skip("unreachable")
    assert calculate_age(dob) == 40
    assert build_patient_info(make_patient(date_of_birth=dob), {})["age"] == 40


def test_age_birthday_not_yet_passed():
    """今年生日還沒到 → 足歲減一。"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    dob = date(tomorrow.year - 40, tomorrow.month, tomorrow.day)
    expected = 40 if (today.month, today.day) >= (dob.month, dob.day) else 39
    assert calculate_age(dob) == expected
    # 跨年（12/31 跑測試）時 tomorrow 落在明年，語意仍成立。
    if tomorrow.year == today.year:
        assert expected == 39


def test_age_zero_for_infant_born_this_year():
    """今年出生 → age 為 0（int），不是 None——呼叫端不可用 truthy 判斷。"""
    today = date.today()
    dob = today - timedelta(days=1)
    age = calculate_age(dob)
    assert age == 0
    assert isinstance(age, int)
    info = build_patient_info(make_patient(date_of_birth=dob), {})
    assert info["age"] == 0
    assert info["age"] is not None


def test_age_none_when_no_dob():
    assert calculate_age(None) is None
    assert build_patient_info(make_patient(date_of_birth=None), {})["age"] is None


# --------------------------------------------------------------------------
# patient=None
# --------------------------------------------------------------------------


def test_none_patient_returns_empty_dict():
    """patient 為 None → 回空 dict（不是含 None 值的骨架）。"""
    assert build_patient_info(None, {"medical_history": [{"condition": "高血壓"}]}) == {}
    assert build_patient_info(None, None) == {}


# --------------------------------------------------------------------------
# helper 邊界
# --------------------------------------------------------------------------


def test_format_jsonb_list_key_precedence_and_fallbacks():
    assert format_jsonb_list(None) is None
    assert format_jsonb_list([]) is None
    assert format_jsonb_list([{"name": "a"}, {"medication": "b"}]) == "a、b"
    assert format_jsonb_list([{"condition": "c"}, {"allergen": "d"}]) == "c、d"
    assert format_jsonb_list(["純字串", 5]) == "純字串、5"
    # 非 list 的 JSONB（例如舊資料存字串）不得炸掉。
    assert format_jsonb_list("高血壓") == "高血壓"


def test_format_family_history_edge_cases():
    assert format_family_history(None) is None
    assert format_family_history([]) is None
    # 非 list 一律 None（原邏輯刻意如此，家族史只接受清單）。
    assert format_family_history("父親：膀胱癌") is None
    # 只有 condition 沒有 relation → 只寫病名。
    assert format_family_history([{"condition": "膀胱癌"}]) == "膀胱癌"
    # 只有 relation 沒有 condition → 整筆略過。
    assert format_family_history([{"relation": "父親"}]) is None
    assert (
        format_family_history([{"relation": "父親"}, {"relation": "母親", "condition": "糖尿病"}])
        == "母親：糖尿病"
    )


# ══════════════════════════════════════════════════════════════════════
# `intake_fields` 來源標記（§3b 安全 gate 的地基）
#
# 2026-07-27 Gate 補上。§3b「關鍵風險因子必問」是安全不變式，**不能**被
# `patients` 表上幾個月前的舊資料關掉。扁平的 medical_history / medications /
# allergies 四欄為了餵 prompt，在本次 intake 空白時會 fallback 到 patients 表，
# 所以扁平值分不出來源；`intake_fields` 是唯一可信的「本次場次填了什麼」。
# llm_conversation.session_intake_fields() 完全建立在這個語意上。
# ══════════════════════════════════════════════════════════════════════


def _patient_with_long_term_record():
    """patients 表上有長期資料的舊病患（建檔於數月前）。"""
    return SimpleNamespace(
        name="王小明",
        date_of_birth=date(1980, 1, 1),
        gender=Gender.MALE,
        medical_history=["高血壓"],
        current_medications=["aspirin"],
        allergies=["penicillin"],
        family_history=[{"relation": "父親", "condition": "膀胱癌"}],
    )


def test_intake_fields_excludes_patient_table_fallback():
    """本次 intake 全空時 `intake_fields` 四欄必須全是 None——即使 patients 表有值。

    這是 §3b 安全 gate 的核心前提：一旦這裡混入 patients 表 fallback，
    「抗凝血劑使用」等必問項就會被舊病歷靜默關掉，AI 全程不會口頭確認一次。
    """
    info = build_patient_info(_patient_with_long_term_record(), None)

    # 扁平欄位**會**（也應該）fallback 到 patients 表——那是餵 prompt 用的。
    assert info["medical_history"] == "高血壓"
    assert info["medications"] == "aspirin"
    assert info["allergies"] == "penicillin"

    # 但來源標記**不得**帶上任何 patients 表的值。
    assert info["intake_fields"] == {
        "medical_history": None,
        "medications": None,
        "allergies": None,
        "family_history": None,
    }


def test_intake_fields_reflects_only_this_session_values():
    """本次 intake 有填的欄位才出現在 `intake_fields`，值＝本次填的那個。"""
    info = build_patient_info(
        _patient_with_long_term_record(),
        {"current_medications": ["amlodipine"]},
    )
    # 本次只填了用藥 → 只有這一欄可證明來源，且值是本次的 amlodipine
    # （**不是** patients 表的 aspirin）。
    assert info["intake_fields"]["medications"] == "amlodipine"
    assert info["intake_fields"]["medical_history"] is None
    assert info["intake_fields"]["allergies"] is None


def test_intake_fields_records_explicit_no_flags():
    """`no_*` 旗標為 True → 「無」，讓 §3b 判得出「已問到、答案為否」。"""
    info = build_patient_info(
        _patient_with_long_term_record(),
        {
            "no_past_medical_history": True,
            "no_known_allergies": True,
            "no_family_history": True,
        },
    )
    assert info["intake_fields"]["medical_history"] == "無"
    assert info["intake_fields"]["allergies"] == "無"
    assert info["intake_fields"]["family_history"] == "無"
    # 用藥沒填也沒勾「無」→ 仍是未知。
    assert info["intake_fields"]["medications"] is None


def test_intake_fields_key_matches_llm_conversation_contract():
    """key 名稱必須等於 llm_conversation.INTAKE_SOURCE_KEY（跨檔契約）。"""
    from app.pipelines.llm_conversation import INTAKE_SOURCE_KEY, session_intake_fields

    info = build_patient_info(_patient_with_long_term_record(), None)
    assert INTAKE_SOURCE_KEY in info

    # 端到端：舊病歷有 aspirin，本次 intake 全空 → gating 看不到任何值。
    assert session_intake_fields(info) == {}

    # 本次真的填了 → gating 看得到。
    info2 = build_patient_info(
        _patient_with_long_term_record(), {"current_medications": ["aspirin"]}
    )
    assert session_intake_fields(info2) == {"medications": "aspirin"}


def test_intake_fields_absent_patient_returns_empty_dict():
    """patient=None 回空 dict（不得冒出半個 intake_fields 讓下游誤判）。"""
    assert build_patient_info(None, {"current_medications": ["aspirin"]}) == {}
