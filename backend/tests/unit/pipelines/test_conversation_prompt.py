"""
Unit tests for llm_conversation.build_system_prompt (Phase 2).

守護 conversation prompt 與 shared.py 的對齊:
- HPI 十欄全部渲染(P1-D)
- 次要補問(family/social/RoS)段落存在(P0-B)
- SINGLE_QUESTION_RULE 由 shared 注入,不再寫死在 prompt 裡
- 紅旗段落由 render_red_flags_for_conversation 產生(P2-E)
"""

from app.core.config import Settings
from app.pipelines.llm_conversation import LLMConversationEngine
from app.pipelines.prompts.shared import HPI_STEPS, SINGLE_QUESTION_RULE


def _build(complaint: str = "血尿持續三天", patient: dict | None = None) -> str:
    settings = Settings()
    engine = LLMConversationEngine(settings)
    return engine.build_system_prompt(complaint, patient or {"age": 45, "gender": "male"})


def test_prompt_contains_all_10_hpi_steps():
    """HPI 十欄(含拆分的 Aggravating / Relieving)必須全部渲染。"""
    prompt = _build()
    for step in HPI_STEPS:
        assert step["zh"] in prompt, f"HPI step 缺失: {step['zh']}"


def test_prompt_has_aggravating_and_relieving_separately():
    """
    P1-D 核心修復:舊 prompt 把 Aggravating / Relieving 合併成一步,與
    SOAP hpi schema(10 欄)不對齊;現在應該各自獨立出現。
    """
    prompt = _build()
    assert "Aggravating" in prompt
    assert "Relieving" in prompt


def test_prompt_has_secondary_intake_section():
    """P0-B:SOAP 需要的 family/social/RoS 欄位必須被 conversation 補問。"""
    prompt = _build()
    assert "次要補問" in prompt
    assert "家族" in prompt
    assert "藥物" in prompt


def test_prompt_includes_single_question_rule_from_shared():
    """一次只問一個問題的規則必須由 shared.SINGLE_QUESTION_RULE 注入(避免兩邊漂移)。"""
    prompt = _build()
    assert SINGLE_QUESTION_RULE.strip() in prompt


def test_prompt_red_flags_filtered_by_complaint():
    """血尿主訴只帶入血尿相關紅旗,不應出現純腰痛紅旗。"""
    prompt = _build("血尿持續三天")
    assert "大量血尿" in prompt
    # 腎絞痛合併發燒 related_complaints 只有「腰痛」,血尿主訴不應帶入
    assert "腎絞痛合併發燒" not in prompt


def test_prompt_red_flags_includes_kidney_colic_for_back_pain():
    """腰痛主訴才會出現腎絞痛紅旗。"""
    prompt = _build("左側腰痛一週")
    assert "腎絞痛合併發燒" in prompt


def test_prompt_no_longer_has_hardcoded_red_flags_dict():
    """舊的 RED_FLAGS_BY_COMPLAINT dict 必須已被移除,避免知識庫漂移。"""
    import inspect
    from app.pipelines import llm_conversation
    source = inspect.getsource(llm_conversation)
    assert "RED_FLAGS_BY_COMPLAINT" not in source
    assert "_get_complaint_red_flags" not in source


def test_prompt_patient_info_is_rendered():
    """patient_info 的年齡性別應出現在 prompt 中。"""
    prompt = _build(patient={"age": 62, "gender": "male", "name": "王先生"})
    assert "62" in prompt
    assert "男性" in prompt
