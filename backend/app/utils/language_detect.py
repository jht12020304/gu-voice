"""
LLM 輸出語言粗略偵測（heuristic）。

SOAPGenerator / RedFlagDetector 對 LLM 下 system prompt 時都會附上
硬性輸出語言規定，但模型偶爾會誤判（特別是在對話原文混雜語言時）。
本模組提供一個低成本的 sanity check：

    detect_text_language(text) → "zh-TW" | "en-US" | None

用途：
- 偵測到輸出語言與要求不符時 log warning（不 raise，避免阻斷 UX）
- 單元測試可用來斷言 mock LLM 輸出符合語言期望

實作限制：
- 純 heuristic，不可靠用於法遵或授權檢查
- 只分「中文（CJK）主」與「英文（ASCII）主」兩類
- 空字串、代碼片段、公式會回 None（歧義過大）
"""

from __future__ import annotations

from typing import Optional

_MIN_MEANINGFUL_CHARS = 4
_CJK_THRESHOLD = 0.30  # CJK 佔可辨識字元 30% 以上 → 視為中文
_ASCII_THRESHOLD = 0.80  # ASCII 字母佔 80% 以上 → 視為英文


def _is_cjk(ch: str) -> bool:
    """CJK 統一漢字 + 擴充 A + Hiragana + Katakana（覆蓋常見中日韓文字）。"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
    )


def detect_text_language(text: Optional[str]) -> Optional[str]:
    """
    回傳 "zh-TW"（CJK 為主）、"en-US"（ASCII 字母為主）、或 None（歧義 / 太短）。
    """
    if not text:
        return None

    cjk_count = 0
    ascii_alpha_count = 0
    meaningful_total = 0

    for ch in text:
        if ch.isspace() or not ch.isprintable():
            continue
        meaningful_total += 1
        if _is_cjk(ch):
            cjk_count += 1
        elif "a" <= ch.lower() <= "z":
            ascii_alpha_count += 1

    if meaningful_total < _MIN_MEANINGFUL_CHARS:
        return None

    cjk_ratio = cjk_count / meaningful_total
    ascii_ratio = ascii_alpha_count / meaningful_total

    if cjk_ratio >= _CJK_THRESHOLD:
        return "zh-TW"
    if ascii_ratio >= _ASCII_THRESHOLD:
        return "en-US"
    return None


def matches_expected_language(text: Optional[str], expected: Optional[str]) -> bool:
    """
    True 代表文字與預期語言一致；當偵測回 None（歧義）一律視為通過，
    避免短字串 / 純數字 / ICD-10 代碼等誤報。
    """
    detected = detect_text_language(text)
    if detected is None:
        return True
    return detected == expected
