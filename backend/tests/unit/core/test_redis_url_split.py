"""
守護 P3 #29 Redis DB index 分離：

- base `redis://localhost:6379/0` → cache `/0`, broker `/1`, result `/2`
- base `redis://localhost:6379`（無 db）→ 直接附加 `/0`、`/1`、`/2`
- base `rediss://user:pass@host:6380/5`（tls + auth + 非零 db）→ 保留 auth 與 tls，
  path 被替換成 `/0`、`/1`、`/2`
"""

from __future__ import annotations

from app.core.config import Settings


def _make_settings(base_url: str) -> Settings:
    """用 REDIS_URL 注入 base，其他欄位走預設即可。"""
    return Settings(REDIS_URL=base_url)  # type: ignore[call-arg]


def test_split_with_trailing_db_zero():
    s = _make_settings("redis://localhost:6379/0")
    assert s.REDIS_URL_CACHE == "redis://localhost:6379/0"
    assert s.REDIS_URL_CELERY_BROKER == "redis://localhost:6379/1"
    assert s.REDIS_URL_CELERY_RESULT == "redis://localhost:6379/2"


def test_split_without_trailing_db():
    s = _make_settings("redis://localhost:6379")
    assert s.REDIS_URL_CACHE == "redis://localhost:6379/0"
    assert s.REDIS_URL_CELERY_BROKER == "redis://localhost:6379/1"
    assert s.REDIS_URL_CELERY_RESULT == "redis://localhost:6379/2"


def test_split_with_tls_auth_and_nonzero_db():
    s = _make_settings("rediss://user:pass@host:6380/5")
    # scheme rediss 與 auth 要保留，只有尾端 db 被換掉
    assert s.REDIS_URL_CACHE == "rediss://user:pass@host:6380/0"
    assert s.REDIS_URL_CELERY_BROKER == "rediss://user:pass@host:6380/1"
    assert s.REDIS_URL_CELERY_RESULT == "rediss://user:pass@host:6380/2"


def test_base_redis_url_untouched():
    """既有 REDIS_URL 屬性不能因為分離改動而被移除。"""
    s = _make_settings("redis://localhost:6379/7")
    assert s.REDIS_URL == "redis://localhost:6379/7"


def test_custom_db_indices_respected(monkeypatch):
    """DB index 欄位若被覆寫，URL 要跟著變。"""
    s = Settings(  # type: ignore[call-arg]
        REDIS_URL="redis://localhost:6379/0",
        REDIS_DB_CACHE=3,
        REDIS_DB_CELERY_BROKER=4,
        REDIS_DB_CELERY_RESULT=5,
    )
    assert s.REDIS_URL_CACHE.endswith("/3")
    assert s.REDIS_URL_CELERY_BROKER.endswith("/4")
    assert s.REDIS_URL_CELERY_RESULT.endswith("/5")
