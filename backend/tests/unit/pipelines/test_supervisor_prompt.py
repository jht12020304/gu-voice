"""
Unit tests for backend/app/pipelines/supervisor.py SUPERVISOR_SYSTEM_PROMPT

守護 supervisor prompt 與共用 shared.py ontology 的一致性:
- HPI 十欄必須渲染進 prompt(避免 supervisor 與 SOAP schema 脫鉤)
- missing_hpi 合法值必須對齊 HPI_FIELD_IDS
- 單問題硬性規則必須存在(P0-A)
"""

from app.pipelines.supervisor import SUPERVISOR_SYSTEM_PROMPT
from app.pipelines.prompts.shared import HPI_FIELD_IDS, HPI_STEPS, SINGLE_QUESTION_RULE
from app.pipelines.prompts.shared import CORE_HPI_PRIORITY_RULE


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


def test_supervisor_prompt_treats_dont_know_as_collected():
    """#2:病患表示不知道的欄位必須視為已盡力採集(missing_hpi 移除、next_focus 不再指向)。"""
    assert "已盡力採集" in SUPERVISOR_SYSTEM_PROMPT
    assert "不知道" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_prompt_forbids_rephrase_reask():
    """換句話重問必須被明文禁止,否則 don't-know 欄位仍會被換方法追問。"""
    assert "換句話" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_prompt_dont_know_does_not_lower_completion():
    """don't-know 不可壓低 hpi_completion_percentage,否則軟收尾門檻(>=80)永不觸發。"""
    assert "不因此壓低" in SUPERVISOR_SYSTEM_PROMPT


def test_missing_core_hpi_precedes_optional_history_without_skipping_risk():
    from app.core.config import Settings
    from app.pipelines.llm_conversation import LLMConversationEngine
    prompt = LLMConversationEngine(Settings()).build_system_prompt("頻尿", {}, "zh-TW")
    assert CORE_HPI_PRIORITY_RULE in prompt
    assert CORE_HPI_PRIORITY_RULE in SUPERVISOR_SYSTEM_PROMPT
    assert "依上方 HPI 框架順序優先補齊 missing_hpi" in SUPERVISOR_SYSTEM_PROMPT
    assert "除急症線索及本主訴必問風險因子外" in SUPERVISOR_SYSTEM_PROMPT
    assert "Onset 與 Duration 分開判定" in SUPERVISOR_SYSTEM_PROMPT


def test_literal_placeholder_in_patient_value_is_not_resubstituted():
    """逐次 .replace() 會把病患值裡的字面 "{chief_complaint}" 在第二趟再代換成主訴。"""
    import asyncio
    from types import SimpleNamespace

    from app.core.config import Settings
    from app.pipelines.supervisor import SupervisorEngine

    class _Client:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    class _Redis:
        async def setex(self, *a):  # noqa: ANN001
            return None

    settings = Settings()
    engine = SupervisorEngine(settings)
    assert engine._temperature == settings.OPENAI_TEMPERATURE_SUPERVISOR  # noqa: SLF001
    client = _Client()
    engine._client = client  # noqa: SLF001
    asyncio.run(
        engine.analyze_next_step(
            session_id="sub",
            conversation_history=[{"role": "patient", "content": "會痛"}],
            chief_complaint="血尿",
            patient_info={"age": 60, "gender": "male", "medications": "{chief_complaint}"},
            redis=_Redis(),
            language="zh-TW",
        )
    )
    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "目前用藥（病歷記載，過往）：{chief_complaint}" in system_prompt
    assert "- 主訴:血尿" in system_prompt
