"""報告就緒／失敗的 fan-out 只用**一個** query 取全部醫師的 preferred_language。

先前每位目標各打一次 `select(User.preferred_language)`（N 位醫師＝N 個 round trip，
每次 SOAP 完成都觸發）。這支用計數型假 DB 釘住「語言查詢次數 = 1」，同時確認
每位醫師仍拿到自己語言的文案。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.services import notification_service as ns


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0][1] if self._rows else None


class _CountingDB:
    def __init__(self, langs: dict):
        self.langs = langs
        self.language_queries = 0

    async def execute(self, stmt):
        sql = str(stmt)
        if "preferred_language" in sql:
            self.language_queries += 1
            return _Result([(uid, lang) for uid, lang in self.langs.items()])
        return _Result([])

    async def flush(self):
        pass


def _run(coro):
    return asyncio.run(coro)


def test_report_ready_fanout_uses_single_language_query(monkeypatch):
    targets = [uuid4() for _ in range(5)]
    langs = {t: ("en-US" if i % 2 else "zh-TW") for i, t in enumerate(targets)}
    db = _CountingDB(langs)
    created_titles: list[tuple] = []

    async def _targets(db_, doctor_id, session_id):  # noqa: ARG001
        return targets

    async def _resolve(db_, session_id):  # noqa: ARG001
        return None, "王小明"

    async def _create(db_, *, user_id, type, title, body, data):  # noqa: ARG001, A002
        created_titles.append((user_id, title))
        return SimpleNamespace(id=uuid4(), user_id=user_id)

    async def _push(**kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(ns.NotificationService, "_doctor_targets", staticmethod(_targets))
    monkeypatch.setattr(ns.NotificationService, "_resolve_session_targets", staticmethod(_resolve))
    monkeypatch.setattr(ns.NotificationService, "create", staticmethod(_create))
    monkeypatch.setattr(ns, "_dispatch_push_best_effort", _push)

    created = _run(ns.NotificationService.notify_report_ready(db, session_id=uuid4(), report_id=uuid4()))

    assert len(created) == 5
    assert db.language_queries == 1, f"語言查詢應只有 1 次，實際 {db.language_queries}"
    titles = dict(created_titles)
    assert titles[targets[0]] != titles[targets[1]], "不同 preferred_language 的醫師應拿到不同語言文案"
