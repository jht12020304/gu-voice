"""
Unit tests for §3b 關鍵風險因子提前必問。

守護:
- shared.CRITICAL_RISK_FACTORS 多語主訴匹配(血尿 / PSA / ED)、無關主訴不誤觸
- conversation prompt 對高風險主訴把風險因子提升為「與 HPI 十欄同級必問」
- supervisor analyze_next_step 對高風險主訴加「收尾前必問」gate
- 不破壞 don't-know 不重問 / 每輪一問不變式(措辭斷言)

背景(稽核 §3b):血尿 cooperative 場 5 語言全都沒問吸菸史 / 抗凝血劑 / 泌尿癌家族史,
ED 場多未問心血管風險——根因是這些被歸「次要補問」只在 HPI 十欄達 7 成才問,而
Supervisor 又不因次要未問完壓低完整度 → 核心十欄快填滿就收尾、觸不到。
"""

from app.core.config import Settings
from app.pipelines.llm_conversation import LLMConversationEngine
from app.pipelines.prompts.shared import (
    CRITICAL_RISK_FACTORS,
    get_critical_risk_factors_for_complaint,
    render_critical_risk_factor_items,
)


# ── shared ontology:多語匹配 ───────────────────────────────


def test_hematuria_matches_all_five_languages():
    """chief_complaint 是場次語言在地化字串,5 語都要能匹配到血尿惡性風險群。"""
    for cc in [
        "血尿持續三天",           # zh-TW
        "Hematuria for 3 days",   # en-US
        "血尿が3日続く",          # ja-JP(血尿 同漢字)
        "혈뇨가 3일째",           # ko-KR
        "tiểu ra máu 3 ngày",     # vi-VN
    ]:
        ids = [g["id"] for g in get_critical_risk_factors_for_complaint(cc)]
        assert "hematuria_malignancy" in ids, f"未匹配到血尿風險群: {cc}"


def test_psa_matches_malignancy_group():
    """PSA 升高與血尿同群(吸菸 / 泌尿攝護腺癌家族史)。"""
    ids = [g["id"] for g in get_critical_risk_factors_for_complaint("PSA 異常升高")]
    assert "hematuria_malignancy" in ids
    # 大小寫不敏感
    ids2 = [g["id"] for g in get_critical_risk_factors_for_complaint("elevated psa")]
    assert "hematuria_malignancy" in ids2


def test_ed_matches_multilingual():
    for cc in [
        "勃起功能障礙",           # zh-TW
        "Erectile Dysfunction",   # en-US
        "勃起不全",               # ja-JP
        "발기부전",               # ko-KR
        "rối loạn cương dương",   # vi-VN
    ]:
        ids = [g["id"] for g in get_critical_risk_factors_for_complaint(cc)]
        assert "ed_cardiovascular" in ids, f"未匹配到 ED 風險群: {cc}"


def test_unrelated_complaints_no_risk_factors():
    """無關主訴不得誤觸(保守:不把心血管 / 吸菸問題硬塞給不相關主訴)。"""
    for cc in [
        "頻尿",
        "排尿困難",
        "夜尿",
        "尿失禁",
        "攝護腺相關症狀",   # BPH 型,非血尿 / PSA,不應觸發惡性群
        "Frequent Urination",
        "Lower Abdominal Pain",
    ]:
        assert get_critical_risk_factors_for_complaint(cc) == [], f"誤觸: {cc}"


def test_ed_substring_no_false_positive_on_elevated():
    """『elevated』含 'ed' 但不得誤判為 ED 群(關鍵字用 erectile / impotence 非裸 'ed')。"""
    ids = [g["id"] for g in get_critical_risk_factors_for_complaint("elevated PSA level")]
    assert "ed_cardiovascular" not in ids


def test_empty_or_non_str_complaint_safe():
    assert get_critical_risk_factors_for_complaint("") == []
    assert get_critical_risk_factors_for_complaint(None) == []
    # 非字串不炸(比照 get_red_flags_for_complaint 的防禦)
    assert isinstance(get_critical_risk_factors_for_complaint(object()), list)


def test_catalogue_shape():
    """資料結構含必要欄位,避免 render 時 KeyError。"""
    for g in CRITICAL_RISK_FACTORS:
        assert g["id"] and g["complaint_keywords"] and g["factors"]


# ── render items ────────────────────────────────────────────


def test_render_items_hematuria_contains_key_factors():
    items = render_critical_risk_factor_items("血尿持續三天")
    assert "吸菸" in items
    assert "抗凝血" in items
    assert "家族史" in items


def test_render_items_ed_contains_cardiovascular():
    assert "心血管" in render_critical_risk_factor_items("勃起功能障礙")


def test_render_items_empty_for_unrelated():
    assert render_critical_risk_factor_items("頻尿") == ""


# ── conversation prompt 整合 ────────────────────────────────


def _conv_prompt(complaint: str) -> str:
    engine = LLMConversationEngine(Settings())
    return engine.build_system_prompt(complaint, {"age": 60, "gender": "male"})


def test_conversation_hematuria_promotes_risk_factors_to_mandatory():
    prompt = _conv_prompt("血尿持續三天")
    assert "與 HPI 十欄同級" in prompt
    assert "吸菸" in prompt
    assert "抗凝血" in prompt
    assert "家族史" in prompt


def test_conversation_ed_asks_cardiovascular():
    prompt = _conv_prompt("勃起功能障礙")
    assert "心血管" in prompt
    assert "與 HPI 十欄同級" in prompt


def test_conversation_unrelated_no_mandatory_risk_section():
    prompt = _conv_prompt("頻尿")
    assert "本主訴的關鍵風險因子" not in prompt
    # 次要補問段落與其他既有段落仍在(其他主訴行為完全不變)
    assert "次要補問" in prompt
    assert "HPI 十欄框架" in prompt


def test_conversation_risk_section_preserves_invariants():
    """必問段落必須保留 don't-know 不重問 + 每輪一問不變式的措辭。"""
    prompt = _conv_prompt("血尿持續三天")
    assert "不知道" in prompt           # don't-know 視為已問到
    assert "每輪仍只問一題" in prompt   # 每輪一問
    assert "不得換句話" in prompt       # 不重問


# ── supervisor gate 整合 ────────────────────────────────────


def test_supervisor_wires_risk_factor_gate():
    """analyze_next_step 對高風險主訴附加『收尾前必問』gate(原始碼引用守護)。

    analyze_next_step 為 async + 依賴 OpenAI/Redis,不易直接單元測試;此處以
    inspect.getsource 守護關鍵 gate 措辭與對共用 render 的呼叫,確保:
    - 完整度在風險因子問到前不得評 80 以上(gate);
    - 與 don't-know 不變式一致(已盡力採集不再壓低 / 不再指向)。
    """
    import inspect

    from app.pipelines import supervisor

    src = inspect.getsource(supervisor.SupervisorEngine.analyze_next_step)
    assert "render_critical_risk_factor_items" in src
    assert "不得評為 80 以上" in src
    assert "已盡力採集" in src
