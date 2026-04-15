"""
Unit tests for red_flag_detector's migration to shared.URO_RED_FLAGS (Phase 3).

守護語意層 prompt 與 fallback rules 都是從 shared catalogue 產生,避免
P2-E 漂移:任何新增/刪除 URO_RED_FLAGS 項目必須在兩邊同時生效。
"""

from app.pipelines.red_flag_detector import RedFlagDetector, _SEMANTIC_SYSTEM_PROMPT
from app.pipelines.prompts.shared import URO_RED_FLAGS


def test_fallback_rules_length_matches_shared_catalogue():
    """fallback rules 數量必須等於 URO_RED_FLAGS,否則代表知識庫漂移。"""
    fallback = RedFlagDetector._get_fallback_rules()
    assert len(fallback) == len(URO_RED_FLAGS)


def test_fallback_rules_titles_align_with_shared():
    """fallback.name 必須對齊 URO_RED_FLAGS.title(_merge_and_deduplicate 用 title 當 key)。"""
    fallback = RedFlagDetector._get_fallback_rules()
    fallback_names = {r["name"] for r in fallback}
    catalogue_titles = {f["title"] for f in URO_RED_FLAGS}
    assert fallback_names == catalogue_titles


def test_fallback_rules_preserve_severity_and_keywords():
    """fallback rule 必須攜帶原始 severity 與 triggers 作為 keywords。"""
    fallback_by_name = {r["name"]: r for r in RedFlagDetector._get_fallback_rules()}
    for flag in URO_RED_FLAGS:
        rule = fallback_by_name[flag["title"]]
        assert rule["severity"] == flag["severity"]
        assert rule["keywords"] == list(flag["triggers"])
        assert rule["suggested_actions"] == list(flag["suggested_actions"])


def test_fallback_rules_have_required_fields_for_rule_layer():
    """_rule_based_detect 會讀這些欄位;缺任何一個會 KeyError 或行為異常。"""
    required = {"id", "name", "severity", "keywords", "regex_pattern",
                "description", "suggested_actions"}
    for rule in RedFlagDetector._get_fallback_rules():
        assert required <= set(rule.keys()), f"缺欄位: {required - set(rule.keys())}"


def test_semantic_prompt_contains_all_catalogue_titles():
    """所有 URO_RED_FLAGS.title 都應出現在 prompt 的 title 對齊段落中。"""
    for flag in URO_RED_FLAGS:
        assert flag["title"] in _SEMANTIC_SYSTEM_PROMPT, (
            f"紅旗 title 未出現在 semantic prompt: {flag['title']}"
        )


def test_semantic_prompt_has_three_severity_buckets():
    """prompt 必須渲染出 Critical / High 三層結構(給 LLM 抓分級語境)。"""
    assert "### Critical" in _SEMANTIC_SYSTEM_PROMPT
    assert "### High" in _SEMANTIC_SYSTEM_PROMPT


def test_semantic_prompt_preserves_output_schema_rules():
    """
    原本的 schema 硬性限制(severity enum、suggested_actions list[str]、禁用欄位清單)
    不能被 refactor 弄掉,否則 LLM 輸出會回歸到舊 format 導致後端解析失敗。
    """
    assert "critical" in _SEMANTIC_SYSTEM_PROMPT
    assert "suggested_actions" in _SEMANTIC_SYSTEM_PROMPT
    assert "trigger_reason" in _SEMANTIC_SYSTEM_PROMPT
    assert "alert_type" in _SEMANTIC_SYSTEM_PROMPT  # 在「不可輸出」列表中
