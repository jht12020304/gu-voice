"""
語言解析工具（docs/i18n_plan.md TODO C.6 / E14 / TODO-O1）。

`resolve_language()` 實作 fallback chain + feature flag gate：

    Feature flag gate
    ────────────────
    - MULTILANG_GLOBAL_ENABLED=False    → 一律回 DEFAULT_LANGUAGE
    - 認證使用者不在 ROLLOUT_PERCENT     → 回 DEFAULT_LANGUAGE
    - 最終候選在 DISABLED_LANGUAGES      → 回 DEFAULT_LANGUAGE（kill-switch）

    Fallback chain（通過 gate 後）
    ────────────────────────────
    payload.language
    → user.preferred_language
    → Accept-Language header（僅取第一個語言，忽略 q 權重）
    → settings.DEFAULT_LANGUAGE

任何環節回傳不在 `SUPPORTED_LANGUAGES` 的值都會被跳過（而非 raise），
讓 fallback 能繼續往下找；所有環節都漏掉才走 settings default。

上線前待辦：
- TODO-M4：consent_records 須 block 未同意最新版的 session。
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class _UserLike(Protocol):
    """只需要 preferred_language 屬性 — ORM User 或 dict wrapper 都相容。

    rollout gate 會讀 `id` 屬性（若存在）作 hash 依據；不是 hard requirement，
    缺失時視同匿名請求（放行 fallback chain）。"""

    preferred_language: Optional[str]


def _user_in_rollout(user: Optional[_UserLike]) -> bool:
    """以 user.id 的 md5 hash 對 100 取模，決定是否進入灰度群。

    - `MULTILANG_ROLLOUT_PERCENT >= 100` → 一律放行
    - `MULTILANG_ROLLOUT_PERCENT <= 0`   → 一律不放行
    - 中間值：使用者按 hash bucket 分配（穩定，不隨時間漂移）
    - 匿名請求（user=None）→ 放行；gate 主要用來管認證使用者的灰度
    """
    percent = max(0, min(100, int(settings.MULTILANG_ROLLOUT_PERCENT)))
    if percent >= 100:
        return True
    # 匿名請求不在 bucket 體系內 — rollout gate 是管認證使用者的灰度，
    # 無 user 或 user.id 缺失時一律放行，避免公開路由（login / forgot-password）被整批 kill
    if user is None:
        return True
    uid = getattr(user, "id", None)
    if uid is None:
        return True
    if percent <= 0:
        return False
    bucket = int(hashlib.md5(str(uid).encode("utf-8")).hexdigest(), 16) % 100
    return bucket < percent


_ACCEPT_LANG_TOKEN_RE = re.compile(r"([A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*)")


def normalize_bcp47(code: Optional[str]) -> Optional[str]:
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
        normalized = normalize_bcp47(match.group(1))
        if not normalized:
            continue
        if normalized in supported:
            return normalized
        # 瀏覽器常只送兩字碼（zh / en）→ expand 到已支援的 region 版本
        family = normalized.split("-")[0]
        if family in family_to_locale:
            return family_to_locale[family]
    return None


def _safe_default() -> str:
    """回傳 DEFAULT_LANGUAGE；若 misconfigured（不在 SUPPORTED_LANGUAGES）則退 zh-TW。"""
    default = settings.DEFAULT_LANGUAGE
    if default in settings.SUPPORTED_LANGUAGES:
        return default
    logger.warning(
        "resolve_language: DEFAULT_LANGUAGE=%r not in SUPPORTED_LANGUAGES=%r; "
        "hard-coded fallback to zh-TW",
        default,
        settings.SUPPORTED_LANGUAGES,
    )
    return "zh-TW"


def resolve_language(
    *,
    payload_language: Optional[str] = None,
    user: Optional[_UserLike] = None,
    accept_language_header: Optional[str] = None,
) -> str:
    """
    解析 session 使用語言。

    Feature flag gate（按順序）：
      1. MULTILANG_GLOBAL_ENABLED=False → DEFAULT_LANGUAGE
      2. user 不在 ROLLOUT_PERCENT bucket → DEFAULT_LANGUAGE
      3. 最終候選落在 DISABLED_LANGUAGES → DEFAULT_LANGUAGE（kill-switch）

    Fallback chain（通過 gate 後）：
      payload > user.preferred_language > Accept-Language > DEFAULT_LANGUAGE。

    所有候選都須落在 `settings.SUPPORTED_LANGUAGES` 才採用；否則略過。
    永遠回字串。
    """
    # Gate 1：全域 kill switch
    if not settings.MULTILANG_GLOBAL_ENABLED:
        return _safe_default()

    # Gate 2：rollout bucket
    if not _user_in_rollout(user):
        logger.debug("resolve_language: user not in rollout bucket; using default")
        return _safe_default()

    supported = set(settings.SUPPORTED_LANGUAGES)
    disabled = set(settings.MULTILANG_DISABLED_LANGUAGES or [])

    def _accept(cand: Optional[str]) -> Optional[str]:
        """候選須在 supported 且不在 disabled。"""
        if not cand or cand not in supported or cand in disabled:
            return None
        return cand

    # 1. payload 顯式指定
    accepted = _accept(normalize_bcp47(payload_language))
    if accepted:
        return accepted
    if payload_language:
        logger.debug(
            "resolve_language: payload %r not accepted (supported=%s, disabled=%s)",
            payload_language, supported, disabled,
        )

    # 2. user.preferred_language
    if user is not None:
        accepted = _accept(normalize_bcp47(getattr(user, "preferred_language", None)))
        if accepted:
            return accepted

    # 3. Accept-Language header
    from_header = _pick_from_accept_language(accept_language_header)
    accepted = _accept(from_header)
    if accepted:
        return accepted

    # 4. settings default（DEFAULT_LANGUAGE 本身不受 DISABLED 影響 —
    #    kill switch 觸發時仍用 default 作為 last resort 一致選擇）
    return _safe_default()
