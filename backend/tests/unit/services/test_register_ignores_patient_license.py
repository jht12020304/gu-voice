"""自助註冊（AUTH-3 降級為 PATIENT）不得把自稱的 license_number 存進病患帳號。

clinician scope 以 `license_number` 區分「臨床 admin」與 system admin；病患帳號帶著
一個執照欄位沒有意義，也不該讓病患自行宣告。
"""

from __future__ import annotations

import asyncio

from app.models.enums import UserRole
from app.schemas.auth import RegisterRequest
from app.services import auth_service as svc


class _NoUserResult:
    def scalar_one_or_none(self):
        return None


class _FakeDB:
    def __init__(self):
        self.added = []

    async def execute(self, stmt):
        return _NoUserResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def test_public_registration_drops_license_number(monkeypatch):
    async def _hash(pw):
        return "hashed"

    monkeypatch.setattr(svc, "hash_password_async", _hash)
    db = _FakeDB()
    data = RegisterRequest(email="p@example.com", password="Passw0rdX", name="P",
                           role=UserRole.DOCTOR, license_number="FAKE-001")

    async def run():
        try:
            await svc.AuthService.register(db, data, current_user=None)
        except Exception:
            pass  # 後續 token 發行可能需要 redis；本測只看寫進 DB 的 User

    asyncio.run(run())
    users = [u for u in db.added if getattr(u, "email", None) == "p@example.com"]
    assert users, "register 應建立 User"
    assert users[0].role == UserRole.PATIENT
    assert users[0].license_number is None
