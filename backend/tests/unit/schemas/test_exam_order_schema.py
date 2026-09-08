"""檢查醫囑 schema 的驗證規則。

這些看起來瑣碎，但每一條都對應一個會讓臨床資料變髒的入口：醫師勾選的項目名稱
最後會原樣存進 JSONB 快照、也會出現在稽核 log 的 `test_names` 裡，沒有代碼表可以
兜底（2026-09-09 拍板先不綁院內代碼），所以形狀只能在這一層守。
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.exam_order import ExamOrderCreate, ExamOrderItem


def test_accepts_camel_case_from_the_app():
    """前端 Dio 送的是 camelCase；alias 必須認得。"""
    item = ExamOrderItem.model_validate({"testName": "尿液常規", "urgency": "routine"})
    assert item.test_name == "尿液常規"

    payload = ExamOrderCreate.model_validate(
        {"items": [{"testName": "腎臟超音波"}], "reportId": str(uuid.uuid4())}
    )
    assert payload.items[0].test_name == "腎臟超音波"
    assert payload.report_id is not None


def test_test_name_whitespace_is_collapsed():
    """LLM 生成的字串常帶換行與連續空白，存進去之前先摺平。"""
    assert ExamOrderItem(test_name="  尿液   常規\n").test_name == "尿液 常規"


def test_blank_test_name_is_rejected():
    with pytest.raises(ValidationError):
        ExamOrderItem(test_name="   ")
    with pytest.raises(ValidationError):
        ExamOrderItem(test_name="")


def test_empty_items_is_allowed():
    """「這次不開任何檢查」是有意義的決策，不能被 schema 擋掉。"""
    assert ExamOrderCreate().items == []
    assert ExamOrderCreate(items=[]).items == []


def test_item_count_is_capped():
    """50 項是防呆上限：正常一張單不會超過個位數，過長多半是前端送錯整份清單。"""
    ok = ExamOrderCreate(items=[ExamOrderItem(test_name=f"項目{i}") for i in range(50)])
    assert len(ok.items) == 50
    with pytest.raises(ValidationError):
        ExamOrderCreate(items=[ExamOrderItem(test_name=f"項目{i}") for i in range(51)])


def test_long_free_text_is_bounded():
    with pytest.raises(ValidationError):
        ExamOrderItem(test_name="x" * 201)
    with pytest.raises(ValidationError):
        ExamOrderCreate(note="x" * 2001)
