"""
目錄 severity floor 測試（修語意層把 critical 自評降級為 high 躲過 abort）。

安全不變式：命中內建 catalogue 的紅旗，severity = max(LLM 自評, 目錄定義)（只升不降）。
"""

from app.pipelines.red_flag_detector import _floor_severity_to_catalog
from app.pipelines.prompts.shared import URO_RED_FLAGS

_CATALOG = {f["canonical_id"]: f["severity"] for f in URO_RED_FLAGS}


def test_critical_catalog_floors_up_high_llm():
    """testicular_pain_severe 目錄=critical，LLM 自評 high → 升回 critical（實測失效案）。"""
    assert _CATALOG["testicular_pain_severe"] == "critical"
    assert _floor_severity_to_catalog("testicular_pain_severe", "high") == "critical"


def test_no_downgrade_when_llm_higher():
    """LLM 自評高於目錄 → 保留 LLM（只升不降，不下修）。"""
    assert _floor_severity_to_catalog("gross_hematuria", "critical") == "critical"


def test_medium_floors_to_high():
    """gross_hematuria 目錄=high，LLM 自評 medium → 升到 high。"""
    assert _CATALOG["gross_hematuria"] == "high"
    assert _floor_severity_to_catalog("gross_hematuria", "medium") == "high"


def test_equal_severity_unchanged():
    assert _floor_severity_to_catalog("urosepsis", "critical") == "critical"


def test_unknown_canonical_unchanged():
    """LLM 自創紅旗（不在目錄）→ 不動 severity。"""
    assert _floor_severity_to_catalog("some_new_llm_flag", "high") == "high"


def test_all_critical_canonicals_floor_high_to_critical():
    """所有目錄 critical 的紅旗，被自評 high 都要升回 critical（abort 門檻不被躲過）。"""
    for cid, sev in _CATALOG.items():
        if sev == "critical":
            assert _floor_severity_to_catalog(cid, "high") == "critical", cid
