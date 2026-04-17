"""
守護 `app.utils.language.resolve_language` 的 fallback chain：

順序：payload > user.preferred_language > Accept-Language > settings default。
任一環節產出未支援語言 → 略過、往下找；全部 miss → settings default。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from app.core.config import settings
from app.utils.language import resolve_language


@dataclass
class _FakeUser:
    preferred_language: Optional[str] = None


def test_payload_wins_when_supported():
    assert (
        resolve_language(payload_language="en-US", user=_FakeUser("zh-TW"))
        == "en-US"
    )


def test_payload_unsupported_falls_through_to_user():
    """payload 不在白名單 → 不 raise，改看 user preference。"""
    assert (
        resolve_language(
            payload_language="fr-FR",
            user=_FakeUser("en-US"),
        )
        == "en-US"
    )


def test_user_preference_when_payload_missing():
    assert (
        resolve_language(payload_language=None, user=_FakeUser("en-US"))
        == "en-US"
    )


def test_accept_language_when_no_payload_no_user():
    """使用者 preference 為 None + 無 payload → 看 Accept-Language。"""
    assert (
        resolve_language(
            payload_language=None,
            user=_FakeUser(None),
            accept_language_header="en-US,zh-TW;q=0.8",
        )
        == "en-US"
    )


def test_accept_language_family_expansion():
    """瀏覽器只送 `zh` → 應 expand 到支援的 zh-TW region。"""
    assert (
        resolve_language(
            payload_language=None,
            user=None,
            accept_language_header="zh",
        )
        == "zh-TW"
    )


def test_accept_language_q_order_respected():
    """多語言時取第一個可支援的（忽略 q 權重數值，順序即優先序）。"""
    assert (
        resolve_language(
            accept_language_header="fr-FR,ja-JP;q=0.9,en-US;q=0.8",
        )
        == "en-US"
    )


def test_normalization_case_insensitive():
    """payload 大小寫錯也要能命中（zh-tw → zh-TW）。"""
    assert resolve_language(payload_language="zh-tw") == "zh-TW"
    assert resolve_language(payload_language="EN-us") == "en-US"


def test_fallback_to_settings_default_when_all_miss():
    assert (
        resolve_language(
            payload_language=None,
            user=_FakeUser(None),
            accept_language_header=None,
        )
        == settings.DEFAULT_LANGUAGE
    )


def test_empty_string_payload_is_not_fatal():
    assert (
        resolve_language(
            payload_language="",
            user=_FakeUser(None),
        )
        == settings.DEFAULT_LANGUAGE
    )


def test_malformed_accept_language_ignored():
    """Accept-Language 有奇怪 token 時略過，不 crash。"""
    assert (
        resolve_language(
            accept_language_header=",,, ;q=0.5, xx-YY, en-US",
        )
        == "en-US"
    )


def test_user_preference_unsupported_falls_through():
    """使用者 preferred_language 指向已下架 locale → 改看 header / default。"""
    assert (
        resolve_language(
            user=_FakeUser("de-DE"),
            accept_language_header="zh-TW",
        )
        == "zh-TW"
    )
