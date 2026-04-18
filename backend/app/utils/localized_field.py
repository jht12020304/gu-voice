"""
Localized JSONB 欄位讀取 helper（docs/i18n_plan.md TODO-A2 / A3）。

`pick(by_lang, lang, legacy_value, default_lang)` 從 `*_by_lang` JSONB
以下列順序取值：

    1. by_lang[lang]                        — 目標語言命中
    2. by_lang[default_lang]                — 站台預設語言
    3. 任一 non-empty by_lang value          — 最後的 best-effort（避免整格 None）
    4. legacy_value                         — legacy 欄位（name / description / category）
    5. None

設計原則
────────
- 不 raise：任何輸入（dict / None / 非 dict）都回 `Optional[str]`，讓 API 永遠
  能序列化
- 不做 family fallback（zh → zh-TW）：前端 URL `/:lng/*` 已用完整 BCP-47 碼
- legacy_value 最後才看：expand-migrate-contract 期間，_by_lang 是新權威來源
  但舊資料若尚未 backfill 時，legacy 欄位可救場
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.core.config import settings


def pick(
    by_lang: Optional[Mapping[str, Any]],
    lang: Optional[str],
    *,
    legacy_value: Optional[str] = None,
    default_lang: Optional[str] = None,
) -> Optional[str]:
    """從 `*_by_lang` JSONB 取指定語言值，含多層 fallback。

    Args:
        by_lang: JSONB 欄位內容（dict / None / 其它）
        lang: 目標 BCP-47 語言碼
        legacy_value: 當 by_lang 完全取不到時退回的舊欄位值
        default_lang: 站台預設語言（None 時讀 settings.DEFAULT_LANGUAGE）

    Returns:
        字串或 None。空字串視為 falsy，會繼續往後 fallback。
    """
    fallback = default_lang or settings.DEFAULT_LANGUAGE

    if isinstance(by_lang, Mapping):
        # 1. 目標語言命中
        value = by_lang.get(lang) if lang else None
        if _is_non_empty_string(value):
            return str(value)

        # 2. 預設語言命中
        value = by_lang.get(fallback)
        if _is_non_empty_string(value):
            return str(value)

        # 3. 任一 non-empty value（避免整格 None，哪怕是第三語言也好過 None）
        for v in by_lang.values():
            if _is_non_empty_string(v):
                return str(v)

    # 4. legacy 欄位
    if _is_non_empty_string(legacy_value):
        return str(legacy_value)

    return None


def _is_non_empty_string(v: Any) -> bool:
    return isinstance(v, str) and v != ""
