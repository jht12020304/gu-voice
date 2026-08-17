"""第三輪 Gate 的雙向探針語料（獨立樣本，入庫為迴歸測試）。

**為什麼需要這一份，而既有的紅旗測試檔不夠**
前兩輪各犯了一次「只往單一方向加測試」：
  第一輪只加「必須命中」→ 改出 over-trigger；
  第二輪只加「不該命中」→ 改出 under-trigger。
第三輪 Gate 用**完全新寫**的雙向語料重跑，結果 63 筆裡有 17 筆不符預期
（11 筆漏報 + 6 筆誤報），而當時既有的 996 條紅旗測試**全綠**——因為那些測試的
語料與實作互相配適（e2e persona 台詞剛好讓關鍵字相鄰）。

所以這個檔案的價值不在條數，而在**它是獨立樣本**：
  - 語料全部為本輪新寫，不是從 `scripts/e2e_realopenai/driver.py` 的 persona 台詞、
    也不是從 `test_red_flag_over_trigger.py` / `test_red_flag_cooccurrence.py`
    抄來的（由 `test_corpus_is_an_independent_sample` 結構性守住）。
  - 每一個方向都有對稱的另一側：MUST_FIRE 的語序變體 ↔ MUST_NOT_FIRE 的近似句，
    五種語言各自在兩側都有覆蓋。

⚠️ 維護規則：修偵測邏輯時**不可以**從這裡刪案例來讓測試變綠。要改期望值必須
   寫明臨床理由，並在**另一個方向**補一筆對照，否則就是拿實作去配適測試。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import RedFlagDetector

CANONICAL = "testicular_pain_severe"


@pytest.fixture()
def detector(monkeypatch):
    monkeypatch.setattr(
        RedFlagDetector, "_negation_guard_enabled", lambda self: True, raising=False
    )
    det = RedFlagDetector.__new__(RedFlagDetector)
    det._rules = [
        {
            "canonical_id": flag["canonical_id"],
            "name": flag["title"],
            "keywords": list(flag.get("triggers") or []),
            "severity": flag["severity"],
            "regex_pattern": None,
        }
        for flag in URO_RED_FLAGS
    ]
    return det


def _fired(detector, text: str) -> bool:
    """規則層對 testicular_pain_severe 是否命中（＝會不會 abort 整場問診）。"""
    return any(
        alert.get("canonical_id") == CANONICAL
        for alert in detector._rule_based_detect(text)
    )


# ─────────────────────────────────────────────────────────────────
# A. 主 agent 的直接探針表（19 筆）——修復前 7 筆漏報，全部釘在這裡
# ─────────────────────────────────────────────────────────────────
PROBE_MUST_FIRE: tuple[tuple[str, str], ...] = (
    ("zh-TW", "我左邊睪丸兩個小時前突然劇痛，還吐了"),
    ("en-US", "my left testicle suddenly started hurting badly and i threw up"),
    ("ja-JP", "二時間前に急に左の睾丸が激しく痛くなり、吐き気もあります"),
    ("ko-KR", "두 시간 전에 갑자기 왼쪽 고환이 심하게 아프고 토했어요"),
    ("vi-VN", "hai tiếng trước tinh hoàn trái đau dữ dội đột ngột, tôi buồn nôn"),
    # 「描述當前症狀 ＋ 順便問掛哪一科」＝院內 kiosk 最常見的真實情境
    ("zh-TW", "請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科"),
    ("zh-TW", "醫生請問一下我今天早上睪丸突然很痛痛到吐我不知道要掛哪一科"),
    ("en-US", "my right testicle is in severe pain since this morning"),
    ("en-US", "sudden severe pain in my testicle"),
)

PROBE_MUST_NOT_FIRE: tuple[tuple[str, str], ...] = (
    ("zh-TW", "我睪丸這半年來偶爾會有一點悶悶的不舒服"),
    ("en-US", "my testicle has had a mild dull ache on and off for months"),
    ("ja-JP", "半年ほど前から睾丸が時々鈍く重い感じがします"),
    ("ko-KR", "반년 전부터 고환이 가끔 묵직하고 불편해요"),
    ("vi-VN", "mấy tháng nay tinh hoàn thỉnh thoảng hơi tưng tức khó chịu"),
    ("en-US", "my eyeball hurts a lot today"),
    ("zh-TW", "我想問睪丸痛要看哪一科"),
    ("zh-TW", "小便會痛，睪丸痛倒是沒有"),
    ("zh-TW", "以前睪丸痛過，但現在完全好了"),
    ("zh-TW", "睪丸痛好幾個月了，不太嚴重"),
)


# ─────────────────────────────────────────────────────────────────
# B. 語序變體：部位詞與修飾詞之間插入 2–8 字的時間／方位／程度語
#    （＝「相鄰子字串」這個錯誤實作方式的直接反證）
# ─────────────────────────────────────────────────────────────────
WORD_ORDER_MUST_FIRE: tuple[tuple[str, str], ...] = (
    ("zh-TW", "我右邊那顆睪丸從半夜三點開始劇烈疼痛，冒冷汗"),
    ("zh-TW", "睪丸大概一個鐘頭以前毫無預警地劇痛起來"),
    ("zh-TW", "陰囊右側在剛剛吃完晚餐後突然腫脹又痛得受不了"),
    ("zh-TW", "蛋蛋今天下午四點多的時候忽然痛到我站不直"),
    ("zh-TW", "左側睪丸自清晨起劇烈抽痛，伴隨反胃"),
    ("en-US", "the pain in my right testicle came on abruptly around midnight"),
    ("en-US", "my testicle, about ninety minutes ago, became excruciating"),
    ("en-US", "the scrotum on the left side swelled up and got extremely painful"),
    ("en-US", "one of my testicles started hurting acutely after dinner"),
    ("en-US", "my left ball has been agonizing since roughly 4 am"),
    ("ja-JP", "右の睾丸が今朝六時ごろから突然ひどく痛み出しました"),
    ("ja-JP", "陰嚢の左側が一時間ほど前に急激に腫れて激痛です"),
    ("ja-JP", "精巣がさっきトイレに行った後で急に耐えられない痛みになりました"),
    ("ja-JP", "キンタマが夜中の二時ごろ突然ものすごく痛くなりました"),
    ("ko-KR", "오른쪽 고환이 오늘 새벽 세 시쯤 갑자기 극심하게 아팠어요"),
    ("ko-KR", "음낭 왼쪽이 한 시간 전부터 급격히 붓고 심하게 아픕니다"),
    ("ko-KR", "고환이 저녁 먹고 나서 갑작스럽게 참을 수 없이 아파요"),
    ("ko-KR", "불알이 아까 화장실 다녀온 뒤에 갑자기 너무 아파요"),
    ("vi-VN", "tinh hoàn bên phải của tôi từ lúc nửa đêm bỗng nhiên đau dữ dội"),
    ("vi-VN", "bìu bên trái khoảng một tiếng trước sưng lên và đau đột ngột"),
    ("vi-VN", "tinh hoàn sau khi tôi đi vệ sinh thì đau kinh khủng"),
    ("vi-VN", "hòn dái của tôi lúc sáng sớm tự nhiên đau dữ dội"),
)


# ─────────────────────────────────────────────────────────────────
# C. 反例：慢性／否定／行政詢問／假設／過去（五語各 ≥3 筆）
#    措辭與 test_red_flag_over_trigger.py **不重複**，互為獨立樣本。
# ─────────────────────────────────────────────────────────────────
CONTEXT_MUST_NOT_FIRE: tuple[tuple[str, str], ...] = (
    ("zh-TW", "這一兩年睪丸偶爾隱隱作痛，休息一下就好了"),
    ("zh-TW", "我最近排尿有灼熱感，睪丸倒是完全不痛也沒腫"),
    ("zh-TW", "請問陰囊突然劇痛這種狀況在貴院是掛哪一個科別"),
    ("zh-TW", "如果以後睪丸突然劇烈疼痛，我應該怎麼處理"),
    ("zh-TW", "十年前睪丸曾經急性劇痛，開完刀之後就再也沒發作"),
    ("en-US", "for the past year my testicle occasionally feels slightly sore"),
    ("en-US", "i have burning when i pee, but no sudden severe testicle pain at all"),
    ("en-US", "which clinic should i book if a testicle suddenly becomes severely painful"),
    ("en-US", "if my testicle ever hurts acutely, should i call the clinic first"),
    ("en-US", "my eyeballs suddenly started hurting after staring at the screen"),
    ("ja-JP", "ここ一年ほど睾丸がたまに少し重く感じる程度です"),
    ("ja-JP", "排尿時にしみますが、睾丸が急に激しく痛むことはありません"),
    ("ja-JP", "陰嚢が突然激しく痛む場合は何科を受診すればよいか教えてください"),
    ("ja-JP", "子供のころ精巣が急に激しく痛みましたが、手術後は完治しました"),
    ("ko-KR", "작년부터 고환이 가끔 살짝 뻐근한 정도예요"),
    ("ko-KR", "소변볼 때 따갑지만 고환이 갑자기 심하게 아프지는 않습니다"),
    ("ko-KR", "음낭이 갑자기 극심하게 아프면 무슨 과로 가야 하는지 궁금합니다"),
    ("ko-KR", "예전에 고환이 갑자기 심하게 아팠지만 수술 후에 완전히 나았어요"),
    ("vi-VN", "cả năm nay tinh hoàn thỉnh thoảng chỉ hơi ê ẩm nhẹ"),
    ("vi-VN", "tôi bị rát khi đi tiểu nhưng tinh hoàn không hề đau dữ dội đột ngột"),
    ("vi-VN", "nếu bìu đột nhiên đau dữ dội thì nên đăng ký khám khoa nào ạ"),
    ("vi-VN", "hồi trước tinh hoàn từng đau dữ dội đột ngột nhưng mổ xong đã khỏi hẳn"),
)

ALL_MUST_FIRE = PROBE_MUST_FIRE + WORD_ORDER_MUST_FIRE
ALL_MUST_NOT_FIRE = PROBE_MUST_NOT_FIRE + CONTEXT_MUST_NOT_FIRE


@pytest.mark.parametrize("language,text", ALL_MUST_FIRE, ids=lambda v: v[:28])
def test_must_fire(detector, language, text):
    assert _fired(detector, text), f"{language} 漏報（under-trigger）：{text!r}"


@pytest.mark.parametrize("language,text", ALL_MUST_NOT_FIRE, ids=lambda v: v[:28])
def test_must_not_fire(detector, language, text):
    assert not _fired(detector, text), f"{language} 誤報（over-trigger）：{text!r}"


# ─────────────────────────────────────────────────────────────────
# 結構性不變式：語料表本身的性質（防止未來被單向化 / 被實作配適）
# ─────────────────────────────────────────────────────────────────
LANGUAGES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_is_covered_in_both_directions(language):
    """五語言都必須在**兩個方向**各有語料，否則這份表又退化成單向。"""
    fire = [t for lang, t in ALL_MUST_FIRE if lang == language]
    miss = [t for lang, t in ALL_MUST_NOT_FIRE if lang == language]
    assert len(fire) >= 3, f"{language} 的 MUST_FIRE 語料不足：{len(fire)}"
    assert len(miss) >= 3, f"{language} 的 MUST_NOT_FIRE 語料不足：{len(miss)}"


def test_corpus_is_bidirectional_and_balanced():
    """兩個方向的筆數不得嚴重失衡（失衡＝又在往單一方向加測試）。"""
    fire, miss = len(ALL_MUST_FIRE), len(ALL_MUST_NOT_FIRE)
    assert min(fire, miss) * 2 >= max(fire, miss), f"雙向失衡：{fire} vs {miss}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def test_corpus_is_an_independent_sample():
    """B/C 兩節的語料**不得**是從 e2e persona 台詞或既有紅旗測試檔抄來的。

    這是本檔存在的理由：一旦語料與被測實作同源，測試就只是在覆誦實作。
    比對方式為整句字面比對（大小寫/空白正規化後）。

    ⚠️ 檢查範圍刻意排除 A 節（`PROBE_*`）：那 19 筆是上游交下來、**要求原樣重跑**
    的探針表，本來就與既有測試檔重疊，是迴歸釘子不是新樣本。獨立性的主張只涵蓋
    本輪新寫的 B（語序變體）與 C（語境反例）。
    """
    fresh = WORD_ORDER_MUST_FIRE + CONTEXT_MUST_NOT_FIRE
    sources = [
        _repo_root() / "scripts" / "e2e_realopenai" / "driver.py",
        Path(__file__).with_name("test_red_flag_over_trigger.py"),
        Path(__file__).with_name("test_red_flag_cooccurrence.py"),
        Path(__file__).with_name("test_red_flag_torsion_and_context.py"),
    ]
    blobs = []
    for path in sources:
        if path.exists():
            blobs.append((path.name, re.sub(r"\s+", " ", path.read_text("utf-8"))))
    assert blobs, "找不到任何比對來源，這條結構性測試會變成空跑"

    overlaps = []
    for _language, text in fresh:
        needle = re.sub(r"\s+", " ", text).strip()
        for name, blob in blobs:
            if needle in blob:
                overlaps.append((name, text))
    assert not overlaps, f"語料與既有來源重複（＝拿實作配適測試）：{overlaps}"


def test_probe_table_cases_are_all_retained():
    """主 agent 探針表的 19 筆必須全部留在語料裡，不得為了讓測試變綠而拿掉。"""
    assert len(PROBE_MUST_FIRE) + len(PROBE_MUST_NOT_FIRE) == 19


def test_word_order_variants_defeat_adjacent_substring_matching():
    """語序變體必須**真的**是非相鄰的，否則這一節可以被相鄰子字串實作矇混過關。

    做法：把每一筆 MUST_FIRE 語序變體拿去比對 catalogue 裡所有相鄰 trigger，
    至少要有一半完全不含任何相鄰 trigger ——那些只能靠共現組接住。
    """
    flag = next(f for f in URO_RED_FLAGS if f["canonical_id"] == CANONICAL)
    triggers = [t.lower() for t in flag.get("triggers") or []]
    for lang_triggers in (flag.get("triggers_by_lang") or {}).values():
        triggers.extend(t.lower() for t in lang_triggers)

    without_adjacent = [
        text
        for _language, text in WORD_ORDER_MUST_FIRE
        if not any(t in text.lower() for t in triggers)
    ]
    assert len(without_adjacent) * 2 >= len(WORD_ORDER_MUST_FIRE), (
        "語序變體大多含相鄰 trigger → 這一節證明不了共現組是承重的"
        f"（{len(without_adjacent)}/{len(WORD_ORDER_MUST_FIRE)}）"
    )
