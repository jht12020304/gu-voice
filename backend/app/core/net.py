"""
網路工具 — 統一的 client IP 解析。

設計：
- 預設（`TRUST_PROXY_HEADERS=False`）只信任 socket peer（`request.client.host`），
  完全忽略 X-Forwarded-For。任何客戶端都能自行送 XFF header，若無條件採信首段，
  攻擊者可偽造 IP 繞過 per-IP rate limit、污染 audit_logs。
- 只有在明確設定信任代理（部署於 Railway / Cloudflare 等可信反代後方）時才讀 XFF，
  且取「最靠近伺服器的可信 hop」——即 XFF 鏈的**最後一段**（rightmost）。
  XFF 由各 proxy 由左至右 append，最左段為原始客戶端宣稱值（可被客戶端任意控制），
  最右段才是緊鄰我方可信代理寫入的位址，最不易被偽造。
"""

from __future__ import annotations

from typing import Optional

from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """解析請求來源 IP。

    Returns:
        client IP 字串；無法取得時回空字串（呼叫端 rate limit / audit 對空字串已有
        防禦性處理：不擋、user_id/ip 留空）。
    """
    peer = request.client.host if request.client else ""

    # 延後 import 避免 module 載入期間 settings 尚未就緒，並沿用既有單例。
    from app.core.config import settings

    if not getattr(settings, "TRUST_PROXY_HEADERS", False):
        return peer

    forwarded = _last_forwarded_hop(request.headers.get("x-forwarded-for", ""))
    return forwarded or peer


def _last_forwarded_hop(xff: str) -> Optional[str]:
    """取 X-Forwarded-For 最後一段（最靠近伺服器、最不易被客戶端偽造的 hop）。"""
    if not xff:
        return None
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if not parts:
        return None
    return parts[-1]
