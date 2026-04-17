"""
守護 P2 #20 `/api/v1/healthz/deep` 深度健康檢查：

- DB + Redis 都 OK → 200，payload.status == "ok"
- DB 拋例外 → 503，payload.checks.db 以 "fail: ..." 開頭
- Redis 拋例外 → 503，payload.checks.redis 以 "fail: ..." 開頭

用 FastAPI dependency overrides 注入 FakeDB / FakeRedis，避免真連線。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app


class _FakeResult:
    def __init__(self, value: int = 1) -> None:
        self._value = value

    def scalar(self) -> int:
        return self._value


class _FakeDBOk:
    async def execute(self, stmt: Any) -> _FakeResult:  # noqa: ARG002
        return _FakeResult()


class _FakeDBFail:
    async def execute(self, stmt: Any) -> _FakeResult:  # noqa: ARG002
        raise RuntimeError("db boom")


class _FakeRedisOk:
    async def ping(self) -> bool:
        return True


class _FakeRedisFail:
    async def ping(self) -> bool:
        raise RuntimeError("redis boom")


def _install_overrides(db_obj: Any, redis_obj: Any) -> None:
    async def _get_db():
        yield db_obj

    async def _get_redis():
        return redis_obj

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_redis] = _get_redis


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_redis, None)


def test_deep_health_both_ok_returns_200():
    _install_overrides(_FakeDBOk(), _FakeRedisOk())
    try:
        with TestClient(app) as client:
            r = client.get("/api/v1/healthz/deep")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["checks"] == {"db": "ok", "redis": "ok"}
    finally:
        _clear_overrides()


def test_deep_health_db_failure_returns_503():
    _install_overrides(_FakeDBFail(), _FakeRedisOk())
    try:
        with TestClient(app) as client:
            r = client.get("/api/v1/healthz/deep")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "fail"
        assert body["checks"]["db"].startswith("fail:")
        assert "db boom" in body["checks"]["db"]
        assert body["checks"]["redis"] == "ok"
    finally:
        _clear_overrides()


def test_deep_health_redis_failure_returns_503():
    _install_overrides(_FakeDBOk(), _FakeRedisFail())
    try:
        with TestClient(app) as client:
            r = client.get("/api/v1/healthz/deep")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "fail"
        assert body["checks"]["db"] == "ok"
        assert body["checks"]["redis"].startswith("fail:")
        assert "redis boom" in body["checks"]["redis"]
    finally:
        _clear_overrides()
