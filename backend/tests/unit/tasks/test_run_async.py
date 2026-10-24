"""`app.tasks.run_async`：同步 Celery task body 跑 coroutine 的唯一入口。

舊寫法 ``try: loop.run_until_complete(coro) except Exception: asyncio.run(coro)``
會把 business exception 當成「loop 壞了」而把整個 task body 重跑一次
（推播送兩遍、報告標兩次 FAILED）。這裡釘住：factory 只被呼叫一次。
"""

import pytest

from app.tasks import run_async


def test_factory_raising_business_exception_is_invoked_exactly_once():
    calls: list[int] = []

    async def _boom() -> None:
        calls.append(1)
        raise ValueError("business error, not a loop problem")

    with pytest.raises(ValueError):
        run_async(_boom)

    assert calls == [1]


def test_returns_coroutine_result():
    async def _ok() -> int:
        return 42

    assert run_async(_ok) == 42
