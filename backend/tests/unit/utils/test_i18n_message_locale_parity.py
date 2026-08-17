"""
結構性守門：`app.utils.i18n_messages.MESSAGES` 的 5 語 locale parity。

為什麼需要這支測試（而不是靠既有的 test_i18n_messages.py）
------------------------------------------------------------
既有的 `test_every_key_has_every_active_locale` 只強制 `settings.ACTIVE_LANGUAGES`
（= zh-TW / en-US 兩語），ja-JP / ko-KR / vi-VN 被當成 best-effort 放行。
但 `get_message()` 對缺譯是**靜默** fallback 到 `DEFAULT_LANGUAGE`（zh-TW），
不 raise、不 warning，所以缺譯在日/韓/越場次的表現是「拿到一段中文」而不是「壞掉」：

  * `alert.rule_match_reason` 只有兩語 → 日文場次寫進 DB 的
    `red_flag_alerts.trigger_reason` 是「關鍵字比對：「尿閉」」。
  * `llm.red_flag_language_instruction` 只有兩語 → 語意層被指示用「繁體中文」輸出，
    於是 `description` / `suggested_actions` 全中文。
  * 而 `title` 另有 `display_title_by_lang`（5 語齊全）所以是對的
    → 肉眼很容易誤判成「已經在地化了」。

因此這裡把門檻拉到 `settings.SUPPORTED_LANGUAGES`（LANGUAGE_MAP 全部 locale，含 beta），
並補上幾道「就算 key 有值也可能是錯的」的內容檢查（placeholder 遺失、中文漏在
韓/越字串裡、複製貼上把中文留在別的 locale）。

允許例外
--------
`PARTIAL_LOCALE_ALLOWLIST` 是唯一的豁免出口，且必須寫理由。
目前是空的 —— MESSAGES 依設計只收「會寫進 DB 或送到使用者眼前」的字串
（純內部 log 訊息不進這張表），所以沒有任何 key 應該只支援部分語言。
"""

from __future__ import annotations

import re
import string

import pytest

from app.core.config import settings
from app.utils.i18n_messages import MESSAGES, get_message

# ── 豁免清單（key → 只支援部分語言的理由）─────────────────────
# 空 dict = 沒有任何 key 可以缺譯。要加入必須寫明理由，並在 code review 說明
# 為什麼該 key 永遠不會以其他語言送到使用者眼前。
PARTIAL_LOCALE_ALLOWLIST: dict[str, str] = {}

# 所有 locale（含 beta 的 ja-JP / ko-KR / vi-VN）。
# 用 SUPPORTED_LANGUAGES 而非寫死清單：LANGUAGE_MAP 新增語言時這支測試會自動跟著變嚴。
ALL_LOCALES = tuple(settings.SUPPORTED_LANGUAGES)

_FORMATTER = string.Formatter()
# CJK 統一表意文字（中文漢字）；日文可合法含漢字，韓文/越南文不行。
_HAN = re.compile(r"[一-鿿㐀-䶿]")
# 平假名 + 片假名：正常的日文句子一定會有假名，全漢字通常代表根本沒翻。
_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯]")


def _placeholders(template: str) -> set[str]:
    """取出 str.format 的 named placeholder 集合。"""
    return {name for _, name, _, _ in _FORMATTER.parse(template) if name}


ALL_KEYS = sorted(MESSAGES.keys())
ENFORCED_KEYS = [k for k in ALL_KEYS if k not in PARTIAL_LOCALE_ALLOWLIST]


# ── 1. 核心：每個 key 都要有全部 5 語 ────────────────────────
@pytest.mark.parametrize("key", ENFORCED_KEYS)
def test_every_message_key_covers_all_supported_languages(key: str) -> None:
    """缺一語 = 該語系場次會靜默拿到中文並寫進 DB，必須在 CI 就擋掉。"""
    entry = MESSAGES[key]
    missing = [loc for loc in ALL_LOCALES if not entry.get(loc)]
    assert not missing, (
        f"i18n key {key!r} 缺 {missing} 翻譯。get_message() 不會 raise，"
        f"只會靜默 fallback 到 {settings.DEFAULT_LANGUAGE} → 該語系場次會拿到中文字串。"
        f"請補齊，或在 PARTIAL_LOCALE_ALLOWLIST 寫明理由。"
    )


def test_partial_locale_allowlist_has_no_stale_or_unjustified_entries() -> None:
    """豁免清單不得殘留已刪除的 key，也不得沒寫理由。"""
    for key, reason in PARTIAL_LOCALE_ALLOWLIST.items():
        assert key in MESSAGES, f"PARTIAL_LOCALE_ALLOWLIST 殘留已不存在的 key: {key!r}"
        assert reason.strip(), f"PARTIAL_LOCALE_ALLOWLIST[{key!r}] 必須寫明豁免理由"


def test_supported_languages_covers_the_five_product_locales() -> None:
    """若有人從 LANGUAGE_MAP 拿掉語言，上面的 parity 測試會悄悄變寬鬆 —— 這裡釘住。"""
    assert set(ALL_LOCALES) >= {"zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"}


# ── 2. 有值也可能是錯的：placeholder 必須跨語一致 ──────────────
@pytest.mark.parametrize("key", ALL_KEYS)
def test_placeholder_set_identical_across_locales(key: str) -> None:
    """某語漏掉 {keyword} → 那語系的 trigger_reason 會少掉關鍵字，字串本身卻「有翻譯」。"""
    entry = MESSAGES[key]
    expected = _placeholders(entry[settings.DEFAULT_LANGUAGE])
    for locale in ALL_LOCALES:
        if locale not in entry:
            continue
        assert _placeholders(entry[locale]) == expected, (
            f"i18n key {key!r} 的 {locale} placeholder 與 "
            f"{settings.DEFAULT_LANGUAGE} 不一致："
            f"{sorted(_placeholders(entry[locale]))} != {sorted(expected)}"
        )


# ── 3. 有值也可能是中文：內容層級的漏翻偵測 ────────────────────
@pytest.mark.parametrize("key", ALL_KEYS)
@pytest.mark.parametrize("locale", ["ko-KR", "vi-VN"])
def test_korean_and_vietnamese_values_contain_no_han(key: str, locale: str) -> None:
    """韓文/越南文字串不該出現漢字 —— 出現就是複製貼上把中文留下來了。"""
    value = MESSAGES[key].get(locale)
    if not value:
        pytest.skip(f"{key} 無 {locale} 值（由 parity 測試負責報錯）")
    hits = _HAN.findall(value)
    assert not hits, f"i18n key {key!r} 的 {locale} 值殘留漢字 {hits}：{value!r}"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_japanese_values_are_actually_japanese(key: str) -> None:
    """日文可合法含漢字，改用「必須有假名」＋「不得與中文逐字相同」偵測漏翻。"""
    entry = MESSAGES[key]
    value = entry.get("ja-JP")
    if not value:
        pytest.skip(f"{key} 無 ja-JP 值（由 parity 測試負責報錯）")
    assert value != entry["zh-TW"], f"i18n key {key!r} 的 ja-JP 與 zh-TW 逐字相同（未翻譯）"
    assert _KANA.search(value), f"i18n key {key!r} 的 ja-JP 不含任何假名，疑似直接貼中文：{value!r}"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_korean_values_are_actually_korean(key: str) -> None:
    value = MESSAGES[key].get("ko-KR")
    if not value:
        pytest.skip(f"{key} 無 ko-KR 值（由 parity 測試負責報錯）")
    assert _HANGUL.search(value), f"i18n key {key!r} 的 ko-KR 不含諺文：{value!r}"


# ── 4. 行為層：走 get_message() 真的拿得到在地化字串 ─────────────
# 本次事故的直接受害 key：全部會寫進 red_flag_alerts 或決定紅旗 LLM 的輸出語言。
RED_FLAG_KEYS = [
    "alert.rule_match_reason",
    "alert.regex_match_reason",
    "alert.combined_trigger_reason",
    "alert.unknown_title",
    "alert.semantic_default_title",
    "llm.red_flag_language_instruction",
]


@pytest.mark.parametrize("key", RED_FLAG_KEYS)
@pytest.mark.parametrize("locale", ["ja-JP", "ko-KR", "vi-VN"])
def test_red_flag_keys_do_not_fall_back_to_chinese(key: str, locale: str) -> None:
    """回歸測試：日/韓/越場次的紅旗文字曾整段退回中文（trigger_reason 寫進 DB）。"""
    localized = get_message(key, locale)
    assert localized != MESSAGES[key]["zh-TW"], (
        f"{key} 在 {locale} 退回了 zh-TW —— 該語系場次的紅旗文字會是中文"
    )
    if locale in ("ko-KR", "vi-VN"):
        assert not _HAN.findall(localized), f"{key} 的 {locale} 輸出含漢字：{localized!r}"


def test_rule_match_reason_renders_keyword_in_every_locale() -> None:
    """trigger_reason 是寫進 DB 的欄位：每一語都必須把關鍵字帶出來。"""
    for locale in ALL_LOCALES:
        rendered = get_message("alert.rule_match_reason", locale, keyword="尿閉")
        assert "尿閉" in rendered, f"{locale} 的 trigger_reason 沒帶出關鍵字：{rendered!r}"
        assert "{keyword}" not in rendered


# ── 5. 病患面措辭鐵律（院內候診 kiosk）──────────────────────
# 病患已在現場等看診 → 只能講「請稍候等看診 / 請告知現場醫護」，
# 不可用含糊催就醫的講法。這條在 ja/ko/vi 一樣適用。
# 註：soap.* 是醫師端報告用語（讀者是臨床人員），刻意不在此清單內。
PATIENT_FACING_KEYS = [
    "ws.initial_greeting",
    "ws.ai_empty_retry_fallback",
    "ws.session_terminated_completed_notice",
    "ws.session_terminated_aborted_notice",
    "llm.conversation_red_flag_alert_rule",
    "llm.conversation_wrap_up_rule",
    # 2026-07-27 Gate 補上：紅旗橫幅／終止提示的病患面文案。
    # 這三條**直接**渲染在病患的 kiosk 畫面上（red_flag_alert payload 的
    # patientNotice 與 session_status 的終止提示），是本輪 BLOCKER #2/#3 的
    # 產物，漏掉就等於新的病患面字串沒有任何措辭鐵律守門。
    "ws.red_flag_patient_notice_notified",
    "ws.red_flag_patient_notice_flagged",
    "ws.session_terminated_aborted_notice_unnotified",
]

# 各語言「含糊催就醫」的典型講法；出現即違反鐵律。
BANNED_URGENT_CARE_PHRASES: dict[str, tuple[str, ...]] = {
    "zh-TW": ("盡速就醫", "儘速就醫", "立即就醫", "趕快去醫院", "前往急診"),
    "en-US": ("seek medical attention", "go to the hospital", "go to the emergency"),
    "ja-JP": ("すぐに病院", "至急病院", "早めに受診", "救急外来を受診"),
    "ko-KR": ("즉시 병원", "빨리 병원", "응급실로"),
    "vi-VN": ("đi khám ngay", "đến bệnh viện ngay", "đi cấp cứu ngay"),
}


@pytest.mark.parametrize("key", PATIENT_FACING_KEYS)
@pytest.mark.parametrize("locale", ALL_LOCALES)
def test_patient_facing_keys_use_kiosk_wording(key: str, locale: str) -> None:
    """院內 kiosk：病患已在現場，禁用含糊的「盡速就醫」類措辭（5 語都適用）。"""
    value = MESSAGES[key].get(locale)
    if not value:
        pytest.skip(f"{key} 無 {locale} 值（由 parity 測試負責報錯）")
    lowered = value.lower()
    for phrase in BANNED_URGENT_CARE_PHRASES[locale]:
        assert phrase.lower() not in lowered, (
            f"病患面 key {key!r} 的 {locale} 含催就醫措辭「{phrase}」；"
            f"kiosk 情境請改為「請稍候等看診／請告知現場醫護」。"
        )
