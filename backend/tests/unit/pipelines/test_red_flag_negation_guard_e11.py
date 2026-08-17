"""E11：紅旗規則層否定守衛（五語言詞表 + critical 緊視窗 + kill-switch）。

背景（TODO E11）：規則層是裸子字串比對，沒有否定語意概念——「沒有注意到體重減輕」
會命中 `unexplained_weight_loss`；若 critical 級也這樣誤報，就會誤中止問診
（conversation_handler 的 `has_critical` 分支會 abort 場次）。

本檔守護三件事：
1. 否定守衛只減少誤報，**不得讓真紅旗漏掉**（fail-open 方向）——最關鍵的
   `test_critical_window_never_suppresses_more_than_default` 是單向性 property test。
2. critical 用更緊的散文視窗（`_NEG_CRITICAL_PROSE_LOOKBACK`），但並列否認列舉
   （「沒有血尿、發燒、…、尿滯留」）仍抑制。
3. `RED_FLAG_NEGATION_GUARD=False` 整組退回加守衛前的裸 substring 行為。

既有的 `test_red_flag_negation.py`（規則層基本否定）與 `test_red_flag_denial.py`
（語意層否定幻覺後過濾）仍是同一組不變式的一部分，未在此重複。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import (
    RedFlagDetector,
    _keyword_present_non_negated,
    _prose_lookback_for_severity,
)

_CRIT = _prose_lookback_for_severity("critical")
_DEFAULT = _prose_lookback_for_severity("high")


def _run(coro):
    return asyncio.run(coro)


def present(keyword: str, text: str, prose_lookback: int | None = _DEFAULT) -> bool:
    """便利包裝：呼叫端一律傳原文（大小寫由此處 normalize，與 detector 一致）。"""
    return _keyword_present_non_negated(keyword, text.lower(), prose_lookback)


# ── detector 腳手架（極簡 AsyncSession stub，空表 → fallback 內建 catalogue）──


class _FakeScalars:
    def all(self) -> list[Any]:
        return []


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()


class _FakeDB:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


def _make_detector(
    monkeypatch: pytest.MonkeyPatch, negation_guard: bool = True
) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = negation_guard
    detector = RedFlagDetector(settings, _FakeDB())
    _run(detector._load_rules())
    return detector


def _canonicals(detector: RedFlagDetector, text: str, language: str) -> set[str]:
    return {a["canonical_id"] for a in detector._rule_based_detect(text, language)}


# ── 1. TODO E11 明確點名的兩個 case ─────────────────────────


class TestTodoE11NamedCases:
    def test_did_not_notice_weight_loss_does_not_fire(self, monkeypatch):
        """TODO 原句：「沒有注意到體重減輕」→ 不得命中 unexplained_weight_loss。"""
        detector = _make_detector(monkeypatch)
        assert _canonicals(detector, "我沒有注意到體重減輕", "zh-TW") == set()

    def test_negation_scoped_to_denied_item_only(self, monkeypatch):
        """「我沒有發燒，但有體重減輕」→ 否定只作用在被否定那一項，體重減輕仍要命中。

        窗口若大到把整句當否定就會漏掉這筆（TODO 明確要求本 case 有測試）。
        """
        detector = _make_detector(monkeypatch)
        assert _canonicals(detector, "我沒有發燒，但有體重減輕", "zh-TW") == {
            "unexplained_weight_loss"
        }


# ── 2. 五語言否定 / 非否定對照（走完整規則層，含跨語言聯集比對）──────


class TestFiveLanguageNegationPairs:
    """每語言一組對照：否定句不得命中、肯定句必須命中（同一個 canonical）。"""

    CASES = [
        ("zh-TW", "我沒有血尿", "我這兩天有血尿"),
        ("en-US", "no blood in urine at all", "I have blood in urine"),
        ("ja-JP", "肉眼的血尿はありません", "肉眼的血尿があります"),
        ("ko-KR", "육안적 혈뇨는 없어요", "육안적 혈뇨가 있어요"),
        ("vi-VN", "không có tiểu ra máu", "tôi bị tiểu ra máu"),
    ]

    @pytest.mark.parametrize("language,negated,affirmed", CASES)
    def test_negated_not_fired_affirmed_fired(
        self, monkeypatch, language, negated, affirmed
    ):
        detector = _make_detector(monkeypatch)
        assert "gross_hematuria" not in _canonicals(detector, negated, language), negated
        assert "gross_hematuria" in _canonicals(detector, affirmed, language), affirmed


class TestFiveLanguageCriticalPairs:
    """critical（urinary_retention）五語言對照：直接否認仍要抑制，肯定必須命中。"""

    CASES = [
        ("zh-TW", "我沒有尿不出來的情形", "從昨天開始尿不出來"),
        ("en-US", "patient denies urinary retention", "I cannot urinate since last night"),
        ("ja-JP", "尿閉はありません", "尿閉になりました"),
        ("ko-KR", "요폐는 없어요", "요폐가 생겼어요"),
        ("vi-VN", "không có bí tiểu", "tôi bị bí tiểu từ hôm qua"),
    ]

    @pytest.mark.parametrize("language,negated,affirmed", CASES)
    def test_negated_not_fired_affirmed_fired(
        self, monkeypatch, language, negated, affirmed
    ):
        detector = _make_detector(monkeypatch)
        assert "urinary_retention" not in _canonicals(detector, negated, language), negated
        assert "urinary_retention" in _canonicals(detector, affirmed, language), affirmed


# ── 3. critical 緊散文視窗的取捨 ────────────────────────────


class TestCriticalProseWindow:
    def test_direct_denial_still_suppressed(self):
        """critical 的直接否認仍必須抑制（否則 E11 點名的誤 abort 又回來）。"""
        assert present("睪丸劇痛", "我完全沒有睪丸劇痛", _CRIT) is False
        assert present("testicle pain", "patient denies testicle pain", _CRIT) is False

    def test_negated_enumeration_still_suppressed(self):
        """並列否認列舉：list 分隔不吃散文預算 → 末端的 critical 關鍵字仍抑制。

        原句取自對抗性 e2e 電池（P2）；若這裡改成命中，一句「我都排除了」會同時
        觸發多個 critical、直接誤中止問診。
        """
        text = (
            "我把我知道的都排除一下好了：沒有血尿、發燒、畏寒、噁心、嘔吐、食慾不振、"
            "體重減輕、排尿疼痛、腰部痠痛、下腹悶脹、頻尿急尿、尿滯留、完全排不出的情形"
        )
        assert present("尿滯留", text, _CRIT) is False
        assert present("完全排不出", text, _CRIT) is False

    def test_short_enumeration_of_critical_symptoms_suppressed(self):
        assert present("寒顫", "我沒有高燒、寒顫、意識不清", _CRIT) is False

    def test_long_prose_between_denial_and_critical_keyword_fires(self):
        """critical 與否定詞之間隔了一長段散文 → 不採信該否定，寧可命中。

        STT 逐字稿常整段沒有標點，舊的 120 字視窗會讓開頭一個「沒有」吃掉後面
        真正講出來的 critical 症狀（under-triage）。
        """
        text = "我沒有什麼慢性病之前也開過一次刀最近工作很忙睡不好突然尿不出來"
        assert present("尿不出來", text, _CRIT) is True
        # 同一句對 high 維持既有（較寬）行為，未改動已驗收的邏輯
        assert present("血尿", text.replace("突然尿不出來", "突然血尿"), _DEFAULT) is False

    def test_affirmative_pivot_resets_negation(self):
        """「就是/只是」是「否認一串後點出真正症狀」的口語標記 → 其後不受否定涵蓋。"""
        assert present("尿不出來", "我沒有什麼特別的問題，就是尿不出來", _CRIT) is True
        assert present("尿不出來", "沒有發燒也不會痛，只是尿不出來", _CRIT) is True

    def test_critical_window_never_suppresses_more_than_default(self):
        """單向性（承重）：緊視窗只能讓 critical 更容易命中，不可能更難。

        default 視窗會命中的任何 (keyword, text) 組合，critical 視窗都必須命中。
        若哪天改了視窗實作而破壞這條，就等於守衛開始製造漏報。
        """
        texts = [
            "我沒有血尿、發燒、腰痛、尿滯留",
            "沒有發燒但有血尿",
            "上週有血尿，這週沒有血尿",
            "patient denies fever, chills, and urinary retention",
            "gross hematuria present for 3 days",
            "血尿はありません",
            "혈뇨가 있어요",
            "không có tiểu ra máu, nhưng tôi bị sụt cân",
            "我沒有什麼慢性病之前也開過一次刀最近工作很忙睡不好突然尿不出來",
        ]
        keywords = {
            kw
            for flag in URO_RED_FLAGS
            for kw in RedFlagDetector._collect_all_language_keywords(flag)
        }
        for text in texts:
            for kw in keywords:
                if present(kw, text, _DEFAULT):
                    assert present(kw, text, _CRIT) is True, (
                        f"緊視窗製造了漏報 | keyword={kw!r} text={text!r}"
                    )


# ── 4. 否定詞假朋友（守衛自己造成的漏報，最危險的方向）────────────


class TestCueFalseFriends:
    """字面含否定詞、語意其實肯定的詞不得當成否定線索（否則守衛製造漏報）。

    ⚠️ 2026-07-27 第四輪：假朋友從「逐個案補」改成**按族系統性展開**（時間敘事／
    轉折／確認語／能力喪失／程度加強 × 5 語言），完整的雙向語料在
    `test_red_flag_negation_false_friends.py`（跨 5 個 critical canonical，
    修復前 28 句中 26 句規則層 0 命中）。本類只留代表性的幾筆當就地回歸。
    """

    @pytest.mark.parametrize(
        "keyword,text,prose",
        [
            # 「無力」是馬尾症候群的症狀，不是否定
            ("會陰麻木", "我覺得下肢無力，也有會陰麻木", _CRIT),
            # 「無法排尿」本身就是 critical trigger，不該否定後面的 critical
            ("睪丸劇痛", "我無法排尿也睪丸劇痛", _CRIT),
            # 「非常」是加強語氣
            ("尿不出來", "我睪丸非常痛，尿不出來", _CRIT),
            # 「不舒服」「不停」都是肯定陳述
            ("血尿", "我很不舒服，有血尿", _DEFAULT),
            ("尿不出來", "血一直流不停，尿不出來", _CRIT),
            # ── 第四輪新增的族（各留一筆代表）──
            # (a) 時間敘事：「沒多久」＝過了一小段時間
            ("尿不出來", "喝了水沒多久就尿不出來", _CRIT),
            # (b) 轉折/意外：「沒想到」
            ("血尿", "本來只是悶悶的，沒想到有血尿", _DEFAULT),
            # (d) 能力喪失/程度加強：「沒辦法」「沒力氣」
            ("尿不出來", "脹到沒辦法忍了，尿不出來", _CRIT),
            # en：cannot / without warning / no idea
            ("testicle pain", "i cannot stop vomiting and i have testicle pain", _CRIT),
            ("testicle pain", "without warning i got testicle pain", _CRIT),
            # ja：可能形否定＝加強語氣（前置也要擋，不只後置）
            ("睾丸の激痛", "我慢できないほどの睾丸の激痛です", _CRIT),
            # ko：참을 수 없이＝加強語氣
            ("고환이 아파", "참을 수 없이 고환이 아파요", _CRIT),
            # vi：không thể＝能力喪失
            ("bìu sưng đau", "tôi không thể chịu được, bìu sưng đau", _CRIT),
        ],
    )
    def test_false_friend_does_not_negate(self, keyword, text, prose):
        assert present(keyword, text, prose) is True, text

    @pytest.mark.parametrize(
        "text",
        [
            "無血尿", "我沒有血尿", "不會有血尿", "未見血尿", "並無血尿", "否認血尿",
            # 第四輪：族展開之後，這些**明確否認**仍必須抑制（對照組）
            "我沒有注意到血尿",
            "沒有大量的血尿",
        ],
    )
    def test_real_negation_still_suppressed(self, text):
        """假朋友白名單不得把真正的否定詞一起放過。"""
        assert present("血尿", text, _DEFAULT) is False, text


# ── 5. kill-switch 關閉 → 回到加守衛前的行為 ──────────────────


class TestKillSwitchOff:
    def test_rule_layer_falls_back_to_naive_substring(self, monkeypatch):
        """guard 關 → 「沒有血尿」照舊誤命中（＝加守衛前的行為）。"""
        detector = _make_detector(monkeypatch, negation_guard=False)
        assert "gross_hematuria" in _canonicals(detector, "我沒有血尿", "zh-TW")

    def test_rule_layer_critical_also_naive_when_off(self, monkeypatch):
        detector = _make_detector(monkeypatch, negation_guard=False)
        assert "urinary_retention" in _canonicals(detector, "我沒有尿不出來", "zh-TW")

    def test_todo_case_fires_again_when_off(self, monkeypatch):
        detector = _make_detector(monkeypatch, negation_guard=False)
        assert "unexplained_weight_loss" in _canonicals(
            detector, "我沒有注意到體重減輕", "zh-TW"
        )

    def test_guard_on_suppresses_semantic_denial_hallucination(self, monkeypatch):
        """guard 開 → 語意層對「沒有血尿」幻覺出的紅旗被後過濾殺掉。"""
        merged = self._detect_with_fake_semantic(monkeypatch, guard=True)
        assert merged == []

    def test_guard_off_keeps_semantic_denial_hallucination(self, monkeypatch):
        """guard 關 → 語意層否定幻覺後過濾一併停用（同一機制，只關一半更難推理）。"""
        merged = self._detect_with_fake_semantic(monkeypatch, guard=False)
        assert {a["canonical_id"] for a in merged} == {"gross_hematuria"}

    @staticmethod
    def _detect_with_fake_semantic(monkeypatch: pytest.MonkeyPatch, guard: bool):
        detector = _make_detector(monkeypatch, negation_guard=guard)

        async def _fake_semantic(self, text, ctx, language=None):
            return [
                {
                    "canonical_id": "gross_hematuria",
                    "severity": "high",
                    "title": "肉眼血尿",
                    "description": "",
                    "trigger_reason": "病患提及血尿",
                    "alert_type": "semantic",
                    "confidence": "semantic_only",
                    "suggested_actions": [],
                    "matched_rule_id": None,
                }
            ]

        monkeypatch.setattr(RedFlagDetector, "_semantic_detect", _fake_semantic)
        return _run(
            detector.detect("我沒有血尿", {"session_id": "s1", "language": "zh-TW"})
        )


# ── 6. 純肯定句回歸（守衛不得影響正常命中）────────────────────


class TestAffirmativeRegression:
    @pytest.mark.parametrize(
        "language,text,expected",
        [
            ("zh-TW", "我這兩天有血尿而且完全尿不出來", {"gross_hematuria", "urinary_retention"}),
            ("en-US", "I have blood in urine and cannot urinate", {"gross_hematuria", "urinary_retention"}),
            ("zh-TW", "半夜開始睪丸劇痛，痛到走不動", {"testicular_pain_severe"}),
            ("zh-TW", "這個月體重下降很多，也一直吃不下", {"unexplained_weight_loss"}),
            ("ja-JP", "睾丸の激痛があります", {"testicular_pain_severe"}),
            ("ko-KR", "극심한 고환 통증이 있어요", {"testicular_pain_severe"}),
            ("vi-VN", "tôi bị đau tinh hoàn dữ dội", {"testicular_pain_severe"}),
        ],
    )
    def test_affirmative_sentences_still_fire(
        self, monkeypatch, language, text, expected
    ):
        detector = _make_detector(monkeypatch)
        assert expected <= _canonicals(detector, text, language), text

    def test_no_symptom_text_fires_nothing(self, monkeypatch):
        detector = _make_detector(monkeypatch)
        assert _canonicals(detector, "我只是來拿慢性處方箋", "zh-TW") == set()


# ──────────────────────────────────────────────────────────────
# 2026-07-26 對抗式驗證找到的漏洞：ja/ko/vi/en 缺轉折詞 → critical 漏報。
#
# 原測試只涵蓋「單句直接否認」與「單句肯定」，從未測任何語言的
# 「否認某症狀 ＋ 轉折 ＋ 真的有 critical 症狀」——那正是門診最常見的句型，
# 也是規則層作為語意層 fallback（不變式 #9）最需要守住的一條。
# 中文一直是對的，所以肉眼比對五語言時看不出破口。
# ──────────────────────────────────────────────────────────────

_CONTRAST_MUST_FIRE = [
    # (病患原話, 語言, 期望命中的 canonical_id)
    ("熱はないですが尿閉になりました", "ja-JP", "urinary_retention"),
    ("熱はないけど睾丸の激痛があります", "ja-JP", "testicular_pain_severe"),
    ("熱はないしかし尿閉です", "ja-JP", "urinary_retention"),
    ("熱ではなく睾丸の激痛です", "ja-JP", "testicular_pain_severe"),
    ("열은 없지만 요폐가 생겼어요", "ko-KR", "urinary_retention"),
    ("열은 아니고 극심한 고환 통증이 있어요", "ko-KR", "testicular_pain_severe"),
    ("chưa có sốt nhưng tiểu ra máu", "vi-VN", "gross_hematuria"),
    # 2026-07-27：原文用的是「testicular pain」，但那個字串**就是** en-US 的主訴
    # 選單標籤（complaint_fallback_i18n["睪丸疼痛"]["en-US"] == "Testicular pain"），
    # 病患複誦一次主訴名稱就會被 critical abort，因此已從 catalogue 移除
    # （見 shared.py 該處註解與 test_red_flag_over_trigger.py 的結構性守衛）。
    # 這一筆測的是**轉折詞 however 是否重置否定範圍**，與用哪個症狀詞無關，
    # 故改用同樣是 critical trigger、且不是主訴標籤的「testicle pain」，
    # 斷言維持原樣（仍必須命中，仍是 under-triage 防線）。
    ("denies fever, however he has testicle pain", "en-US", "testicular_pain_severe"),
    ("我沒有發燒，但是尿不出來", "zh-TW", "urinary_retention"),
]

# 同一批語言的「純否認」必須仍被抑制——否則上面的修法等於把守衛關掉。
_PLAIN_DENIAL_MUST_SUPPRESS = [
    ("熱はありません", "ja-JP"),
    ("열은 없어요", "ko-KR"),
    ("고환 통증이 없어요", "ko-KR"),
    ("không có tiểu ra máu", "vi-VN"),
    # 同上：改用仍在 catalogue 內的「testicle pain」，斷言才是有效的
    #（用已移除的關鍵字會變成永遠 trivially pass 的空測試）。
    ("denies testicle pain", "en-US"),
    ("我沒有睪丸劇痛", "zh-TW"),
]


@pytest.mark.parametrize("text,language,expected_id", _CONTRAST_MUST_FIRE)
def test_denial_then_contrast_still_fires(
    monkeypatch: pytest.MonkeyPatch, text, language, expected_id
):
    """否認 A、轉折、真的有 B → B 必須命中。漏掉＝under-triage（不可逆）。"""
    ids = _canonicals(_make_detector(monkeypatch), text, language)
    assert expected_id in ids, (
        f"{language} 的『否認＋轉折＋真症狀』漏報：{text!r} 應命中 {expected_id}，"
        f"實得 {sorted(ids)}。檢查 _CONTRAST_MARKERS 是否涵蓋該語言的轉折詞。"
    )


@pytest.mark.parametrize("text,language", _PLAIN_DENIAL_MUST_SUPPRESS)
def test_plain_denial_still_suppressed(monkeypatch: pytest.MonkeyPatch, text, language):
    """純否認仍須抑制——證明上面的轉折詞不是把守衛整個關掉換來的。"""
    ids = _canonicals(_make_detector(monkeypatch), text, language)
    assert not ids, f"{language} 純否認 {text!r} 不該命中，實得 {sorted(ids)}"
