"""TODO-B1：驗證 seed 資料結構涵蓋 5 語、分類一致、UUID 唯一。

此測試不跑實際 migration，只針對 seed 常數做靜態檢查，確保：
1. 10 筆主訴 UUID 唯一
2. 每筆 name / description 都有 5 語完整覆蓋
3. category_key 都能在 CATEGORY_I18N 找到對應
4. 每個 category 都有 5 語完整覆蓋
5. `pick()` helper 能在任一語言取得非空值（煙霧測試）
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.utils.localized_field import pick


SUPPORTED_LANGS = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")


@pytest.fixture(scope="module")
def seed_module():
    """以 importlib 動態載入 migration（檔名以 yyyy-開頭不能直接 import）。"""
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "20260418_1900-seed_chief_complaints_multilang.py"
    )
    spec = importlib.util.spec_from_file_location("b1_seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_count_matches_spec(seed_module):
    assert len(seed_module.SEED_COMPLAINTS) == 10


def test_seed_uuids_unique(seed_module):
    ids = [c["id"] for c in seed_module.SEED_COMPLAINTS]
    assert len(set(ids)) == len(ids), "seed UUID 必須唯一以保證 idempotent"


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_every_complaint_has_all_langs(seed_module, lang):
    for entry in seed_module.SEED_COMPLAINTS:
        name = entry["name"].get(lang)
        desc = entry["description"].get(lang)
        assert name, f"{entry['id']} 缺少 name[{lang}]"
        assert desc, f"{entry['id']} 缺少 description[{lang}]"


def test_every_category_has_all_langs(seed_module):
    for category_key, labels in seed_module.CATEGORY_I18N.items():
        missing = [lng for lng in SUPPORTED_LANGS if not labels.get(lng)]
        assert not missing, f"分類 {category_key} 缺少 {missing}"


def test_category_keys_referenced_are_defined(seed_module):
    defined = set(seed_module.CATEGORY_I18N.keys())
    for entry in seed_module.SEED_COMPLAINTS:
        assert entry["category_key"] in defined, (
            f"{entry['id']} 參照未定義的 category_key={entry['category_key']}"
        )


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_pick_can_resolve_every_seed(seed_module, lang):
    """以 pick() 煙霧測試 — 模擬 API 上線後讀取路徑。"""
    for entry in seed_module.SEED_COMPLAINTS:
        resolved = pick(entry["name"], lang)
        assert resolved, f"pick(name, {lang}) 在 {entry['id']} 回 None"


def test_display_order_is_sequential(seed_module):
    orders = [c["display_order"] for c in seed_module.SEED_COMPLAINTS]
    assert orders == sorted(orders), "display_order 應為遞增"
    assert orders[0] == 1
