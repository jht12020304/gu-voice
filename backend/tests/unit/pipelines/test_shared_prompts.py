"""
Unit tests for backend/app/pipelines/prompts/shared.py

這些測試守護四個 pipeline 依賴的 ontology 不變式:
- HPI 十欄順序與 id 命名
- 紅旗清單完整且 title 與 fallback rules 對齊
- render_* 函式輸出可被 prompt 安全嵌入
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


# =============================================================================
# HPI 框架
# =============================================================================


def test_hpi_has_exactly_10_steps():
    """SOAP schema 依賴 hpi 子欄位為 10 個;少一個就會造成斷鏈。"""
    assert len(HPI_STEPS) == 10


def test_hpi_field_ids_are_snake_case_and_unique():
    """所有 id 必須是 snake_case 字串、互相唯一,且與 SOAP hpi schema 對齊。"""
    assert len(HPI_FIELD_IDS) == 10
    assert len(set(HPI_FIELD_IDS)) == 10  # unique
    for fid in HPI_FIELD_IDS:
        assert fid.islower()
        assert " " not in fid
        assert fid == fid.strip()


def test_hpi_field_ids_match_soap_schema():
    """
    硬性對齊:這 10 個 id 必須與 soap_generator._validate_and_fill
    中的 hpi_fields 列表一致。修改 HPI_STEPS 時必須同步檢查 SOAP validator。
    """
    expected = {
        "onset",
        "location",
        "duration",
        "characteristics",
        "severity",
        "aggravating_factors",
        "relieving_factors",
        "associated_symptoms",
        "timing",
        "context",
    }
    assert set(HPI_FIELD_IDS) == expected


def test_render_hpi_checklist_numbered_and_complete():
    """渲染後每一步都應有 1-indexed 編號與中文名稱。"""
    rendered = render_hpi_checklist()
    for i, step in enumerate(HPI_STEPS, start=1):
        assert f"{i}. " in rendered
        assert step["zh"] in rendered
        assert step["desc"] in rendered


# =============================================================================
# 紅旗清單
# =============================================================================


def test_uro_red_flags_core_titles_present():
    """
    Red flag detector 的 fallback rules 與 prompt 都假設這 7 個內建 title 存在。
    新增紅旗可以,但這 7 個不可刪除或改名(會破壞規則層/語意層去重合併)。
    """
    core_titles = {
        "急性尿滯留",
        "大量血尿",
        "睪丸劇痛",
        "尿路敗血症",
        "肉眼血尿",
        "腎絞痛合併發燒",
        "不明原因體重下降",
    }
    actual_titles = {f["title"] for f in URO_RED_FLAGS}
    missing = core_titles - actual_titles
    assert not missing, f"缺少核心紅旗 title: {missing}"


def test_uro_red_flags_have_required_fields():
    """每一筆紅旗必須有完整欄位,否則 render_* 函式會拋 KeyError。"""
    required = {
        "title",
        "severity",
        "description",
        "triggers",
        "related_complaints",
        "suggested_actions",
    }
    for flag in URO_RED_FLAGS:
        missing = required - set(flag.keys())
        assert not missing, f"紅旗 {flag.get('title')} 缺少欄位: {missing}"


def test_uro_red_flags_severity_enum():
    """severity 必須是 critical/high/medium 其中之一(red flag detector 硬性限制)。"""
    allowed = {"critical", "high", "medium"}
    for flag in URO_RED_FLAGS:
        assert flag["severity"] in allowed, (
            f"{flag['title']} severity 違規: {flag['severity']}"
        )


def test_uro_red_flags_titles_unique():
    """title 是 _merge_and_deduplicate 的 key,若重複會撞在一起。"""
    titles = [f["title"] for f in URO_RED_FLAGS]
    assert len(titles) == len(set(titles)), "URO_RED_FLAGS 有重複 title"


def test_uro_red_flags_triggers_and_actions_are_lists():
    """triggers 與 suggested_actions 必須是 list[str],否則 set() 合併會炸。"""
    for flag in URO_RED_FLAGS:
        assert isinstance(flag["triggers"], list)
        assert isinstance(flag["suggested_actions"], list)
        assert all(isinstance(t, str) for t in flag["triggers"])
        assert all(isinstance(a, str) for a in flag["suggested_actions"])


# =============================================================================
# 紅旗過濾與渲染
# =============================================================================


def test_get_red_flags_for_complaint_filters_hematuria():
    """血尿主訴應包含『大量血尿』與『肉眼血尿』。"""
    flags = get_red_flags_for_complaint("血尿持續三天")
    titles = {f["title"] for f in flags}
    assert "大量血尿" in titles
    assert "肉眼血尿" in titles
    # 不應包含純腰痛類的紅旗(這些 related_complaints 只有「腰痛」)
    assert "腎絞痛合併發燒" not in titles


def test_get_red_flags_for_complaint_filters_back_pain():
    """腰痛主訴應包含『腎絞痛合併發燒』。"""
    flags = get_red_flags_for_complaint("左側腰痛一週")
    titles = {f["title"] for f in flags}
    assert "腎絞痛合併發燒" in titles


def test_get_red_flags_for_complaint_empty_returns_all():
    """空字串或無匹配主訴應回傳全部紅旗,避免漏報。"""
    all_count = len(URO_RED_FLAGS)
    assert len(get_red_flags_for_complaint("")) == all_count
    assert len(get_red_flags_for_complaint("牙痛")) == all_count  # 無泌尿相關


def test_render_red_flag_titles_for_prompt_contains_all():
    """Prompt 中的 title 對齊段落必須含所有紅旗 title。"""
    rendered = render_red_flag_titles_for_prompt()
    for flag in URO_RED_FLAGS:
        assert f"「{flag['title']}」" in rendered


def test_render_red_flags_by_severity_has_three_buckets():
    """輸出應包含 Critical / High 至少兩個段落(medium 可能為空)。"""
    rendered = render_red_flags_by_severity()
    assert "### Critical" in rendered
    assert "### High" in rendered
    # 所有 critical / high 紅旗 title 都要出現在輸出中
    for flag in URO_RED_FLAGS:
        if flag["severity"] in ("critical", "high"):
            assert flag["title"] in rendered


def test_render_red_flags_for_conversation_per_complaint():
    """主訴篩選後,conversation 提醒段落應只含相關紅旗。"""
    rendered = render_red_flags_for_conversation("睪丸疼痛兩天")
    assert "睪丸劇痛" in rendered
    # 腎絞痛只關聯腰痛,不應出現
    assert "腎絞痛合併發燒" not in rendered


# =============================================================================
# 跨 pipeline 輸出規則
# =============================================================================


def test_single_question_rule_non_empty():
    """SINGLE_QUESTION_RULE 是 conversation + supervisor 共用,不能為空。"""
    assert SINGLE_QUESTION_RULE.strip() != ""
    assert "一次只追問一個問題" in SINGLE_QUESTION_RULE
