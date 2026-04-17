"""
守護 P2 #12：config.py 三路對齊後的優先順序契約。

為什麼有這個檔：
- DATABASE_URL / REDIS_URL / JWT_PRIVATE_KEY 同時有「顯式值」與「元件組合」兩條路徑，
  歷史上曾經名稱不一致（.env.example 的 JWT_PRIVATE_KEY 被 config.py 忽略），
  這層測試把「顯式優先、元件 fallback、PEM-vs-path 偵測」焊死，免得又漂回去。
- 不碰 .env / Redis / DB，純 pydantic Settings 構造行為測試。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.core.config import Settings


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

def _env_only(monkeypatch, **kv: str) -> None:
    """清空會干擾的 env，再塞入指定的 key/value。不讀 .env 檔。"""
    for k in (
        "DATABASE_URL", "ASYNC_DATABASE_URL", "REDIS_URL",
        "JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY",
        "JWT_PRIVATE_KEY_PATH", "JWT_PUBLIC_KEY_PATH",
        "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
        "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB",
        "JWT_ALGORITHM", "JWT_SECRET_KEY",
        "LOG_LEVEL", "APP_LOG_LEVEL",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def _settings_without_dotenv(monkeypatch) -> Settings:
    """避開 backend/.env 檔干擾：傳 _env_file=None 明確禁用 .env 載入。"""
    return Settings(_env_file=None)


# ──────────────────────────────────────────────────────
# DATABASE_URL 優先於 DB_* 元件
# ──────────────────────────────────────────────────────

def test_explicit_database_url_wins(monkeypatch):
    _env_only(
        monkeypatch,
        DATABASE_URL="postgresql://u:p@db.supabase.co:5432/mydb",
        DB_HOST="should-not-be-used",
        DB_NAME="wrong",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert "db.supabase.co" in s.DATABASE_URL
    assert "should-not-be-used" not in s.DATABASE_URL


def test_async_database_url_adds_asyncpg_driver(monkeypatch):
    """顯式給 plain postgresql:// → ASYNC_DATABASE_URL 自動加 +asyncpg."""
    _env_only(
        monkeypatch,
        DATABASE_URL="postgresql://u:p@host:5432/db",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.DATABASE_URL.startswith("postgresql://")
    assert s.ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://")


def test_async_database_url_strips_asyncpg_for_sync(monkeypatch):
    """顯式給 postgresql+asyncpg:// → sync DATABASE_URL 會把驅動後綴去掉."""
    _env_only(
        monkeypatch,
        DATABASE_URL="postgresql+asyncpg://u:p@host:5432/db",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.DATABASE_URL == "postgresql://u:p@host:5432/db"
    assert s.ASYNC_DATABASE_URL == "postgresql+asyncpg://u:p@host:5432/db"


def test_postgres_legacy_scheme_normalized(monkeypatch):
    """Railway/Heroku 舊格式 postgres:// → 兩版都轉成 postgresql:// 家族."""
    _env_only(
        monkeypatch,
        DATABASE_URL="postgres://u:p@host:5432/db",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.DATABASE_URL == "postgresql://u:p@host:5432/db"
    assert s.ASYNC_DATABASE_URL == "postgresql+asyncpg://u:p@host:5432/db"


def test_db_components_compose_when_no_explicit_url(monkeypatch):
    """沒設 DATABASE_URL 時走 DB_* 元件組合路徑 + URL 跳脫特殊字元."""
    _env_only(
        monkeypatch,
        DB_HOST="localhost",
        DB_PORT="5432",
        DB_NAME="gu",
        DB_USER="gu_app",
        DB_PASSWORD="p@ss/word!",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    # 密碼裡的 @ / ! 要被 quote，不可以裸出現在 URL
    assert "p@ss/word!" not in s.DATABASE_URL
    assert "p%40ss%2Fword%21" in s.DATABASE_URL
    assert s.ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://")


# ──────────────────────────────────────────────────────
# REDIS_URL 優先於 REDIS_* 元件
# ──────────────────────────────────────────────────────

def test_explicit_redis_url_wins(monkeypatch):
    _env_only(
        monkeypatch,
        REDIS_URL="redis://default:secret@upstash.io:6379",
        REDIS_HOST="should-not-be-used",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.REDIS_URL == "redis://default:secret@upstash.io:6379"


def test_redis_components_compose_when_no_explicit_url(monkeypatch):
    _env_only(
        monkeypatch,
        REDIS_HOST="localhost",
        REDIS_PORT="6379",
        REDIS_PASSWORD="pw",
        REDIS_DB="2",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.REDIS_URL == "redis://:pw@localhost:6379/2"


# ──────────────────────────────────────────────────────
# JWT_PRIVATE_KEY：PEM 內容 vs 路徑自動偵測
# ──────────────────────────────────────────────────────

def test_jwt_pem_content_recognized(monkeypatch):
    """值含 'BEGIN' → 當 PEM 內容，直接使用不讀檔."""
    pem = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    _env_only(
        monkeypatch,
        JWT_ALGORITHM="RS256",
        JWT_PRIVATE_KEY=pem,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.JWT_PRIVATE_KEY == pem


def test_jwt_pem_literal_backslash_n_restored(monkeypatch):
    """Railway 常把 \\n 字面傳進來 → 還原成真換行，不然 jose 會解析失敗."""
    _env_only(
        monkeypatch,
        JWT_ALGORITHM="RS256",
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\nabc\\n-----END RSA PRIVATE KEY-----",
    )
    s = _settings_without_dotenv(monkeypatch)
    assert "\\n" not in s.JWT_PRIVATE_KEY
    assert "\n" in s.JWT_PRIVATE_KEY


def test_jwt_path_value_reads_file(monkeypatch, tmp_path):
    """值不含 'BEGIN' 且為存在路徑 → 讀檔回傳內容."""
    key_file = tmp_path / "private.pem"
    key_file.write_text("FILE_CONTENT_PRIV")
    _env_only(
        monkeypatch,
        JWT_ALGORITHM="RS256",
        JWT_PRIVATE_KEY=str(key_file),
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.JWT_PRIVATE_KEY == "FILE_CONTENT_PRIV"


def test_jwt_fallback_to_path_field(monkeypatch, tmp_path):
    """完全沒設 JWT_PRIVATE_KEY → fallback 到 JWT_PRIVATE_KEY_PATH."""
    key_file = tmp_path / "fallback.pem"
    key_file.write_text("FALLBACK")
    _env_only(
        monkeypatch,
        JWT_ALGORITHM="RS256",
        JWT_PRIVATE_KEY_PATH=str(key_file),
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.JWT_PRIVATE_KEY == "FALLBACK"


def test_hs256_ignores_pem_uses_secret(monkeypatch):
    """HS256 時一律用 JWT_SECRET_KEY，不理 PEM 設定."""
    _env_only(
        monkeypatch,
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="s" * 40,
        JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nirrelevant\n-----END RSA PRIVATE KEY-----",
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.JWT_PRIVATE_KEY == "s" * 40
    assert s.JWT_PUBLIC_KEY == "s" * 40


# ──────────────────────────────────────────────────────
# LOG_LEVEL 單一欄位
# ──────────────────────────────────────────────────────

def test_log_level_reads_env(monkeypatch):
    _env_only(
        monkeypatch,
        LOG_LEVEL="DEBUG",
        JWT_ALGORITHM="HS256",
        JWT_SECRET_KEY="x" * 40,
    )
    s = _settings_without_dotenv(monkeypatch)
    assert s.LOG_LEVEL == "DEBUG"


def test_log_level_default(monkeypatch):
    _env_only(monkeypatch, JWT_ALGORITHM="HS256", JWT_SECRET_KEY="x" * 40)
    s = _settings_without_dotenv(monkeypatch)
    assert s.LOG_LEVEL == "info"


def test_app_log_level_field_removed(monkeypatch):
    """確保舊的 APP_LOG_LEVEL 欄位已被移除，避免雙來源."""
    _env_only(monkeypatch, JWT_ALGORITHM="HS256", JWT_SECRET_KEY="x" * 40)
    s = _settings_without_dotenv(monkeypatch)
    assert not hasattr(s, "APP_LOG_LEVEL")
