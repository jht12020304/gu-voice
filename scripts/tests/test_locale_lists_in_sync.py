"""支援語系清單在三端是手抄的——這支測試釘住它們不得漂移。

來源：
- backend: app/models/enums.py 的 SupportedLanguage（LANGUAGE_MAP 的 key 由它而來）
- web:     frontend/src/i18n/index.ts 的 SUPPORTED_LANGUAGES
- iOS:     flutter_app/lib/core/router/lng.dart 的 supportedLanguages
用 regex 讀原始碼而非 import，三端工具鏈都不必裝。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCALE = r"[a-z]{2}-[A-Z]{2}"


def _codes(path: str, block_pattern: str) -> set[str]:
    src = (REPO / path).read_text(encoding="utf-8")
    m = re.search(block_pattern, src, re.S)
    assert m, f"{path}: locale list not found"
    return set(re.findall(rf"[\"']({LOCALE})[\"']", m.group(1)))


def test_backend_web_and_flutter_locale_lists_match() -> None:
    backend = _codes(
        "backend/app/models/enums.py",
        r"class SupportedLanguage\(str, Enum\):(.*?)(?:\n\S|\Z)",
    )
    web = _codes(
        "frontend/src/i18n/index.ts",
        r"export const SUPPORTED_LANGUAGES = \[(.*?)\]",
    )
    flutter = _codes(
        "flutter_app/lib/core/router/lng.dart",
        r"const supportedLanguages = \[(.*?)\];",
    )
    assert backend, "backend enum parsed as empty"
    assert backend == web == flutter, {
        "backend": sorted(backend), "web": sorted(web), "flutter": sorted(flutter)
    }
