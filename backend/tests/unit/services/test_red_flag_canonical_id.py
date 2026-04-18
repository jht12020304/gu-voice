"""
TODO-E6：紅旗 canonical_id 與多語言 display_title 守護測試。

- URO_RED_FLAGS 每筆 rule 都必須帶 canonical_id + display_title_by_lang
- Dedup 以 canonical_id 為 key,讓 zh 規則層與 en 語意層能正確合併
- Alert serializer 依 language 解析正確 display title(透過
  get_display_title + alert 的 canonical_id)
"""

from __future__ import annotations

from app.pipelines.prompts.shared import (
    URO_RED_FLAGS,
    get_display_title,
    has_locale_coverage,
)
from app.pipelines.red_flag_detector import RedFlagDetector


# ── catalogue 結構守護 ─────────────────────────────────


def test_every_flag_has_canonical_id():
    """URO_RED_FLAGS 每筆都必須有 canonical_id 且為 snake_case 字串。"""
    for flag in URO_RED_FLAGS:
        cid = flag.get("canonical_id")
        assert cid, f"missing canonical_id on flag: {flag.get('title')}"
        assert isinstance(cid, str)
        assert cid == cid.lower(), f"canonical_id not snake_case: {cid}"
        assert " " not in cid, f"canonical_id contains space: {cid}"


def test_canonical_ids_are_unique():
    """canonical_id 必須 globally unique(DB 加 UNIQUE,程式端也不可碰撞)。"""
    ids = [f["canonical_id"] for f in URO_RED_FLAGS]
    assert len(ids) == len(set(ids)), f"duplicate canonical_id detected: {ids}"


def test_every_flag_has_display_title_for_zh_tw_and_en_us():
    """兩個 Phase 1 locale 的 display title 不可缺;否則 alert serializer 會回 fallback。"""
    for flag in URO_RED_FLAGS:
        by_lang = flag.get("display_title_by_lang") or {}
        assert "zh-TW" in by_lang, f"missing zh-TW display for {flag['canonical_id']}"
        assert "en-US" in by_lang, f"missing en-US display for {flag['canonical_id']}"


# ── get_display_title serializer helper ─────────────────


def test_get_display_title_returns_zh_tw_by_default():
    assert get_display_title("gross_hematuria", None) == "肉眼血尿"


def test_get_display_title_returns_en_us_when_language_en_us():
    assert get_display_title("gross_hematuria", "en-US") == "Gross Hematuria"


def test_get_display_title_falls_back_when_language_missing():
    # fr-FR 沒翻譯 → fallback zh-TW
    assert get_display_title("gross_hematuria", "fr-FR") == "肉眼血尿"


def test_get_display_title_unknown_canonical_id_returns_id_itself():
    assert get_display_title("totally_new_flag", "zh-TW") == "totally_new_flag"


# ── has_locale_coverage ─────────────────────────────────


def test_has_locale_coverage_zh_tw_covers_every_catalogue_flag():
    for flag in URO_RED_FLAGS:
        assert has_locale_coverage(flag["canonical_id"], "zh-TW") is True


def test_has_locale_coverage_en_us_covers_every_catalogue_flag():
    # Phase 1:所有 URO_RED_FLAGS 都應該同時具備 zh-TW 與 en-US triggers
    for flag in URO_RED_FLAGS:
        assert has_locale_coverage(flag["canonical_id"], "en-US") is True, (
            f"{flag['canonical_id']} missing en-US coverage"
        )


def test_has_locale_coverage_unknown_language_returns_false():
    # 非 Phase 1 locale(如 fr-FR)預期無 trigger 覆蓋 → fail-safe 觸發 escalation
    assert has_locale_coverage("gross_hematuria", "fr-FR") is False


# ── Dedup 用 canonical_id 為 key ─────────────────────────


def test_merge_uses_canonical_id_across_languages():
    """
    規則層命中 zh-TW title「肉眼血尿」,語意層回 en-US「Gross Hematuria」,
    兩者 canonical_id 相同 → merge 為 combined(只一筆),confidence 升為 rule_hit。
    """
    rule_alerts = [
        {
            "canonical_id": "gross_hematuria",
            "severity": "high",
            "title": "肉眼血尿",
            "description": "",
            "trigger_reason": "關鍵字比對:「血尿」",
            "alert_type": "rule_based",
            "confidence": "rule_hit",
            "suggested_actions": ["安排尿液檢查"],
            "matched_rule_id": None,
        }
    ]
    semantic_alerts = [
        {
            "canonical_id": "gross_hematuria",
            "severity": "high",
            "title": "Gross Hematuria",
            "description": "",
            "trigger_reason": "patient reports red urine",
            "alert_type": "semantic",
            "confidence": "semantic_only",
            "suggested_actions": ["cystoscopy"],
            "matched_rule_id": None,
        }
    ]
    merged = RedFlagDetector._merge_and_deduplicate(
        rule_alerts, semantic_alerts, language="zh-TW"
    )
    assert len(merged) == 1, "cross-language canonical_id should dedup to one alert"
    assert merged[0]["alert_type"] == "combined"
    assert merged[0]["confidence"] == "rule_hit", (
        "combined merge must upgrade confidence back to rule_hit"
    )
    assert merged[0]["canonical_id"] == "gross_hematuria"


def test_merge_falls_back_to_title_when_canonical_id_missing():
    """舊型態 alert(無 canonical_id)仍可用 title dedup。"""
    rule_alerts = [
        {
            "severity": "high",
            "title": "legacy flag",
            "description": "",
            "trigger_reason": "x",
            "alert_type": "rule_based",
            "confidence": "rule_hit",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    semantic_alerts = [
        {
            "severity": "high",
            "title": "Legacy Flag",
            "description": "",
            "trigger_reason": "y",
            "alert_type": "semantic",
            "confidence": "semantic_only",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    merged = RedFlagDetector._merge_and_deduplicate(
        rule_alerts, semantic_alerts, language="zh-TW"
    )
    assert len(merged) == 1
    assert merged[0]["alert_type"] == "combined"


# ── Fallback rules 攜帶 canonical_id ─────────────────────


def test_fallback_rules_carry_canonical_id():
    """_get_fallback_rules() 每條都必須帶 canonical_id,供 rule_based_detect 寫入 alert。"""
    for rule in RedFlagDetector._get_fallback_rules():
        assert rule.get("canonical_id"), f"fallback rule missing canonical_id: {rule}"


def test_fallback_rules_carry_display_title_map():
    """_get_fallback_rules() 每條都必須帶 display_title_by_lang(空 dict 也算合法,但我們預期填齊)。"""
    for rule in RedFlagDetector._get_fallback_rules():
        m = rule.get("display_title_by_lang")
        assert isinstance(m, dict)
        assert "zh-TW" in m and "en-US" in m
