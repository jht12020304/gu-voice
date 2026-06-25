"""
安全硬規則守護：SOAPGenerator._enforce_red_flag_urgency

背景：RedFlagDetector 即時偵測到的 critical/high 紅旗會持久化到
red_flag_alerts，但 SOAP 由 LLM 自逐字稿重新推導，曾發生 critical
(urosepsis) 卻只給 plan.urgency=24h 的 under-triage。此測試鎖住
deterministic「只升不降」(monotonic escalation) 行為。
"""

from __future__ import annotations

from app.pipelines.soap_generator import SOAPGenerator


def _report(urgency: str, tests_urgency=None, impression="患者可能患有腎盂腎炎。"):
    tests = []
    if tests_urgency:
        tests = [{"test_name": "尿液分析", "urgency": u} for u in tests_urgency]
    return {
        "assessment": {"clinical_impression": impression},
        "plan": {"urgency": urgency, "recommended_tests": tests},
    }


def test_critical_forces_er_now():
    """critical 紅旗 → plan.urgency 必須升到 er_now（under-triage 修補核心）。"""
    rep = _report("24h", tests_urgency=["this_week", "24h"])
    rf = [{"severity": "critical", "canonical_id": "urosepsis"}]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, rf, "zh-TW")
    assert out["plan"]["urgency"] == "er_now"
    # recommended_tests 各項也提升至 er_now（消除整體急但檢查緩的矛盾）
    assert all(t["urgency"] == "er_now" for t in out["plan"]["recommended_tests"])
    # clinical_impression 開頭補上紅旗標註
    assert out["assessment"]["clinical_impression"].startswith("⚠")
    assert "urosepsis" in out["assessment"]["clinical_impression"]


def test_high_forces_at_least_24h():
    """high 紅旗 → plan.urgency 至少 24h（routine/this_week 應被提升）。"""
    rep = _report("this_week")
    rf = [{"severity": "high", "canonical_id": "gross_hematuria"}]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, rf, "zh-TW")
    assert out["plan"]["urgency"] == "24h"


def test_monotonic_never_downgrades():
    """已是 er_now，high 紅旗不得把它下調（只升不降）。"""
    rep = _report("er_now")
    rf = [{"severity": "high", "canonical_id": "gross_hematuria"}]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, rf, "zh-TW")
    assert out["plan"]["urgency"] == "er_now"


def test_no_red_flags_leaves_report_untouched():
    """無紅旗 → 完全不動（保護非紅旗案不被誤升級）。"""
    rep = _report("this_week", tests_urgency=["routine"])
    before_impression = rep["assessment"]["clinical_impression"]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, [], "zh-TW")
    assert out["plan"]["urgency"] == "this_week"
    assert out["plan"]["recommended_tests"][0]["urgency"] == "routine"
    assert out["assessment"]["clinical_impression"] == before_impression
    # None 也安全
    assert SOAPGenerator._enforce_red_flag_urgency(rep, None, "zh-TW") is rep


def test_highest_severity_wins_with_mixed_flags():
    """混合嚴重度時取最高（critical > high）→ er_now。"""
    rep = _report("routine")
    rf = [
        {"severity": "high", "canonical_id": "gross_hematuria"},
        {"severity": "critical", "canonical_id": "urinary_retention"},
        {"severity": "medium", "canonical_id": "weight_loss"},
    ]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, rf, "zh-TW")
    assert out["plan"]["urgency"] == "er_now"


def test_impression_not_double_tagged():
    """clinical_impression 已含 ⚠ 標記時不重複加註。"""
    rep = _report("er_now", impression="⚠️ 已標註的紅旗。患者腎盂腎炎。")
    rf = [{"severity": "critical", "canonical_id": "urosepsis"}]
    out = SOAPGenerator._enforce_red_flag_urgency(rep, rf, "zh-TW")
    # 只有一個 ⚠（沒有被加第二次）
    assert out["assessment"]["clinical_impression"].count("⚠") == 1
