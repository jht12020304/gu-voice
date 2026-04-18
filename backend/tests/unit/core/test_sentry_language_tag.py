"""
驗證 Sentry 語言 tag helper（TODO-O3）。

由於 sentry_sdk 是全域單例，且 set_tag 會打 noop（未 init 時），
我們直接 mock `sentry_sdk.set_tag` 驗證呼叫行為，不依賴 Sentry 實際 init。
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.sentry import set_language_scope


def test_set_language_scope_invokes_set_tag() -> None:
    with patch("app.core.sentry.sentry_sdk.set_tag") as mock_set_tag:
        set_language_scope("en-US")
    mock_set_tag.assert_called_once_with("session.language", "en-US")


def test_set_language_scope_noop_on_none() -> None:
    with patch("app.core.sentry.sentry_sdk.set_tag") as mock_set_tag:
        set_language_scope(None)
    mock_set_tag.assert_not_called()


def test_set_language_scope_noop_on_empty_string() -> None:
    with patch("app.core.sentry.sentry_sdk.set_tag") as mock_set_tag:
        set_language_scope("")
    mock_set_tag.assert_not_called()


def test_set_language_scope_swallows_exceptions() -> None:
    """sentry_sdk 故障不可影響業務流程（observability 只是輔助）。"""
    with patch(
        "app.core.sentry.sentry_sdk.set_tag",
        side_effect=RuntimeError("sentry down"),
    ):
        # 不應該 raise
        set_language_scope("ja-JP")


def test_set_language_scope_uses_fixed_tag_key() -> None:
    """tag key 必須穩定為 `session.language` — 改名會讓 Sentry alert rule 全失效。"""
    with patch("app.core.sentry.sentry_sdk.set_tag") as mock_set_tag:
        set_language_scope("zh-TW")
    args, _ = mock_set_tag.call_args
    assert args[0] == "session.language"
    assert args[1] == "zh-TW"
