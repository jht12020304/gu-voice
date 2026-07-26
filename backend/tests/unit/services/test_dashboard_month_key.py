"""儀表板月份摘要的 month_key 契約測試。

為什麼要測：month_label 是後端硬寫中文（「2026 年 7 月」），非中文語系的醫師
看到會中英混雜。修法是後端額外回傳機器可讀的 month_key，讓前端各自依語系格式化，
所以 month_key 的格式（恆為零填補 YYYY-MM）是前後端契約，必須被鎖住。
"""

import re
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.exceptions import ValidationException
from app.schemas.dashboard import MonthlySummaryResponse
from app.services.dashboard_service import _parse_month_range
from app.utils.datetime_utils import utc_now

# 零填補 YYYY-MM：4 位年 + 合法的 2 位月（01–12）
MONTH_KEY_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@pytest.mark.parametrize(
    ("month_value", "expected_key"),
    [
        ("2026-07", "2026-07"),  # 單位數月份必須零填補
        ("2026-01", "2026-01"),
        ("2026-12", "2026-12"),
        ("2026-10", "2026-10"),
    ],
)
def test_month_key_is_zero_padded_year_month(month_value: str, expected_key: str) -> None:
    _, _, month_key, _ = _parse_month_range(month_value)

    assert month_key == expected_key
    assert MONTH_KEY_PATTERN.match(month_key)


def test_month_key_defaults_to_current_utc_month() -> None:
    """未指定 month 時取當前 UTC 月份，且仍符合零填補格式。"""
    now = utc_now()

    _, _, month_key, _ = _parse_month_range(None)

    assert MONTH_KEY_PATTERN.match(month_key)
    assert month_key == f"{now.year:04d}-{now.month:02d}"


def test_month_key_matches_month_start_after_day_normalisation() -> None:
    """month_start 被正規化到當月 1 日，month_key 必須與正規化後的月份一致。"""
    month_start, month_end, month_key, _ = _parse_month_range("2026-02")

    assert month_start == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert month_end == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert month_key == "2026-02"


def test_december_rolls_over_to_next_year_without_breaking_key() -> None:
    month_start, month_end, month_key, _ = _parse_month_range("2026-12")

    assert month_start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert month_end == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert month_key == "2026-12"


def test_invalid_month_value_raises_validation_exception() -> None:
    with pytest.raises(ValidationException):
        _parse_month_range("2026-13")


def test_month_label_stays_chinese_for_backward_compatibility() -> None:
    """month_label 刻意保留中文：舊前端還在直接顯示它，不能改格式或改語言。"""
    _, _, _, month_label = _parse_month_range("2026-07")

    assert month_label == "2026 年 7 月"


def test_response_exposes_machine_readable_month_and_legacy_label() -> None:
    """`month` 是前端格式化的來源（零填補 YYYY-MM）；`month_label` 僅向後相容保留。

    註：曾短暫加過一個與 `month` 值完全相同的 `month_key`，是多餘欄位，已移除——
    前端一律用 `month`。
    """
    month_start, _, month_key, month_label = _parse_month_range("2026-07")

    response = MonthlySummaryResponse(
        month=month_key,
        month_label=month_label,
        generated_at=month_start,
    )

    assert response.month == "2026-07"
    assert response.month_label == "2026 年 7 月"


def test_month_is_required_on_response() -> None:
    """`month` 是前端格式化年月的唯一來源，被移除的話這個測試要擋下來。"""
    with pytest.raises(ValidationError):
        MonthlySummaryResponse(
            month_label="2026 年 7 月",
            generated_at=utc_now(),
        )
