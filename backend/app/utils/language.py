"""
語言解析工具（docs/i18n_plan.md TODO C.6 / E14）。

`resolve_language()` 實作 fallback chain：
    payload.language
    → user.preferred_language
    → Accept-Language header（僅取第一個語言，忽略 q 權重）
    → settings.DEFAULT_LANGUAGE

任何環節回傳不在 `SUPPORTED_LANGUAGES` 的值都會被跳過（而非 raise），
讓 fallback 能繼續往下找；所有環節都漏掉才走 settings default。

上線前須完成的相關 TODO：
- TODO-M4：consent_records 須 block 未同意最新版的 session。
- TODO-O1：此函式要先過 feature flag gate（`MULTILANG_GLOBAL_ENABLED`
           / `MULTILANG_ROLLOUT_PERCENT` / `MULTILANG_DISABLED_LANGUAGES`），
           flag 未開時一律回 DEFAULT_LANGUAGE。
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class _UserLike(Protocol):
    """只需要 preferred_language 屬性 — ORM User 或 dict wrapper 都相容。"""

    preferred_language: Optional[str]


_ACCEPT_LANG_TOKEN_RE = re.compile(r"([A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*)")


def _normalize(code: Optional[str]) -> Optional[str]:
    """大小寫正規化為 BCP-47 conventional form（zh-tw → zh-TW、EN → en）。"""
    if not code:
        return None
    parts = code.strip().split("-")
    if len(parts) == 1:
        return parts[0].lower()
    # 第一段 lowercase，第二段 uppercase（region subtag 慣例）
    return f"{parts[0].lower()}-{parts[1].upper()}"


def _pick_from_accept_language(header: Optional[str]) -> Optional[str]:
    """
    從 Accept-Language header 取第一個能對到 SUPPORTED_LANGUAGES 的值。

    不做 q 權重比較 — `Accept-Language: zh-TW,en;q=0.8` → 優先 `zh-TW`，
    後面順序即優先順序。遇到 `zh` 時會 expand 為 `zh-TW`（主語言 fallback），
    避免瀏覽器只送兩字碼時失配。
    """
    if not header:
        return None

    supported = set(settings.SUPPORTED_LANGUAGES)
    # 預處理一次 language-family → first matching full locale 對映
    family_to_locale: dict[str, str] = {}
    for locale in settings.SUPPORTED_LANGUAGES:
        family = locale.split("-")[0].lower()
        family_to_locale.setdefault(family, locale)

    for token in header.split(","):
        # 去掉 q= 權重後取語言碼
        code = token.split(";")[0].strip()
        match = _ACCEPT_LANG_TOKEN_RE.match(code)
        if not match:
            continue
        normalized = _normalize(match.group(1))
        if not normalized:
            continue
        if normalized in supported:
            return normalized
        # 瀏覽器常只送兩字碼（zh / en）→ expand 到已支援的 region 版本
        family = normalized.split("-")[0]
        if family in family_to_locale:
            return family_to_locale[family]
    return None


def resolve_language(
    *,
    payload_language: Optional[str] = None,
    user: Optional[_UserLike] = None,
    accept_language_header: Optional[str] = None,
) -> str:
    """
    解析 session 使用語言。

    優先序：payload > user.preferred_language > Accept-Language > settings 預設。
    所有候選都須落在 `settings.SUPPORTED_LANGUAGES` 才採用；否則略過。
    永遠回字串 —— 最後一層 fallback 到 `settings.DEFAULT_LANGUAGE`。
    """
    supported = set(settings.SUPPORTED_LANGUAGES)

    # 1. payload 顯式指定
    candidate = _normalize(payload_language)
    if candidate and candidate in supported:
        return candidate
    if payload_language and candidate not in supported:
        logger.debug(
            "resolve_language: payload %r not in supported; fall back",
            payload_language,
        )

    # 2. user.preferred_language
    if user is not None:
        candidate = _normalize(getattr(user, "preferred_language", None))
        if candidate and candidate in supported:
            return candidate

    # 3. Accept-Language header
    from_header = _pick_from_accept_language(accept_language_header)
    if from_header:
        return from_header

    # 4. settings default
    default = settings.DEFAULT_LANGUAGE
    if default in supported:
        return default
    # 終極防線：default 不在清單時回 zh-TW 避免 runtime 炸鍋
    logger.warning(
        "resolve_language: DEFAULT_LANGUAGE=%r not in SUPPORTED_LANGUAGES=%r; "
        "hard-coded fallback to zh-TW",
        default,
        settings.SUPPORTED_LANGUAGES,
    )
    return "zh-TW"
