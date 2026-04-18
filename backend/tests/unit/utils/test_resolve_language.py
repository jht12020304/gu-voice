"""
守護 `app.utils.language.resolve_language` 的 fallback chain 與 feature flag gate：

Fallback chain 順序：payload > user.preferred_language > Accept-Language > settings default。
任一環節產出未支援語言 → 略過、往下找；全部 miss → settings default。

Feature flag gate：
  - MULTILANG_GLOBAL_ENABLED=False → 直接回 default
  - MULTILANG_ROLLOUT_PERCENT 決定使用者是否進入灰度 bucket
  - MULTILANG_DISABLED_LANGUAGES 作為 per-locale kill switch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.core.config import settings
from app.utils.language import resolve_language


@dataclass
class _FakeUser:
    preferred_language: Optional[str] = None
    id: Optional[str] = None


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
    # ja-JP 已進 SUPPORTED_LANGUAGES（beta），header 順序先列會命中。
    assert (
        resolve_language(
            accept_language_header="fr-FR,ja-JP;q=0.9,en-US;q=0.8",
        )
        == "ja-JP"
    )
    # unsupported 跳過：de-DE 不在清單，往後找到 en-US。
    assert (
        resolve_language(
            accept_language_header="de-DE;q=0.9,en-US;q=0.8",
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


# ─────────────────────────────────────────────────────────────
# Feature flag gate（TODO-O1）
# ─────────────────────────────────────────────────────────────


def test_gate_global_disabled_returns_default(monkeypatch):
    """MULTILANG_GLOBAL_ENABLED=False → 一律 DEFAULT_LANGUAGE，不走 fallback chain。"""
    monkeypatch.setattr(settings, "MULTILANG_GLOBAL_ENABLED", False)
    assert (
        resolve_language(
            payload_language="en-US",
            user=_FakeUser("en-US"),
            accept_language_header="en-US",
        )
        == settings.DEFAULT_LANGUAGE
    )


def test_gate_rollout_zero_blocks_authenticated_users(monkeypatch):
    """ROLLOUT_PERCENT=0 + 有 user.id → 不進灰度，回 default。"""
    monkeypatch.setattr(settings, "MULTILANG_ROLLOUT_PERCENT", 0)
    assert (
        resolve_language(
            payload_language="en-US",
            user=_FakeUser(preferred_language="en-US", id="user-123"),
        )
        == settings.DEFAULT_LANGUAGE
    )


def test_gate_rollout_zero_allows_anonymous(monkeypatch):
    """ROLLOUT_PERCENT=0 但匿名請求 (user=None) → 放行 fallback chain。"""
    monkeypatch.setattr(settings, "MULTILANG_ROLLOUT_PERCENT", 0)
    assert (
        resolve_language(
            payload_language="en-US",
            user=None,
        )
        == "en-US"
    )


def test_gate_rollout_full_allows_everyone(monkeypatch):
    """ROLLOUT_PERCENT=100 → 不論 user.id 都進灰度。"""
    monkeypatch.setattr(settings, "MULTILANG_ROLLOUT_PERCENT", 100)
    assert (
        resolve_language(
            payload_language="en-US",
            user=_FakeUser(preferred_language="zh-TW", id="any-user"),
        )
        == "en-US"
    )


def test_gate_rollout_partial_is_stable_per_user(monkeypatch):
    """ROLLOUT_PERCENT 中間值：同一 user.id 多次呼叫結果一致（hash 穩定）。"""
    monkeypatch.setattr(settings, "MULTILANG_ROLLOUT_PERCENT", 50)
    user = _FakeUser(preferred_language="en-US", id="stable-user-id")
    results = {
        resolve_language(payload_language="en-US", user=user)
        for _ in range(5)
    }
    assert len(results) == 1  # 同一 user 必定分到同一 bucket


def test_gate_disabled_language_kill_switch(monkeypatch):
    """MULTILANG_DISABLED_LANGUAGES 包含候選 → 跳過該候選。"""
    monkeypatch.setattr(settings, "MULTILANG_DISABLED_LANGUAGES", ["en-US"])
    # payload=en-US 被 block → 改看 user → 再看 accept-language
    assert (
        resolve_language(
            payload_language="en-US",
            user=_FakeUser(preferred_language="en-US"),
            accept_language_header="zh-TW",
        )
        == "zh-TW"
    )


def test_gate_disabled_language_falls_to_default(monkeypatch):
    """全部候選都在 DISABLED_LANGUAGES → 最終走 settings default。"""
    monkeypatch.setattr(settings, "MULTILANG_DISABLED_LANGUAGES", ["en-US"])
    assert (
        resolve_language(
            payload_language="en-US",
            user=_FakeUser(preferred_language="en-US"),
            accept_language_header="en-US",
        )
        == settings.DEFAULT_LANGUAGE
    )


def test_gate_default_language_unaffected_by_disabled(monkeypatch):
    """
    DEFAULT_LANGUAGE 本身不受 DISABLED 影響 — kill switch 觸發時仍用 default 作為
    last resort；避免整個系統沒語言可回。
    """
    # 讓所有候選都 miss，強制走到 default
    monkeypatch.setattr(settings, "MULTILANG_DISABLED_LANGUAGES", ["en-US"])
    assert (
        resolve_language(
            payload_language=None,
            user=None,
            accept_language_header=None,
        )
        == settings.DEFAULT_LANGUAGE
    )
