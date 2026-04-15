"""
Unit tests for backend/app/pipelines/supervisor.py SUPERVISOR_SYSTEM_PROMPT

守護 supervisor prompt 與共用 shared.py ontology 的一致性:
- HPI 十欄必須渲染進 prompt(避免 supervisor 與 SOAP schema 脫鉤)
- missing_hpi 合法值必須對齊 HPI_FIELD_IDS
- 單問題硬性規則必須存在(P0-A)
"""

from app.pipelines.supervisor import SUPERVISOR_SYSTEM_PROMPT
from app.pipelines.prompts.shared import HPI_FIELD_IDS, HPI_STEPS, SINGLE_QUESTION_RULE


def test_supervisor_prompt_renders_all_hpi_steps():
    """HPI 十欄的中文名稱都必須出現在 prompt 中,否則 supervisor 追問會漏項。"""
    for step in HPI_STEPS:
        assert step["zh"] in SUPERVISOR_SYSTEM_PROMPT, f"HPI step 缺失: {step['zh']}"


def test_supervisor_prompt_lists_all_missing_hpi_ids():
    """missing_hpi 的 enum 必須對齊 HPI_FIELD_IDS,否則 supervisor 回傳的 id 會無效。"""
    for fid in HPI_FIELD_IDS:
        assert fid in SUPERVISOR_SYSTEM_PROMPT, f"HPI id 缺失: {fid}"


def test_supervisor_prompt_contains_single_question_rule():
    """SINGLE_QUESTION_RULE 必須嵌入,避免 next_focus 塞多問題違反 P0-A。"""
    assert SINGLE_QUESTION_RULE.strip() in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_prompt_has_single_question_hard_rule():
    """next_focus 的「只能是一個問題」硬性規則必須存在(P0-A 核心修復)。"""
    assert "只能是一個問題" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_prompt_has_length_limit():
    """next_focus 最大長度限制必須明示,避免 supervisor 產出長指令撐爆下一輪 prompt。"""
    assert "60" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_prompt_has_dynamic_placeholders():
    """patient_info_str 與 chief_complaint 必須仍是 placeholder,等 .replace() 注入。"""
    assert "{patient_info_str}" in SUPERVISOR_SYSTEM_PROMPT
    assert "{chief_complaint}" in SUPERVISOR_SYSTEM_PROMPT
