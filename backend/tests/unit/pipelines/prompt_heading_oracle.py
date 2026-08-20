"""偽區段注入測試的共用 oracle：「這一行在 LLM 眼中是不是一個 markdown 標題」。

兩個消毒測試檔（D-1 對話 prompt、D-1b SOAP prompt）共用同一份判準,所以只會有
**一份**定義會漂移;拆兩份的話,補了一邊忘了另一邊不會有任何訊號。

## 為什麼不是 `line.lstrip().startswith("#")`（2026-08-21 P1 複驗）

`str.lstrip()` 只吃 `str.isspace()` 為真的字元。**零寬但不是空白**的字元（U+2066
LRI、U+200B ZWSP、U+034F CGJ…）留在行首時:

    "\\u2066## Consultation Transcript"

`lstrip()` 拿不掉那個 U+2066 → `startswith("#")` 為 False → oracle 判「這不是標題」
＝ **假 PASS**。但那個字元在任何介面上都不佔寬度,LLM 讀到的仍然是一個 `##` 標題。
於是同一個洞會從「不可見字元」那一側整條繞回來——消毒漏掉一個碼位,測試就跟著漏掉。

修法是**先剝掉不可見字元再判行首**。這裡刻意用 Unicode **general category**
（Cc/Cf/Zl/Zp）而不是複製 `shared._PROMPT_UNSAFE_CHARS` 的字面清單:oracle 要獨立於
實作,而且 category 天生是實作那張白名單的**超集**——實作漏收哪個碼位,這裡照樣看得見。
（category 是 Mn 的零寬字元不在 Cc/Cf/Zl/Zp 裡,故另列 `_INVISIBLE_MARKS`。）
"""

from __future__ import annotations

import unicodedata

# category 判不出來的零寬字元（都是 Mn——把整個 Mn 排除會連越南文/韓文的組合符號
# 一起吃掉,對「行首是不是 `#`」這個問題沒必要,所以逐個列舉）。
_INVISIBLE_MARKS = frozenset(
    {
        "͏",  # COMBINING GRAPHEME JOINER
        "឴",  # KHMER VOWEL INHERENT AQ
        "឵",  # KHMER VOWEL INHERENT AA
    }
)
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

# 半形與全形的 `#`——消毒層兩個都當標題記號,oracle 也必須兩個都認。
HEADING_MARKS = ("#", "＃")


def strip_invisible(text: str) -> str:
    """剝掉零寬／格式／控制字元（不動空白,`lstrip()` 自己會處理空白）。"""
    return "".join(
        ch
        for ch in text
        if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
        and ch not in _INVISIBLE_MARKS
    )


def is_heading_line(line: str) -> bool:
    return strip_invisible(line).lstrip().startswith(HEADING_MARKS)


def heading_lines(prompt: str) -> list[str]:
    """prompt 裡所有「LLM 會讀成標題」的行,原樣回傳（比對用逐字相等）。

    回傳的是**原行**不是剝過的行:基準與注入版兩邊都原樣比,多出來一個逐字相同的
    偽標題時 list 長度就對不上（`['## X'] != ['## X', '## X']`）。
    """
    return [line for line in prompt.splitlines() if is_heading_line(line)]
