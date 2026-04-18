"""守護 `app.utils.localized_field.pick` 的多層 fallback（TODO-A2 / A3）：

    1. by_lang[lang] 命中
    2. by_lang[default_lang] 命中
    3. 任一 non-empty by_lang value（best-effort）
    4. legacy_value
    5. None

任何異常輸入（None / 非 dict / 空 dict）都回 None 或 fallback，不得 raise。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.utils.localized_field import pick


def test_target_language_hits_first():
    by_lang = {"zh-TW": "血尿", "en-US": "Hematuria"}
    assert pick(by_lang, "en-US") == "Hematuria"


def test_falls_back_to_default_language(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "zh-TW")
    by_lang = {"zh-TW": "血尿"}
    # ja-JP 沒有 → 退到 DEFAULT_LANGUAGE (zh-TW)
    assert pick(by_lang, "ja-JP") == "血尿"


def test_falls_back_to_any_non_empty_value():
    """default 也沒有 → 抓任一 non-empty 值，避免回 None。"""
    by_lang = {"en-US": "Hematuria"}
    # target=ja-JP 沒有、default=zh-TW 也沒有 → 抓到 en-US
    assert pick(by_lang, "ja-JP", default_lang="zh-TW") == "Hematuria"


def test_falls_back_to_legacy_when_by_lang_empty():
    assert pick({}, "zh-TW", legacy_value="舊資料") == "舊資料"


def test_returns_none_when_all_missing():
    assert pick(None, "zh-TW") is None
    assert pick({}, "zh-TW") is None
    assert pick({}, "zh-TW", legacy_value=None) is None


def test_empty_string_is_skipped():
    """空字串視為 falsy，繼續往後 fallback。"""
    by_lang = {"zh-TW": "", "en-US": "Hematuria"}
    assert pick(by_lang, "zh-TW") == "Hematuria"


def test_non_dict_by_lang_is_ignored():
    """容錯：legacy row 若 by_lang 被塞成字串 / list 也不能 raise。"""
    assert pick("not-a-dict", "zh-TW", legacy_value="舊") == "舊"  # type: ignore[arg-type]
    assert pick(["zh-TW"], "zh-TW", legacy_value="舊") == "舊"  # type: ignore[arg-type]


def test_none_lang_still_uses_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "en-US")
    by_lang = {"zh-TW": "血尿", "en-US": "Hematuria"}
    assert pick(by_lang, None) == "Hematuria"


def test_non_string_value_is_skipped():
    """by_lang value 意外為 int / list 時略過該 entry。"""
    by_lang = {"zh-TW": 123, "en-US": "Hematuria"}
    assert pick(by_lang, "zh-TW", legacy_value="舊") == "Hematuria"
