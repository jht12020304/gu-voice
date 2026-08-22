"""sampling_kwargs／is_reasoning_model（2026-08-22 gpt-5.6 換代）。

取樣參數的相容性是模型家族的屬性：gpt-5.x／o 系列拒收非預設 temperature
（實測 400「Only the default (1) value is supported」）、接受 reasoning_effort
（含字面值 "none"＝關 CoT）；gpt-4o／gpt-4.1 相反。歷史上各管線用
config=="none" 的字串約定判斷，而 SOAP／紅旗根本沒有那個分支——無條件送
temperature，一換 5.6 就整條 400。這裡釘住集中後的行為。
"""

import pytest

from app.core.openai_client import is_reasoning_model, sampling_kwargs


class TestFamilyDetection:
    @pytest.mark.parametrize("m", [
        "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol",
        "gpt-5.4-mini", "gpt-5-nano", "o1-pro", "o3-mini", "o4-mini",
    ])
    def test_reasoning_family(self, m):
        assert is_reasoning_model(m) is True

    @pytest.mark.parametrize("m", ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-nano", "gpt-3.5-turbo"])
    def test_traditional_family(self, m):
        assert is_reasoning_model(m) is False

    def test_none_and_empty_are_traditional(self):
        # 防禦：模型名缺失時走傳統路徑（送 temperature），至少不會送出
        # 傳統模型不認識的 reasoning_effort。
        assert is_reasoning_model("") is False
        assert is_reasoning_model(None) is False


class TestKwargs:
    def test_reasoning_model_gets_effort_never_temperature(self):
        kw = sampling_kwargs("gpt-5.6-luna", effort="medium", temperature=0.7)
        assert kw == {"reasoning_effort": "medium"}

    def test_effort_none_is_sent_not_dropped(self):
        # "none" 是合法 API 值（關 CoT），不是「不送參數」。不送的話模型會用
        # 預設 effort 燒 reasoning token，對話延遲直接翻倍。
        kw = sampling_kwargs("gpt-5.6-luna", effort="none", temperature=0.7)
        assert kw == {"reasoning_effort": "none"}

    def test_missing_effort_defaults_to_none(self):
        assert sampling_kwargs("gpt-5.6-terra", effort=None, temperature=0.3) == {
            "reasoning_effort": "none"
        }
        assert sampling_kwargs("gpt-5.6-terra", effort="", temperature=0.3) == {
            "reasoning_effort": "none"
        }

    def test_traditional_model_gets_temperature_never_effort(self):
        kw = sampling_kwargs("gpt-4o", effort="medium", temperature=0.3)
        assert kw == {"temperature": 0.3}


# ── cache_kwargs（2026-08-22 prompt caching 路由） ─────────


def test_cache_kwargs_builds_extra_body_with_session_key():
    from app.core.openai_client import cache_kwargs

    assert cache_kwargs("abc-123") == {
        "extra_body": {"prompt_cache_key": "sess-abc-123"}
    }


def test_cache_kwargs_empty_for_missing_or_unknown_session():
    from app.core.openai_client import cache_kwargs

    assert cache_kwargs(None) == {}
    assert cache_kwargs("") == {}
    # generate_response 的 session_id 預設佔位字串——所有場次共用 "sess-unknown"
    # 反而把不同前綴路由到同一分片，寧可不帶 key
    assert cache_kwargs("unknown") == {}
