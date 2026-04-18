"""
Sentry 初始化 + PII 過濾（TODO P1-#9）。

- lifespan 啟動時呼叫 `init_sentry()`；未設 `SENTRY_DSN` 時會記 warning 但不會阻擋啟動
- `redact_sensitive` 以 before_send hook 攔截 event 與 breadcrumb，
  去除密碼 / JWT / Authorization header 等敏感欄位
"""

from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import settings

logger = logging.getLogger(__name__)

# 敏感 key 小寫比對（contains），任何包含這些片段的欄位都會被 [Filtered]
_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "api-key",
    "secret",
    "jwt",
    "cookie",
    "set-cookie",
)

_FILTERED = "[Filtered]"


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(frag in lowered for frag in _SENSITIVE_KEY_FRAGMENTS)


def _redact(node: Any) -> Any:
    """遞迴清洗 dict/list，對敏感 key 取代為 [Filtered]。"""
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for k, v in node.items():
            if _is_sensitive_key(k):
                cleaned[k] = _FILTERED
            else:
                cleaned[k] = _redact(v)
        return cleaned
    if isinstance(node, list):
        return [_redact(item) for item in node]
    return node


def redact_sensitive(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Sentry `before_send` hook：移除可能含密碼 / token 的欄位。

    Sentry 事件 schema 常見敏感位置：
      - request.headers.Authorization / Cookie
      - request.data (POST body 可能有 password)
      - extra / contexts — 開發者自己塞的診斷資料
    """
    return _redact(event)


def init_sentry() -> bool:
    """
    初始化 Sentry；未設 DSN 時跳過並回傳 False。

    Returns:
        True 表示已初始化；False 表示因缺 DSN / production 外環境等跳過
    """
    dsn = settings.SENTRY_DSN
    env = (settings.APP_ENV or "development").lower()

    if not dsn:
        logger.warning("Sentry 未啟用：SENTRY_DSN 未設")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        traces_sample_rate=0.1,
        send_default_pii=False,
        before_send=redact_sensitive,
        before_send_transaction=redact_sensitive,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            AsyncioIntegration(),
        ],
    )
    logger.info("Sentry 已初始化 | environment=%s", env)
    return True


# ── 語言 tag helper（TODO-O3）────────────────────────────
# Sentry alert rule 可針對特定 tag 過濾，例如「只針對 en-US 且 10 分鐘 >10 issue 告警」；
# 讓英文版規模上量時能獨立觀察錯誤率，不被中文版背景噪音蓋住。
def set_language_scope(language: str | None) -> None:
    """
    為當前 Sentry scope 設定 `session.language` tag。

    呼叫時機：
      - `get_current_user` 依賴取出使用者時，依 `user.preferred_language`
      - session 建立成功後，依 `session.language` 覆寫（session 的值優先於 user preference）

    None / 空字串時不設 tag（避免寫入 "None" 字面值汙染 alert rule 過濾）。
    即使 Sentry 未初始化，`sentry_sdk.set_tag` 也是 no-op，不必另外 guard。
    """
    if not language:
        return
    try:
        sentry_sdk.set_tag("session.language", language)
    except Exception:  # noqa: BLE001 — observability 不應影響主流程
        logger.debug("set_language_scope: set_tag 失敗", exc_info=True)
