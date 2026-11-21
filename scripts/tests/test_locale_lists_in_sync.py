"""支援語系清單在三端是手抄的——這支測試釘住它們不得漂移。

來源：
- backend: app/models/enums.py 的 SupportedLanguage（LANGUAGE_MAP 的 key 由它而來）
- web:     frontend/src/i18n/index.ts 的 SUPPORTED_LANGUAGES
- iOS:     ios_native/App/Configuration.swift 的 AppLanguage 與 Apple 資源
用 regex 讀原始碼而非 import，三端工具鏈都不必裝。
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.check_translations import IOS_LOCALES

REPO = Path(__file__).resolve().parents[2]
LOCALE = r"[a-z]{2}-[A-Z]{2}"


def _codes(path: str, block_pattern: str) -> set[str]:
    src = (REPO / path).read_text(encoding="utf-8")
    m = re.search(block_pattern, src, re.S)
    assert m, f"{path}: locale list not found"
    return set(re.findall(rf"[\"']({LOCALE})[\"']", m.group(1)))


def test_backend_web_and_ios_locale_lists_match() -> None:
    backend = _codes(
        "backend/app/models/enums.py",
        r"class SupportedLanguage\(str, Enum\):(.*?)(?:\n\S|\Z)",
    )
    web = _codes(
        "frontend/src/i18n/index.ts",
        r"export const SUPPORTED_LANGUAGES = \[(.*?)\]",
    )
    native = _codes(
        "ios_native/App/Configuration.swift",
        r"enum AppLanguage[^\n]+\{(.*?)var id",
    )
    assert backend == web == native == IOS_LOCALES.keys()
    swift = (REPO / "ios_native/App/Configuration.swift").read_text()
    cases = dict(re.findall(rf'case (\w+) = "({LOCALE})"', swift))
    resource_codes = dict(re.findall(r'case \.(\w+): "([\w-]+)"', swift.split("var localization:")[1].split("}", 1)[0]))
    assert {api: resource_codes[case] for case, api in cases.items()} == IOS_LOCALES
    app = REPO / "ios_native/App"
    assert {path.parent.stem for path in app.glob("*.lproj/Kiosk.strings")} == set(IOS_LOCALES.values())
