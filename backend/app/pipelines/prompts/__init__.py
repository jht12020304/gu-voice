"""
跨 pipeline 共用的 prompt 常數與 ontology。

此套件是 Single Source of Truth,supervisor / llm_conversation /
soap_generator / red_flag_detector 四個 pipeline 的 HPI 框架、
紅旗清單、以及跨管線輸出規則都從這裡 import,避免知識漂移。
"""

from app.pipelines.prompts.shared import (
    HPI_FIELD_IDS,
    HPI_STEPS,
    SINGLE_QUESTION_RULE,
    URO_RED_FLAGS,
    get_red_flags_for_complaint,
    render_hpi_checklist,
    render_red_flag_titles_for_prompt,
    render_red_flags_by_severity,
    render_red_flags_for_conversation,
)

__all__ = [
    "HPI_STEPS",
    "HPI_FIELD_IDS",
    "URO_RED_FLAGS",
    "SINGLE_QUESTION_RULE",
    "render_hpi_checklist",
    "render_red_flag_titles_for_prompt",
    "render_red_flags_by_severity",
    "render_red_flags_for_conversation",
    "get_red_flags_for_complaint",
]
