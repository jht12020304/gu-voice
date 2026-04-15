"""
Unit tests for app.main._enforce_production_secrets (問題 ⑭ / ⑱)。

守護:
- APP_ENV=production 時,若 JWT_SECRET_KEY / APP_SECRET_KEY 等於 git 公開
  的 dev 預設字串,應 raise RuntimeError 拒絕啟動
- 非 production 環境只記 warning,不中斷(方便本機開發)
- Secret 為隨機值時無論何種環境都不 raise
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.main as main_module
from app.main import _enforce_production_secrets, _DEV_DEFAULT_SECRETS


def _set_settings(monkeypatch: pytest.MonkeyPatch, **kwargs) -> None:
    fake = SimpleNamespace(
        APP_ENV=kwargs.get("APP_ENV", "development"),
        APP_SECRET_KEY=kwargs.get("APP_SECRET_KEY", "random-32-char-production-secret"),
        JWT_SECRET_KEY=kwargs.get("JWT_SECRET_KEY", "random-32-char-production-jwt-key"),
    )
    monkeypatch.setattr(main_module, "settings", fake)


def test_dev_default_app_secret_in_production_raises(monkeypatch):
    _set_settings(
        monkeypatch,
        APP_ENV="production",
        APP_SECRET_KEY="dev-secret-key-at-least-32-characters-long",
    )
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        _enforce_production_secrets()


def test_dev_default_jwt_secret_in_production_raises(monkeypatch):
    _set_settings(
        monkeypatch,
        APP_ENV="production",
        JWT_SECRET_KEY="dev-jwt-secret-at-least-32-characters-long-for-hs256",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _enforce_production_secrets()


def test_placeholder_change_me_in_production_raises(monkeypatch):
    _set_settings(
        monkeypatch,
        APP_ENV="production",
        APP_SECRET_KEY="change-me-in-production",
    )
    with pytest.raises(RuntimeError):
        _enforce_production_secrets()


def test_empty_jwt_secret_in_production_raises(monkeypatch):
    _set_settings(
        monkeypatch,
        APP_ENV="production",
        JWT_SECRET_KEY="",
    )
    with pytest.raises(RuntimeError):
        _enforce_production_secrets()


def test_production_with_proper_secrets_does_not_raise(monkeypatch):
    _set_settings(
        monkeypatch,
        APP_ENV="production",
        APP_SECRET_KEY="a-very-random-production-secret-xyz",
        JWT_SECRET_KEY="another-random-hs256-key-abc",
    )
    # Should not raise
    _enforce_production_secrets()


def test_development_env_with_dev_defaults_only_warns(monkeypatch, caplog):
    _set_settings(
        monkeypatch,
        APP_ENV="development",
        APP_SECRET_KEY="dev-secret-key-at-least-32-characters-long",
        JWT_SECRET_KEY="dev-jwt-secret-at-least-32-characters-long-for-hs256",
    )
    # 不應 raise;但應該有 warning log
    with caplog.at_level("WARNING"):
        _enforce_production_secrets()
    assert any("dev 預設值" in rec.message for rec in caplog.records)


def test_dev_defaults_registry_covers_both_keys():
    """防止未來有人誤刪 _DEV_DEFAULT_SECRETS 裡其中一項。"""
    assert "APP_SECRET_KEY" in _DEV_DEFAULT_SECRETS
    assert "JWT_SECRET_KEY" in _DEV_DEFAULT_SECRETS
    # 確保已知 dev 字串都在清單裡
    assert "dev-secret-key-at-least-32-characters-long" in _DEV_DEFAULT_SECRETS["APP_SECRET_KEY"]
    assert "dev-jwt-secret-at-least-32-characters-long-for-hs256" in _DEV_DEFAULT_SECRETS["JWT_SECRET_KEY"]
    assert "change-me-in-production" in _DEV_DEFAULT_SECRETS["APP_SECRET_KEY"]
