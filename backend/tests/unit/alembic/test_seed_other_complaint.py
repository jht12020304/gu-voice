"""#5：驗證「其他」sentinel 主訴 seed 的結構與跨層同步。

大部分測試不跑實際 migration，只針對 seed 常數做靜態檢查，確保：
1. sentinel UUID 與 conversation_handler 的特判常數一致（跨檔同步）
2. sentinel UUID 可解析且不與既有 10 筆 seed 衝突
3. name / description / 分類都有 5 語完整覆蓋 + pick() 煙霧測試
4. is_default=True（病患端可見）且 display_order 排在既有 seed 之後
5. 分類 5 語與舊 seed 的 other 分類完全一致（前端才會歸入同一 section）

F7 追加：upgrade() 冪等性驗證（`test_upgrade_is_idempotent_when_sentinel_already_referenced_by_fk`）
是唯一真的跑 migration 的測試——舊版 upgrade() 是 DELETE-then-INSERT，sentinel
一旦被 sessions.chief_complaint_id（NOT NULL FK、無 cascade）引用，重跑就會撞
FK violation；這個屬性只有對著真 DB 執行才驗得出來，純靜態檢查測不到。該測試
在自己開的交易內建最小 users→patients→sessions 引用鏈，全程不 commit，跑完
一律 rollback，不會在共用測試 DB 留下痕跡；DB 連不上時比照
tests/integration/conftest.py 的慣例整個 skip，CI 沒 DB 仍維持綠燈。
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.utils.localized_field import pick
from app.websocket.conversation_handler import OTHER_CHIEF_COMPLAINT_ID


SUPPORTED_LANGS = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic" / "versions"

# 與 tests/integration/conftest.py 同一顆測試 DB，但這裡走 sync psycopg2
# driver（與 alembic/env.py 一致，op.execute 本來就是 sync 語意）。
TEST_DATABASE_URL_SYNC = os.environ.get(
    "TEST_DATABASE_URL_SYNC",
    "postgresql+psycopg2://postgres:postgres@127.0.0.1:55432/gu_voice",
)


def _sync_db_reachable(url: str) -> bool:
    """比照 tests/integration/conftest.py：連不上就整個 module 交給呼叫端 skip。"""
    try:
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


DB_AVAILABLE = _sync_db_reachable(TEST_DATABASE_URL_SYNC)

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason=(
        "integration DB unreachable at "
        f"{TEST_DATABASE_URL_SYNC!r}; set TEST_DATABASE_URL_SYNC to a migrated Postgres"
    ),
)


def _load_migration(filename: str, module_name: str):
    """以 importlib 動態載入 migration（檔名以數字開頭不能直接 import）。"""
    spec = importlib.util.spec_from_file_location(module_name, VERSIONS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed_module():
    return _load_migration(
        "20260704_1000-seed_other_chief_complaint.py", "other_seed"
    )


@pytest.fixture(scope="module")
def legacy_seed_module():
    return _load_migration(
        "20260418_1900-seed_chief_complaints_multilang.py", "b1_seed_for_other"
    )


def test_sentinel_id_synced_with_conversation_handler(seed_module):
    assert seed_module.OTHER_COMPLAINT_ID == OTHER_CHIEF_COMPLAINT_ID, (
        "seed 與 conversation_handler 的 sentinel UUID 必須一致，"
        "否則開場語特判永遠不會命中"
    )


def test_sentinel_id_is_valid_uuid_and_not_colliding(seed_module, legacy_seed_module):
    uuid.UUID(seed_module.OTHER_COMPLAINT_ID)  # 不可解析會 raise
    legacy_ids = {c["id"] for c in legacy_seed_module.SEED_COMPLAINTS}
    assert seed_module.OTHER_COMPLAINT_ID not in legacy_ids, (
        "sentinel UUID 不可與既有 seed 衝突（DELETE-then-INSERT 會誤刪）"
    )


def test_entry_id_matches_constant(seed_module):
    assert seed_module.OTHER_COMPLAINT["id"] == seed_module.OTHER_COMPLAINT_ID


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_all_langs_present(seed_module, lang):
    assert seed_module.OTHER_COMPLAINT["name"].get(lang), f"缺少 name[{lang}]"
    assert seed_module.OTHER_COMPLAINT["description"].get(lang), (
        f"缺少 description[{lang}]"
    )
    assert seed_module.CATEGORY_OTHER.get(lang), f"缺少 category[{lang}]"


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_pick_can_resolve(seed_module, lang):
    """以 pick() 煙霧測試 — 模擬 API 上線後讀取路徑。"""
    assert pick(seed_module.OTHER_COMPLAINT["name"], lang)
    assert pick(seed_module.OTHER_COMPLAINT["description"], lang)


def test_visible_to_patients_and_ordered_last(seed_module):
    assert seed_module.OTHER_COMPLAINT["is_default"] is True, (
        "sentinel 必須 is_default=True 病患端才看得到"
    )
    assert seed_module.OTHER_COMPLAINT["display_order"] > 10, (
        "display_order 必須大於既有 seed（1-10），病患端才固定排最後"
    )


def test_category_matches_legacy_other_section(seed_module, legacy_seed_module):
    assert seed_module.CATEGORY_OTHER == legacy_seed_module.CATEGORY_I18N["other"], (
        "分類 5 語必須與舊 seed 的 other 完全一致，前端才會歸入同一個「其他」section"
    )


@requires_db
def test_upgrade_is_idempotent_when_sentinel_already_referenced_by_fk(seed_module):
    """F7：此 migration 已在生產跑過，sentinel 早已可能被 sessions FK 引用；
    重跑 upgrade()（例如重建環境、或未來 alembic downgrade/upgrade 演練）
    不可再撞 FK violation。

    舊版 upgrade() 是 DELETE-then-INSERT：sentinel 一旦被 sessions.chief_complaint_id
    （NOT NULL FK、無 cascade）引用，DELETE 就會被 Postgres 擋下。新版改用
    INSERT ... ON CONFLICT (id) DO UPDATE，同一顆 id 不論存不存在、有沒有被引用
    都能安全重跑。

    注意：不用 `with Operations.context(...):`——該 contextmanager 中間沒有
    try/finally，upgrade() 若拋例外會讓 module-level 的 `alembic.op` proxy
    卡在未清除狀態、殃及同一 pytest session 的其他測試；改成手動
    install/remove proxy 並包在 try/finally 裡，任何情況都保證清乾淨。
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine(TEST_DATABASE_URL_SYNC)
    conn = engine.connect()
    trans = conn.begin()
    op_instance = Operations(MigrationContext.configure(conn))
    op_instance._install_proxy()
    try:
        # 前置：確保 sentinel 存在（模擬「已經跑過一次」的既有環境）。
        seed_module.upgrade()

        # 建最小 users → patients → sessions 引用鏈，讓 sentinel 被真的 FK 引用。
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, name, role) "
                "VALUES (:email, 'x', 'F7 idempotency test user', 'patient') "
                "RETURNING id"
            ),
            {"email": f"f7-seed-idempotency-{uuid.uuid4()}@example.invalid"},
        ).scalar()
        patient_id = conn.execute(
            text(
                "INSERT INTO patients "
                "(user_id, medical_record_number, name, gender, date_of_birth) "
                "VALUES (:user_id, :mrn, 'F7 idempotency test patient', 'other', '2000-01-01') "
                "RETURNING id"
            ),
            {"user_id": user_id, "mrn": f"F7-{uuid.uuid4().hex[:12]}"},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO sessions (patient_id, chief_complaint_id) "
                "VALUES (:patient_id, :complaint_id)"
            ),
            {"patient_id": patient_id, "complaint_id": seed_module.OTHER_COMPLAINT_ID},
        )

        # sentinel 現在被 FK 引用了 —— 重跑兩次 upgrade() 不可拋例外。
        seed_module.upgrade()
        seed_module.upgrade()

        row = conn.execute(
            text(
                "SELECT is_active, is_default, display_order "
                "FROM chief_complaints WHERE id = :id"
            ),
            {"id": seed_module.OTHER_COMPLAINT_ID},
        ).one()
        assert row.is_active is True
        assert row.is_default is True
        assert row.display_order == seed_module.OTHER_COMPLAINT["display_order"]
    finally:
        op_instance._remove_proxy()
        # 全程不 commit，測完 rollback —— 不在共用測試 DB 留下任何痕跡。
        trans.rollback()
        conn.close()
        engine.dispose()
