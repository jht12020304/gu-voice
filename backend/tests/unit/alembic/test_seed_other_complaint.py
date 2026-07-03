"""#5：驗證「其他」sentinel 主訴 seed 的結構與跨層同步。

此測試不跑實際 migration，只針對 seed 常數做靜態檢查，確保：
1. sentinel UUID 與 conversation_handler 的特判常數一致（跨檔同步）
2. sentinel UUID 可解析且不與既有 10 筆 seed 衝突
3. name / description / 分類都有 5 語完整覆蓋 + pick() 煙霧測試
4. is_default=True（病患端可見）且 display_order 排在既有 seed 之後
5. 分類 5 語與舊 seed 的 other 分類完全一致（前端才會歸入同一 section）
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from app.utils.localized_field import pick
from app.websocket.conversation_handler import OTHER_CHIEF_COMPLAINT_ID


SUPPORTED_LANGS = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic" / "versions"


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
