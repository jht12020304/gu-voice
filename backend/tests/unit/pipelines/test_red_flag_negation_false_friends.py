"""否定線索「假朋友」——守衛自己製造的漏報（**跨 5 個 critical 紅旗 × 5 語言**）。

為什麼要有這個檔案
────────────────────────────────────────
規則層的否定守衛用**字面**否定詞（沒／無／not／ない／없／không…）判斷「病患是不是
在否認這個症狀」。但每一種語言的否定詞都有一整族固定搭配，字面帶否定、語意卻是
**敘事、加強語氣、或症狀本身**：

    「今天早上開始痛，沒多久睪丸就腫起來痛到吐」   沒多久＝過了一小段時間（敘事）
    「痛到沒辦法忍了，尿不出來」                    沒辦法＝程度加強
    「i cannot stop vomiting, my testicle …」       cannot＝能力喪失，本身就是主訴
    「我慢できないほど痛くて、睾丸が急に…」         我慢できない＝加強語氣
    「참을 수 없이 아파서 고환이 갑자기 부었어요」   참을 수 없이＝加強語氣
    「tôi không thể chịu được, bìu sưng đau…」      không thể＝能力喪失

這些全部會被守衛當成否定 → **整句抹掉** → 規則層 0 命中 → under-triage（不可逆）。

2026-07-27 第四輪實測：下面 `FALSE_FRIEND_MUST_FIRE` 的 28 句，修復前 **26 句規則層
0 命中**。它橫跨全部 5 個 critical canonical（不是睪丸專屬）與全部 5 種語言。

前兩輪各只補了兩三個詞（「沒記錯／沒錯」「毫無預警」）就收手，於是同一個坑換個詞
就再踩一次。本檔的承諾是：**這是一族結構性問題，測試要按族施力，不是逐句釘個案。**

雙向對稱（鐵律）
────────────────────────────────────────
`FALSE_FRIEND_MUST_FIRE`（守衛不得抑制）與 `EXPLICIT_DENIAL_MUST_SUPPRESS`
（守衛必須抑制）必須成對存在。少了後者，前者可以靠「把否定守衛整個關掉」全過——
那會讓 E11 點名的誤 abort 全部回來。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector

# 真跑 scripts/e2e_realopenai/results/*.json 的 persona 台詞。本檔語料**不得**與它們
# 相同或互為子字串——第一輪 e2e 之所以全綠，就是因為 persona 台詞剛好與關鍵字互相
# 配適（「睪丸突然劇烈疼痛」讓「睪丸突然」相鄰），測到的是實作不是行為。
E2E_PERSONA_LINES = (
    "大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難。",
    "The hematuria started about 3 days ago.",
    "三天前開始，小便時看到整泡尿是紅色的。",
    "這三天以來，血尿一直都有。",
)


def _run(coro):
    return asyncio.run(coro)


class _FakeScalars:
    def all(self) -> list[Any]:
        return []


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()


class _FakeDB:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


@pytest.fixture
def detector(monkeypatch: pytest.MonkeyPatch) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = True
    det = RedFlagDetector(settings, _FakeDB())
    _run(det._load_rules())
    return det


def _canonicals(det: RedFlagDetector, text: str, language: str) -> set[str]:
    return {a["canonical_id"] for a in det._rule_based_detect(text, language)}


def _critical_hits(det: RedFlagDetector, text: str, language: str) -> list[tuple]:
    return [
        (a["canonical_id"], a.get("trigger_keywords"))
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# A. 守衛**不得**抑制：字面帶否定詞、語意是敘事／加強語氣／症狀本身
# ══════════════════════════════════════════════════════════════
# (id, language, text, 必須命中的 canonical_id)
FALSE_FRIEND_MUST_FIRE: list[tuple[str, str, str, str]] = [
    # ── zh-TW：(a) 時間敘事 ──
    ("zh-沒多久", "zh-TW", "今天早上開始痛，沒多久睪丸就腫起來痛到吐", "testicular_pain_severe"),
    ("zh-沒多久-retention", "zh-TW", "喝了水沒多久就完全尿不出來了", "urinary_retention"),
    ("zh-沒過多久", "zh-TW", "打完針沒過多久尿不出來，脹得很痛", "urinary_retention"),
    ("zh-沒兩分鐘", "zh-TW", "站起來沒兩分鐘睪丸就劇痛", "testicular_pain_severe"),
    ("zh-沒幾天", "zh-TW", "開刀沒幾天就尿不出來", "urinary_retention"),
    # ── zh-TW：(b) 轉折／意外 ──
    ("zh-沒想到", "zh-TW", "本來只是悶悶的，沒想到今天血尿很多，整個都是血", "gross_hematuria_heavy"),
    # ── zh-TW：(d) 能力喪失＝症狀本身 / 程度加強 ──
    ("zh-沒辦法", "zh-TW", "脹到沒辦法忍了，尿不出來", "urinary_retention"),
    ("zh-沒有辦法", "zh-TW", "痛到沒有辦法站著，尿不出來一整天了", "urinary_retention"),
    ("zh-沒力氣", "zh-TW", "痛到沒力氣，還一直高燒寒顫", "urosepsis"),
    ("zh-沒知覺", "zh-TW", "屁股那邊沒知覺，還有下肢無力", "cauda_equina_suspected"),
    # ── zh-TW：(e) 持續／程度加強 ──
    ("zh-沒完沒了", "zh-TW", "痛得沒完沒了，睪丸劇痛到想吐", "testicular_pain_severe"),
    # ── en-US ──
    (
        "en-cannot",
        "en-US",
        "i cannot stop vomiting, my testicle suddenly hurts so bad",
        "testicular_pain_severe",
    ),
    (
        "en-without-warning",
        "en-US",
        "without warning my testicle became excruciating",
        "testicular_pain_severe",
    ),
    (
        "en-no-idea",
        "en-US",
        "i have no idea why, my balls hurt so much since this morning",
        "testicular_pain_severe",
    ),
    (
        "en-not-sure",
        "en-US",
        "i am not sure what happened but i cannot urinate at all",
        "urinary_retention",
    ),
    (
        "en-no-relief",
        "en-US",
        "painkillers gave no relief and there is heavy bleeding in my urine",
        "gross_hematuria_heavy",
    ),
    (
        "en-not-able",
        "en-US",
        "i was not able to sleep, high fever and chills all night",
        "urosepsis",
    ),
    # ── ja-JP（可能形否定＋固定搭配）──
    (
        "ja-我慢できない",
        "ja-JP",
        "我慢できないほど痛くて、睾丸が急に腫れて痛みます",
        "testicular_pain_severe",
    ),
    ("ja-歩けない", "ja-JP", "歩けないくらい痛くて精巣が激しく痛みます", "testicular_pain_severe"),
    (
        "ja-仕方ない",
        "ja-JP",
        "仕方ないと思っていたら急に睾丸が激しく痛くなりました",
        "testicular_pain_severe",
    ),
    (
        "ja-信じられない",
        "ja-JP",
        "信じられないくらい急に睾丸が痛くなりました",
        "testicular_pain_severe",
    ),
    ("ja-たまらない", "ja-JP", "たまらなく痛くて、尿が出ないんです", "urinary_retention"),
    # ── ko-KR ──
    ("ko-참을수없이", "ko-KR", "참을 수 없이 아파서 고환이 갑자기 부었어요", "testicular_pain_severe"),
    ("ko-어쩔수없이", "ko-KR", "어쩔 수 없이 왔는데 고환이 심하게 아파요", "testicular_pain_severe"),
    ("ko-견딜수없", "ko-KR", "견딜 수 없을 만큼 아프고 소변이 안 나와요", "urinary_retention"),
    # ── vi-VN ──
    (
        "vi-không-chịu-nổi",
        "vi-VN",
        "đau không chịu nổi, tinh hoàn sưng đau đột ngột",
        "testicular_pain_severe",
    ),
    (
        "vi-chưa-bao-giờ-như",
        "vi-VN",
        "chưa bao giờ đau như vậy, tinh hoàn đau dữ dội",
        "testicular_pain_severe",
    ),
    (
        "vi-không-thể",
        "vi-VN",
        "tôi không thể chịu được, bìu sưng đau đột ngột",
        "testicular_pain_severe",
    ),
]


@pytest.mark.parametrize(
    "language,text,expected",
    [(lg, t, e) for _i, lg, t, e in FALSE_FRIEND_MUST_FIRE],
    ids=[i for i, _lg, _t, _e in FALSE_FRIEND_MUST_FIRE],
)
def test_false_friend_does_not_suppress_real_symptom(
    detector, language, text, expected
):
    """字面帶否定詞、語意是症狀陳述 → 規則層必須命中（漏報不可逆）。"""
    got = _canonicals(detector, text, language)
    assert expected in got, (
        f"否定守衛把真症狀陳述整句抹掉（under-triage）：{language} {text!r}\n"
        f"  期望命中 {expected}，實得 {sorted(got)}"
    )


# ══════════════════════════════════════════════════════════════
# B. 守衛**必須**抑制：病患明確、無歧義地否認了這個症狀
# ══════════════════════════════════════════════════════════════
# 沒有這一組，A 組可以靠「把否定守衛整個關掉」全過。
EXPLICIT_DENIAL_MUST_SUPPRESS: list[tuple[str, str, str]] = [
    ("zh-沒有-睪丸", "zh-TW", "我沒有睪丸劇痛"),
    ("zh-沒有-尿滯留", "zh-TW", "我沒有尿不出來的情形"),
    ("zh-沒有-血尿", "zh-TW", "沒有大量血尿"),
    ("zh-沒有-列舉", "zh-TW", "沒有高燒、寒顫、意識不清"),
    ("zh-無", "zh-TW", "無血塊"),
    # 「沒有注意到 X」是 TODO-E11 點名的明確否認，沒有任何症狀讀法 →
    # 假朋友表刻意**不**收「注意到」。這條就是釘住那個界線。
    ("zh-沒有注意到", "zh-TW", "我沒有注意到體重減輕"),
    # 「沒有完全…」是部分否認，不是加強語氣 → 假朋友表刻意不收裸「完」。
    ("zh-沒有完全", "zh-TW", "我沒有完全尿不出來"),
    ("en-no", "en-US", "no testicle pain at all"),
    ("en-denies", "en-US", "patient denies heavy bleeding"),
    ("en-without", "en-US", "without any testicle pain"),
    ("ja-ありません", "ja-JP", "睾丸の痛みはありません"),
    ("ja-なし", "ja-JP", "尿閉なし"),
    ("ko-없어요", "ko-KR", "고환이 아파요는 없어요"),
    ("vi-không", "vi-VN", "không có đau tinh hoàn dữ dội"),
    # 「chưa bao giờ bị đau…」＝從來沒有痛過（明確否認）；假朋友只收比較級的
    # 「chưa bao giờ đau như…」（從來沒有痛得像這樣＝加強語氣）。
    ("vi-chưa-bao-giờ-bị", "vi-VN", "tôi chưa bao giờ bị đau tinh hoàn dữ dội"),
]


@pytest.mark.parametrize(
    "language,text",
    [(lg, t) for _i, lg, t in EXPLICIT_DENIAL_MUST_SUPPRESS],
    ids=[i for i, _lg, _t in EXPLICIT_DENIAL_MUST_SUPPRESS],
)
def test_explicit_denial_still_suppressed(detector, language, text):
    """病患明確否認 → 仍必須抑制（否則 A 組等於把守衛關掉換來的）。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], f"明確否認被判 critical（會誤中止問診）：{language} {text!r} → {hits}"


def test_denial_of_non_critical_symptom_also_suppressed(detector):
    """non-critical 也要驗一筆：假朋友表不得把 high 的否定守衛一起打壞。"""
    assert "gross_hematuria" not in _canonicals(detector, "我沒有血尿", "zh-TW")
    assert "unexplained_weight_loss" not in _canonicals(
        detector, "我沒有注意到體重減輕", "zh-TW"
    )


# ══════════════════════════════════════════════════════════════
# C. 結構性守衛
# ══════════════════════════════════════════════════════════════


def test_corpus_is_not_copied_from_e2e_persona_lines():
    """本檔語料不得與 e2e persona 台詞相同或互為子字串。

    e2e 曾經全綠是因為 persona 台詞剛好與關鍵字互相配適（「睪丸突然劇烈疼痛」
    讓「睪丸突然」相鄰）。拿 persona 台詞當測資＝拿實作配適測試。
    """
    corpus = [t for _i, _lg, t, _e in FALSE_FRIEND_MUST_FIRE] + [
        t for _i, _lg, t in EXPLICIT_DENIAL_MUST_SUPPRESS
    ]
    for text in corpus:
        for persona in E2E_PERSONA_LINES:
            assert text != persona, text
            assert text not in persona, text
            assert persona not in text, text


def test_false_friend_corpus_covers_every_critical_canonical():
    """A 組必須橫跨**全部** critical canonical——這個 bug 不是睪丸專屬。

    第一次發現時只在睪丸那條被察覺，但根因在共用的 `_has_negation_cue`，
    5 個 critical 全中同一個坑。只測睪丸會讓下一次同型回歸再度靜默。
    """
    from app.pipelines.prompts.shared import URO_RED_FLAGS

    critical_ids = {
        f["canonical_id"] for f in URO_RED_FLAGS if f.get("severity") == "critical"
    }
    covered = {expected for _i, _lg, _t, expected in FALSE_FRIEND_MUST_FIRE}
    assert critical_ids <= covered, f"未涵蓋的 critical：{sorted(critical_ids - covered)}"


def test_false_friend_corpus_covers_every_language():
    """A 組必須橫跨 5 種語言——每種語言的否定詞都有自己的假朋友族。"""
    langs = {lg for _i, lg, _t, _e in FALSE_FRIEND_MUST_FIRE}
    assert langs == {"zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"}, sorted(langs)


def test_pre_and_post_cue_false_friends_are_shared():
    """ja/ko 可能形否定的假朋友必須**前置與後置都**適用。

    可能形否定（歩けない／참을 수 없이）是 SOV 語言最常見的「痛到不能～」加強
    語氣，它可以落在關鍵字任一側。第三輪只在後置擋、前置不擋，等於同一個語意
    現象修了一半（前置那半＝漏報）。
    """
    for ff in rfd_module._POST_CUE_FALSE_FRIENDS:
        assert ff in rfd_module._PRE_CUE_FALSE_FRIENDS, ff


def test_false_friend_match_is_containment_not_prefix():
    """判準必須是「cue 落在假朋友範圍內」，不是「假朋友從 cue 位置開始」。

    否定詞不見得是固定搭配的第一個字元：cannot 的 `not ` 從第 3 字元起、
    我慢できない的「ない」從第 5 字元起、참을 수 없이的「없」從第 6 字元起。
    用 prefix 判準時這三種語言的假朋友**結構上永遠命中不到**。
    """
    assert rfd_module._has_negation_cue("i cannot walk ") is False
    assert rfd_module._has_negation_cue("我慢できないほど痛くて") is False
    assert rfd_module._has_negation_cue("참을 수 없이 아파서 ") is False
    # 對照：真正的否定仍必須被認出來
    assert rfd_module._has_negation_cue("i do not have ") is True
    assert rfd_module._has_negation_cue("睾丸の痛みはない") is True
    assert rfd_module._has_negation_cue("고환 통증은 없") is True
