"""
Unit tests for soap_generator SOAP prompt (Phase 4).

守護 P0-B 收尾:confidence_score 的評分規則必須明確告訴 LLM
不要因 family_history / social_history / review_of_systems 為 null
而壓低分數,否則 Phase 2 擴充進來的補問還是壓不過既有的扣分規則。
"""

from app.pipelines.soap_generator import _SOAP_SYSTEM_PROMPT


def test_confidence_score_rule_exists():
    """confidence_score 段落必須存在。"""
    assert "confidence_score" in _SOAP_SYSTEM_PROMPT


def test_confidence_score_anchored_to_hpi_not_fh_sh_ros():
    """
    confidence_score 評分應明確鎖定 HPI 十欄,而非 family/social/RoS
    (後者在泌尿科門診由醫師現場補問為正常情況)。
    """
    assert "HPI 十欄" in _SOAP_SYSTEM_PROMPT


def test_confidence_score_explicitly_excludes_penalising_fh_sh_ros():
    """必須有明確「不應以此壓低分數」之類的措辭,否則 LLM 仍會保守扣分。"""
    assert "不應以此壓低" in _SOAP_SYSTEM_PROMPT


def test_confidence_score_mentions_fh_sh_ros_by_name():
    """評分規則必須點名三個欄位,避免 LLM 只看籠統描述。"""
    assert "family_history" in _SOAP_SYSTEM_PROMPT
    assert "social_history" in _SOAP_SYSTEM_PROMPT
    assert "review_of_systems" in _SOAP_SYSTEM_PROMPT


# ── §3a：矛盾陳述必須標註 ───────────────────────────────────
# 實測 contradiction 對抗場病患前段「10/10 劇痛、每次血尿」中途翻供「上個月、
# 偶爾、不太痛」,SOAP 只採後段、未標矛盾。強化 prompt 以固定標記強制並列兩版本。


def test_contradiction_fixed_marker_exists():
    """必須使用固定標記「⚠️ 陳述不一致：」,讓醫師端可一眼辨識矛盾。"""
    assert "⚠️ 陳述不一致：" in _SOAP_SYSTEM_PROMPT


def test_contradiction_requires_both_versions():
    """必標且須並列**兩個版本**,不得只採其一。"""
    assert "兩個版本" in _SOAP_SYSTEM_PROMPT
    # 明文禁止靜默覆蓋前段(舊行為:只採後段)
    assert "靜默覆蓋" in _SOAP_SYSTEM_PROMPT


def test_contradiction_is_hard_rule_not_optional():
    """須為硬性規定(『必標』),而非可選提示,否則 LLM 仍會略過。"""
    assert "矛盾陳述必標" in _SOAP_SYSTEM_PROMPT
    # few-shot 範例存在,降低 LLM 誤解(範例引用『10/10』程度描述)。
    assert "10/10" in _SOAP_SYSTEM_PROMPT
