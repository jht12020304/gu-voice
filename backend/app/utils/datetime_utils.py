"""
日期時間工具函式
- UTC 時間取得
- ISO 8601 格式化與解析
"""

from datetime import datetime, timezone
from typing import Optional

from app.core.exceptions import ValidationException


def utc_now() -> datetime:
    """取得當前 UTC 時間（帶時區資訊）"""
    return datetime.now(timezone.utc)


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    將 datetime 格式化為 ISO 8601 字串

    Args:
        dt: datetime 物件，若為 None 則回傳 None

    Returns:
        ISO 8601 格式字串，例如 "2026-04-10T08:30:00+00:00"
    """
    if dt is None:
        return None
    # 若無時區資訊，假設為 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    """
    解析 ISO 8601 字串為 datetime

    Args:
        s: ISO 8601 格式字串，若為 None 則回傳 None

    Returns:
        帶 UTC 時區的 datetime 物件

    Raises:
        ValidationException: 非 None 但格式不合法（含空字串、非 ISO-8601），
            避免非法輸入冒泡成裸 500；合法輸入與 None 行為不變。
    """
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError) as exc:
        raise ValidationException(
            "errors.invalid_date_format",
            details={"value": s},
        ) from exc
    # 若無時區資訊，假設為 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
