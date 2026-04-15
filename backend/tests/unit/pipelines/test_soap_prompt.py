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
