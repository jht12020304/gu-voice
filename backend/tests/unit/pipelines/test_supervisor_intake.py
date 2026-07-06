"""
P0-1 單元測試：Supervisor 餵完整 intake。

守護：
- SUPERVISOR_SYSTEM_PROMPT 含「intake 已提供不重問」護欄。
- build_patient_info_str 會把 intake 已提供的病史/用藥/過敏/家族史帶進背景字串，
  且缺項時不亂塞，age/gender 恆在。
"""

from app.pipelines.supervisor import (
    SUPERVISOR_SYSTEM_PROMPT,
    build_patient_info_str,
)


def test_prompt_has_no_reask_intake_rule():
    """prompt 必須明文禁止 next_focus 重問 intake 已提供項（P0-1 核心護欄）。"""
    assert "intake 已提供" in SUPERVISOR_SYSTEM_PROMPT
    assert "不得" in SUPERVISOR_SYSTEM_PROMPT


def test_patient_info_str_includes_intake_when_present():
    """intake 有值時，四類 intake 欄位都要進背景字串並標註「intake 已提供」。"""
    s = build_patient_info_str(
        {
            "age": 68,
            "gender": "male",
            "medical_history": "高血壓、糖尿病",
            "medications": "amlodipine 5mg",
            "allergies": "盤尼西林",
            "family_history": "父親攝護腺癌",
        }
    )
    assert "年齡：68" in s
    assert "性別：male" in s
    assert "過去病史（intake 已提供）：高血壓、糖尿病" in s
    assert "目前用藥（intake 已提供）：amlodipine 5mg" in s
    assert "過敏史（intake 已提供）：盤尼西林" in s
    assert "家族史（intake 已提供）：父親攝護腺癌" in s


def test_patient_info_str_omits_absent_intake():
    """缺 intake 時只留 age/gender，不塞空的 intake 欄位（避免污染 supervisor 判斷）。"""
    s = build_patient_info_str({"age": 55, "gender": "female"})
    assert "年齡：55" in s
    assert "性別：female" in s
    assert "intake 已提供" not in s


def test_patient_info_str_skips_empty_string_and_none():
    """空字串 / None 的 intake 欄位視為未提供，不進背景字串。"""
    s = build_patient_info_str(
        {
            "age": 40,
            "gender": "male",
            "medical_history": "",
            "medications": None,
            "allergies": "無",  # 有值（病患明確表示無過敏）→ 應保留
            "family_history": "",
        }
    )
    assert "過去病史" not in s
    assert "目前用藥" not in s
    assert "過敏史（intake 已提供）：無" in s
    assert "家族史" not in s


def test_patient_info_str_defaults_when_missing_age_gender():
    """age/gender 缺值時 fallback 「未知」，維持原行為。"""
    s = build_patient_info_str({})
    assert "年齡：未知" in s
    assert "性別：未知" in s
