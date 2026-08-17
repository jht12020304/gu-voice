"""紅旗 **over-trigger 防線**：這裡的每一筆輸入都是「不該觸發 critical」。

為什麼要有一個專門往這個方向測的檔案
────────────────────────────────────────
critical 紅旗一命中，`conversation_handler` 的 `has_critical` 分支就會把場次打成
`aborted_red_flag`（2026-07-27 真跑 `torsion_critical_zh` 實測：病患第 1 輪講完就結束）。
所以 **critical 的誤報 ≠ 多一則警示，而是整場問診被中止**：病患在院內 kiosk 前
被告知「請告知現場醫護」，問診資料不全，等於白跑一趟——而且病患**感知得到**。
漏偵測則還有語意層（LLM）與現場醫護兩層接住。

⚠️ 2026-07-27 臨床拍板：這個檔案的取捨方向已被**推翻一半**，讀者必讀
────────────────────────────────────────
本檔原本寫的是「寧可規則層漏一點，也不要誤中止」。使用者（臨床）於 2026-07-27
拍板的政策相反：**紅旗規則層偏誤報**——「寧可多中止幾場。第三人稱轉述、別部位
誤配這類殘餘誤報就留著。誤中止的代價是病患白等、護理師走一趟，可逆。」

所以本檔現在守的是**收窄過的**過度觸發面，只涵蓋一件事：
**病患明確、無歧義地否認了這個症狀**（我沒有 X／X 倒是沒有／以前有現在好了／
純假設／純行政詢問）。除此之外的「像症狀但主體/情境不同」（第三人稱轉述、別部位
誤配、hedge 式否認）**刻意不擋**，正向釘在
`test_red_flag_suppression_policy.py::test_policy_accepted_false_positives`。
要往本檔加新的 over-trigger 斷言前，先確認它屬於「明確否認」那一類；
不是的話，加了就是在製造漏報。

而既有的紅旗測試（test_red_flag_negation_guard_e11.py、
test_red_flag_torsion_and_context.py）幾乎全部是「這句話**必須**命中」的方向。
2026-07-27 為了修「規則層對睪丸扭轉 0 命中」補了一批**裸關鍵字**（睪丸痛／
陰囊痛／ball hurt…），單元測試全綠、卻讓下面 `BLOCKER_REPRODUCTIONS` 四句
（含「my eyeball hurts a lot」）全部變成 critical——因為**沒有任何測試往
over-trigger 方向施力**。這個檔案就是補上那個方向。

本檔守護四件事
────────────────────────────────────────
1. `BLOCKER_REPRODUCTIONS`：對抗式覆核實測誤觸發的四句，逐字釘住。
2. `test_no_critical_on_generated_counterexamples`：**每一個** critical trigger
   關鍵字都自動配上四種「相近但不是症狀陳述」的框架（直接否認／子句尾否認／
   假設語氣／行政詢問／時態否定）。新增關鍵字時反例會自動長出來，不會再出現
   「補了關鍵字但沒補反例」。
3. `test_no_critical_trigger_equals_a_chief_complaint_label`：結構性守衛——
   critical trigger 不得**等於**主訴選單標籤，否則病患複誦一次主訴就被 abort。
4. `MUST_STILL_FIRE`：對照組。沒有這一組，上面三組可以靠「把偵測關掉」全過。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from unittest.mock import MagicMock

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import RedFlagDetector
from app.utils.complaint_fallback_i18n import NAME_FALLBACK_I18N

LANGUAGES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")
TORSION = "testicular_pain_severe"


def _run(coro):
    return asyncio.run(coro)


# ── detector 腳手架（空表 → fallback 內建 catalogue）───────────────


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


def _critical_hits(det: RedFlagDetector, text: str, language: str) -> list[tuple]:
    """回傳 (canonical_id, 命中詞) — 空 list 代表不會 abort 問診。"""
    return [
        (a["canonical_id"], a.get("trigger_keywords"))
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


def _torsion_fired(det: RedFlagDetector, text: str, language: str) -> bool:
    return any(
        a["canonical_id"] == TORSION for a in det._rule_based_detect(text, language)
    )


# ══════════════════════════════════════════════════════════════
# 1. 對抗式覆核實測誤觸發的四句（逐字釘住）
# ══════════════════════════════════════════════════════════════

BLOCKER_REPRODUCTIONS = [
    # 子字串誤命中：「ball hurt」⊂「eyeball hurts」→ 眼睛痛被判睪丸扭轉。
    # 修法＝拉丁字母關鍵字改詞邊界比對（前緣）。
    pytest.param("en-US", "my eyeball hurts a lot", id="eyeball-substring"),
    # 行政詢問：病患在問掛號科別，不是在陳述症狀。
    pytest.param("zh-TW", "我想問睪丸痛要看哪一科", id="which-department"),
    # 後置否定：否認詞在關鍵字**之後**，舊守衛只看前面。
    pytest.param("zh-TW", "小便會痛，睪丸痛倒是沒有", id="post-negation"),
    # 時態否定：以前有過、現在已經好了。
    pytest.param("zh-TW", "以前睪丸痛過，但現在完全好了", id="past-resolved"),
]


@pytest.mark.parametrize("language,text", BLOCKER_REPRODUCTIONS)
def test_no_critical_on_blocker_reproductions(detector, language, text):
    hits = _critical_hits(detector, text, language)
    assert hits == [], (
        f"誤觸發 critical → 第 1 輪就 aborted_red_flag，病患白跑一趟。"
        f"\n  輸入：{text!r}（{language}）\n  命中：{hits}"
    )


# 上面四句有兩句在關鍵字收緊後已經沒有任何 trigger（睪丸痛已移除），
# 所以額外釘住「關鍵字**還在**、只能靠語境守衛擋下來」的同型句子——
# 否則哪天有人把裸關鍵字加回來，上面的測試會照過。
SAME_SHAPE_WITH_LIVE_KEYWORDS = [
    pytest.param("zh-TW", "我想問睪丸很痛要看哪一科", id="zh-inquiry-live-kw"),
    pytest.param("zh-TW", "我想問睪丸扭轉要看哪一科", id="zh-inquiry-torsion-name"),
    pytest.param("zh-TW", "小便會痛，睪丸很痛倒是沒有", id="zh-postneg-live-kw"),
    pytest.param("zh-TW", "陰囊很痛倒是沒有", id="zh-postneg-scrotum"),
    pytest.param("zh-TW", "以前睪丸很痛過，但現在完全好了", id="zh-past-live-kw"),
    pytest.param("zh-TW", "以前蛋蛋很痛過，現在都好了", id="zh-past-slang"),
    pytest.param("zh-TW", "如果睪丸突然很痛要怎麼辦", id="zh-conditional"),
    pytest.param("zh-TW", "沒有睪丸腫痛的情形", id="zh-pre-negation-swelling"),
    pytest.param("en-US", "my eyeballs hurt so much", id="en-eyeballs-plural"),
    pytest.param("en-US", "what if my testicle hurts again later", id="en-what-if"),
    pytest.param(
        "en-US",
        "I just wanted to ask about testicle pain, which doctor should I see",
        id="en-which-doctor",
    ),
    pytest.param(
        "en-US",
        "I used to have testicle pain years ago but it went away",
        id="en-past-resolved",
    ),
    pytest.param("ja-JP", "睾丸の痛みはありません", id="ja-denial"),
    pytest.param(
        "ja-JP", "昔は睾丸の痛みがありましたが、今は治りました", id="ja-past-resolved"
    ),
    pytest.param(
        "ja-JP",
        "睾丸が痛いのは何科か聞きたいです",
        id="ja-which-department",
    ),
    pytest.param("ko-KR", "고환이 아파요는 없어요", id="ko-denial"),
    pytest.param(
        "ko-KR",
        "예전에 고환이 아파서 고생했지만 지금은 다 나았어요",
        id="ko-past-resolved",
    ),
    pytest.param(
        "ko-KR",
        "고환 통증이 심한 건 무슨 과에 가야 하는지 물어보고 싶어요",
        id="ko-which-department",
    ),
    pytest.param("vi-VN", "nếu tinh hoàn đau thì phải làm sao", id="vi-conditional"),
    pytest.param(
        "vi-VN",
        "tôi muốn hỏi tinh hoàn đau thì khám khoa nào",
        id="vi-which-department",
    ),
    pytest.param(
        "vi-VN",
        "trước đây tinh hoàn đau nhưng bây giờ đã khỏi hẳn",
        id="vi-past-resolved",
    ),
]


@pytest.mark.parametrize("language,text", SAME_SHAPE_WITH_LIVE_KEYWORDS)
def test_no_critical_on_same_shape_with_live_keywords(detector, language, text):
    hits = _critical_hits(detector, text, language)
    assert hits == [], f"{language} {text!r} 誤觸發 critical：{hits}"


# ══════════════════════════════════════════════════════════════
# 2. 每個 critical 關鍵字自動長出反例
# ══════════════════════════════════════════════════════════════
# 五種「不是病患現在症狀陳述」的框架，逐語言套到 catalogue 裡**每一個**
# critical trigger 上。新增關鍵字 → 反例自動出現，不會再有「只往容易命中的
# 方向加斷言」的漏洞。
#
# 句子的自然度刻意讓位給覆蓋率：框架是機械套用的，有些組合讀起來生硬，
# 但斷言本身（「這句話不是在陳述現在的症狀，不該中止問診」）永遠成立。
_COUNTEREXAMPLE_FRAMES: dict[str, tuple[str, ...]] = {
    "zh-TW": (
        "我沒有{kw}",  # 前置否定
        "{kw}倒是沒有",  # 後置否定（子句尾否認）
        "如果{kw}要怎麼辦",  # 假設語氣
        "我想問{kw}要看哪一科",  # 行政詢問
        "以前{kw}過，但現在完全好了",  # 時態否定
    ),
    "en-US": (
        "no {kw} at all",
        "patient denies {kw}",
        "what if {kw} comes back later",
        "I just wanted to ask about {kw}, which doctor should I see",
        "I used to have {kw} years ago but it went away",
    ),
    "ja-JP": (
        "{kw}はありません",
        "もし{kw}ならどうすればいいですか",
        "{kw}は何科か聞きたいです",
        "昔は{kw}がありましたが、今は治りました",
    ),
    "ko-KR": (
        "{kw}은 없어요",
        "만약 {kw} 있으면 어떻게 하나요",
        "{kw}은 무슨 과에 가야 하는지 물어보고 싶어요",
        "예전에 {kw} 있었지만 지금은 다 나았어요",
    ),
    "vi-VN": (
        "không có {kw}",
        "nếu {kw} thì phải làm sao",
        "tôi muốn hỏi {kw} thì khám khoa nào",
        "trước đây {kw} nhưng bây giờ đã khỏi hẳn",
    ),
}


def _critical_triggers_by_lang() -> list[tuple[str, str, str]]:
    """(canonical_id, language, keyword) — 只取 critical（會 abort 的那一群）。

    ⚠️ 必須同時列舉**頂層 `triggers`** 與 `triggers_by_lang`。
    2026-07-27 Gate 的注入式回歸實測：只列舉 `triggers_by_lang` 時，把裸
    「睪丸疼痛」（＝主訴選單標籤）加進頂層 `triggers`，本檔的結構性守衛與
    生成式反例**兩者都不會紅**——但 `red_flag_detector._get_flag_keywords`
    比對的是「頂層 triggers ∪ triggers_by_lang 全語言」聯集（見該檔約 786 行），
    所以那個關鍵字實際上是會 abort 問診的。少列頂層等於本檔的核心承諾
    （「新增關鍵字時反例自動長出來」）有一個靜默破口。

    頂層 triggers 目前全是中文，且比對時不分場次語言，故：
    - 生成式反例掛在 zh-TW 框架下（框架要跟關鍵字同語言才讀得通）；
    - 主訴標籤結構性守衛另外對**全語言**標籤比對（見
      `test_no_critical_trigger_equals_a_chief_complaint_label`）。
    """
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(cid: str, lang: str, kw: str) -> None:
        if lang not in _COUNTEREXAMPLE_FRAMES:
            return
        item = (cid, lang, kw)
        if item not in seen:
            seen.add(item)
            out.append(item)

    for flag in URO_RED_FLAGS:
        if flag.get("severity") != "critical":
            continue
        cid = flag["canonical_id"]
        for lang, keywords in (flag.get("triggers_by_lang") or {}).items():
            for kw in keywords:
                _add(cid, lang, kw)
        # 頂層 triggers：跨語言聯集比對，反例用 zh-TW 框架（內容為中文）。
        for kw in flag.get("triggers") or []:
            _add(cid, "zh-TW", kw)
    return out


def _critical_top_level_triggers() -> list[tuple[str, str]]:
    """(canonical_id, keyword) — critical 的**頂層** triggers（不分語言比對）。"""
    return [
        (flag["canonical_id"], kw)
        for flag in URO_RED_FLAGS
        if flag.get("severity") == "critical"
        for kw in (flag.get("triggers") or [])
    ]


_GENERATED_COUNTEREXAMPLES = [
    pytest.param(lang, frame.format(kw=kw), cid, id=f"{cid}-{lang}-{kw}-{i}")
    for cid, lang, kw in _critical_triggers_by_lang()
    for i, frame in enumerate(_COUNTEREXAMPLE_FRAMES[lang])
]


@pytest.mark.parametrize("language,text,canonical_id", _GENERATED_COUNTEREXAMPLES)
def test_no_critical_on_generated_counterexamples(
    detector, language, text, canonical_id
):
    """關鍵字被包在否認／假設／詢問／過去式框架裡 → 不得判 critical。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], (
        f"{canonical_id} 的關鍵字在非症狀陳述語境仍誤觸發 critical（會中止問診）："
        f"\n  {language} {text!r}\n  命中：{hits}"
    )


def test_every_critical_language_has_counterexample_frames():
    """5 語言都要有反例框架——少一語＝那語的 over-trigger 完全沒有防線。"""
    for lang in LANGUAGES:
        assert _COUNTEREXAMPLE_FRAMES.get(lang), lang


def test_generated_counterexamples_cover_every_critical_keyword():
    """每個 critical 關鍵字至少配到一組反例（就是本檔的核心承諾）。"""
    covered = {kw for _cid, _lang, kw in _critical_triggers_by_lang()}
    assert covered, "critical 關鍵字表是空的？"
    for lang in LANGUAGES:
        assert any(
            lang == lg for _cid, lg, _kw in _critical_triggers_by_lang()
        ), f"{lang} 沒有任何 critical trigger，規則層 fallback 在該語言等於失效"


# ══════════════════════════════════════════════════════════════
# 3. 結構性守衛：critical trigger 不得等於主訴選單標籤
# ══════════════════════════════════════════════════════════════


def _complaint_labels_by_lang() -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    for by_lang in NAME_FALLBACK_I18N.values():
        for lang, text in by_lang.items():
            labels.setdefault(lang, set()).add(text.lower().strip())
    return labels


def test_no_critical_trigger_equals_a_chief_complaint_label():
    """critical trigger 不得**等於**該語言的主訴選單標籤。

    理由（2026-07-27 實測）：主訴選單有「睪丸疼痛 / Testicular pain / 睾丸痛 /
    고환 통증 / Đau tinh hoàn」與「陰囊疼痛 / Scrotal pain / 陰嚢痛 / 음낭 통증 /
    Đau bìu」。這些字串一度同時是 critical trigger，於是病患只要把自己選的主訴
    複誦一次（「我是睪丸疼痛來看診的，已經三個月了」）就會在第 1 輪被
    aborted_red_flag——慢性睪丸痛正是泌尿科門診最常見的良性主訴之一。

    critical 以外的嚴重度不受此限（high/medium 不會中止問診，只是多一則警示）。
    """
    labels = _complaint_labels_by_lang()
    offenders = [
        (cid, lang, kw)
        for cid, lang, kw in _critical_triggers_by_lang()
        if kw.lower().strip() in labels.get(lang, set())
    ]
    assert offenders == [], (
        "critical trigger 與主訴選單標籤字面相同 → 病患複誦主訴即被中止問診："
        f"{offenders}"
    )


def test_no_critical_top_level_trigger_equals_any_language_label():
    """頂層 `triggers` 不得等於**任何語言**的主訴選單標籤。

    頂層 triggers 由 `red_flag_detector._get_flag_keywords` 併進跨語言聯集，
    比對時**不分場次語言**（該檔約 786 行的 W1 設計）。所以一個中文頂層
    trigger 在英文場次也會命中；反過來說，只要它字面等於任一語言的主訴標籤，
    那個語言的病患複誦主訴就會被 abort。

    2026-07-27 Gate 注入式回歸補上：先前只有「按語言比對 triggers_by_lang」
    的守衛，把「睪丸疼痛」塞進頂層 triggers 時整個檔案不會紅。
    """
    all_labels = {lbl for lbls in _complaint_labels_by_lang().values() for lbl in lbls}
    offenders = [
        (cid, kw)
        for cid, kw in _critical_top_level_triggers()
        if kw.lower().strip() in all_labels
    ]
    assert offenders == [], (
        "critical 的頂層 trigger 與主訴選單標籤字面相同（跨語言聯集比對，"
        f"任一語言的病患複誦主訴即被中止問診）：{offenders}"
    )


def test_chief_complaint_echo_does_not_abort(detector):
    """把主訴標籤原樣講出來（且明說是慢性）不得觸發 critical。"""
    echoes = [
        ("zh-TW", "我是睪丸疼痛來看診的，已經三個月了"),
        ("en-US", "I'm here for testicular pain, it's been three months"),
        ("ja-JP", "睾丸痛で来ました、三ヶ月前からです"),
        ("ko-KR", "고환 통증 때문에 왔어요, 삼 개월 됐어요"),
        ("vi-VN", "tôi bị đau tinh hoàn ba tháng nay"),
    ]
    for language, text in echoes:
        assert _critical_hits(detector, text, language) == [], f"{language} {text!r}"


# ══════════════════════════════════════════════════════════════
# 4. 詞邊界（拉丁字母關鍵字）
# ══════════════════════════════════════════════════════════════


class TestLatinWordBoundary:
    """「ball hurt」不得命中「eyeball hurts」，但字尾變化仍要命中。"""

    @pytest.mark.parametrize(
        "text",
        [
            "my eyeball hurts a lot",
            "my eyeballs hurt so much",
            "the eyeball hurt for two days",
        ],
    )
    def test_no_critical_on_eyeball(self, detector, text):
        assert _critical_hits(detector, text, "en-US") == [], text

    @pytest.mark.parametrize(
        "text",
        [
            "my ball hurts really bad",
            "my balls hurt so much I want to vomit",
            "my left ball hurting since midnight",
        ],
    )
    def test_real_complaint_still_fires_despite_inflection(self, detector, text):
        """只檢查前緣詞邊界：hurt/hurts/hurting 的字尾變化不可因此漏掉。"""
        assert _torsion_fired(detector, text, "en-US"), text

    def test_boundary_applies_even_with_guard_off(self, monkeypatch):
        """詞邊界是比對精度，不隨否定守衛 kill-switch 一起關掉。"""
        monkeypatch.setattr(
            rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
        )
        settings = MagicMock()
        settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
        settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
        settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
        settings.RED_FLAG_NEGATION_GUARD = False  # 守衛關掉
        det = RedFlagDetector(settings, _FakeDB())
        _run(det._load_rules())
        assert _critical_hits(det, "my eyeball hurts a lot", "en-US") == []
        # 對照：守衛關掉時「沒有…」照舊會誤命中（＝加守衛前的行為，未被本次改動影響）
        assert _critical_hits(det, "我完全沒有睪丸劇痛", "zh-TW") != []


# ══════════════════════════════════════════════════════════════
# 5. 對照組：沒有這一組，上面全部可以靠「關掉偵測」通過
# ══════════════════════════════════════════════════════════════

MUST_STILL_FIRE = [
    # 2026-07-27 真跑 torsion_critical_zh 的病患第 1 輪逐字稿
    pytest.param(
        "zh-TW",
        "大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難。",
        id="e2e-real-transcript",
    ),
    pytest.param("zh-TW", "兩個小時前左邊睪丸突然很痛，痛到想吐", id="zh-sudden"),
    pytest.param("zh-TW", "半夜開始睪丸劇痛，痛到走不動", id="zh-severe"),
    pytest.param("zh-TW", "我蛋蛋突然痛起來，腫得很大", id="zh-slang"),
    pytest.param("zh-TW", "陰囊突然腫起來而且痛到走不動", id="zh-scrotum"),
    # 真的在求助的問句：只問「怎麼辦」不算行政詢問，必須命中
    pytest.param("zh-TW", "請問我睪丸很痛怎麼辦", id="zh-real-question-for-help"),
    # 「沒記錯」是肯定的確認語，不是否定線索
    pytest.param("zh-TW", "如果我沒記錯，是兩小時前睪丸突然劇痛", id="zh-if-i-recall"),
    # 2026-07-27 第四輪：否定線索的「假朋友」族——字面帶否定詞、語意是敘事／
    # 加強語氣／症狀本身。這裡各語言各留一筆當**對照組**，完整的雙向語料在
    # test_red_flag_negation_false_friends.py（跨 5 個 critical × 5 語言）。
    pytest.param("zh-TW", "今天早上開始痛，沒多久睪丸就腫起來痛到吐", id="zh-cue-meiduojiu"),
    pytest.param(
        "en-US",
        "i cannot stop vomiting, my testicle suddenly hurts so bad",
        id="en-cue-cannot",
    ),
    pytest.param(
        "ja-JP", "我慢できないほど痛くて、睾丸が急に腫れて痛みます", id="ja-cue-gaman"
    ),
    pytest.param(
        "ko-KR", "참을 수 없이 아파서 고환이 갑자기 부었어요", id="ko-cue-chameul"
    ),
    pytest.param(
        "vi-VN", "tôi không thể chịu được, bìu sưng đau đột ngột", id="vi-cue-khongthe"
    ),
    # 條件句 ＋ 已經在發作（急性伴隨症狀）→ 第四輪收窄後不得抑制
    pytest.param(
        "zh-TW", "醫生如果我今天早上睪丸突然劇痛痛到吐要怎麼辦", id="zh-conditional-but-ongoing"
    ),
    # 舊傷已癒 ＋ **今天復發** → 復發詞一出現就不得抑制
    pytest.param(
        "zh-TW",
        "之前睪丸很痛，吃了藥好了，今天又痛起來腫得很大，睪丸突然更痛",
        id="zh-past-but-recurred",
    ),
    pytest.param(
        "en-US",
        "two hours ago my left testicle suddenly started to hurt badly",
        id="en-sudden",
    ),
    pytest.param(
        "en-US", "sudden severe scrotal pain and swollen testicle", id="en-severe"
    ),
    pytest.param("ja-JP", "二時間前に急に睾丸が痛くなりました", id="ja-sudden"),
    pytest.param("ja-JP", "左の精巣の痛みがひどくて歩けません", id="ja-severe"),
    pytest.param("ja-JP", "陰嚢が腫れて痛みがひどいです", id="ja-swelling"),
    pytest.param("ko-KR", "두 시간 전에 갑자기 고환이 아파요", id="ko-sudden"),
    pytest.param("ko-KR", "음낭이 부어오르고 고환 통증이 심해요", id="ko-severe"),
    pytest.param("vi-VN", "hai tiếng trước tinh hoàn bên trái đau", id="vi-sudden"),
    pytest.param("vi-VN", "bìu sưng đau và tôi buồn nôn", id="vi-swelling"),
    pytest.param("vi-VN", "tôi bị đau tinh hoàn dữ dội", id="vi-severe"),
]


@pytest.mark.parametrize("language,text", MUST_STILL_FIRE)
def test_real_torsion_descriptions_still_fire(detector, language, text):
    """收緊之後真扭轉描述仍必須命中——這是本檔所有 over-trigger 斷言的對照組。

    ⚠️ 這些句子裡刻意含有守衛的**陷阱詞**：「兩小時前 / two hours ago /
    二時間前に / 두 시간 전에 / hai tiếng trước」——時態否定的過去詞表若收了
    裸「前 / ago / trước / 전에」，最典型的急症句子就會被整句抹掉。
    """
    assert _torsion_fired(detector, text, language), (
        f"真實扭轉描述被收緊後漏報（under-triage，不可逆）：{language} {text!r}"
    )
