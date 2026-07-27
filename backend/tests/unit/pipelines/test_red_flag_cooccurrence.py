"""紅旗共現組（部位詞 × 急性/嚴重度詞）的**雙向對稱**測試表。

為什麼要有這個檔案
────────────────────────────────────────
睪丸扭轉的規則層在三輪之內被「只往單一方向加測試」害了三次：

  第 1 輪  只加「必須命中」 → 補了裸關鍵字（睪丸痛／ball hurt）
           → 「my eyeball hurts a lot」「我想問睪丸痛要看哪一科」全變 critical，
             第 1 輪就 aborted_red_flag。
  第 2 輪  只加「不該命中」 → 把裸關鍵字收成**相鄰複合詞**（睪丸突然）
           → 「睪丸**兩個小時前**突然劇痛」不相鄰 → 5 語言 4 種真扭轉描述 0 命中。
  兩輪的單元測試都全綠，因為 e2e persona 台詞（「左邊睪丸突然劇烈疼痛」）剛好
  是相鄰語序 —— **情境台詞與關鍵字互相配適，測到的是實作不是行為。**

所以本檔的每一組斷言都必須成對出現，而且語料刻意**不**從
`scripts/e2e_realopenai/results/torsion_critical_zh.json` 的 persona 台詞抄：
語序變體（部位與修飾詞之間插入時間/方位/程度）、不同時間表達、有無標點、
口語 vs 書面，五語各自獨立寫。`test_no_case_is_copied_from_the_e2e_persona_line`
與 `test_e2e_persona_wording_is_not_the_only_one_that_fires` 把這件事釘死。

本檔守護五件事
────────────────────────────────────────
1. `MUST_FIRE`   ：真急症必須命中（含第三輪探針裡 7 筆 under-trigger 全數）。
2. `MUST_NOT_FIRE`：慢性/否定/假設/行政詢問/eyeball 不得命中。
3. 插入語結構測試：部位與修飾詞之間插入 2–8 字仍須命中
                  —— 直接釘死「相鄰子字串」這個錯誤實作方式。
4. 同情境多措辭  ：同一臨床情境用 ≥3 種措辭表達，全部要命中，
                  且其中 ≥2 種**完全不含任何相鄰複合 trigger**。
5. 結構不變式    ：共現詞表不得與主訴標籤/彼此重疊；當前發作證據詞表不得與
                  critical trigger 字面相交（否則生成式反例會被自己的 trigger 解除）。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.prompts.shared import URO_RED_FLAGS
from app.pipelines.red_flag_detector import RedFlagDetector
from app.utils.complaint_fallback_i18n import NAME_FALLBACK_I18N

LANGUAGES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")
TORSION = "testicular_pain_severe"

# 真跑 scripts/e2e_realopenai/results/torsion_critical_zh.json 的 persona 第 1 輪台詞。
# 本檔的語料**不得**與它相同或是它的子字串（見 test_no_case_is_copied_...）。
E2E_PERSONA_LINE = (
    "大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，走路都有困難。"
)


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


def _build(monkeypatch: pytest.MonkeyPatch, guard: bool = True) -> RedFlagDetector:
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = True
    settings.RED_FLAG_NEGATION_GUARD = guard
    det = RedFlagDetector(settings, _FakeDB())
    _run(det._load_rules())
    return det


@pytest.fixture
def detector(monkeypatch: pytest.MonkeyPatch) -> RedFlagDetector:
    return _build(monkeypatch)


def _fired(det: RedFlagDetector, text: str, language: str) -> bool:
    return any(
        a["canonical_id"] == TORSION for a in det._rule_based_detect(text, language)
    )


def _critical_hits(det: RedFlagDetector, text: str, language: str) -> list[tuple]:
    return [
        (a["canonical_id"], a.get("trigger_keywords"))
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# 語料：正方向（真急症，必須命中）
# ══════════════════════════════════════════════════════════════
# 五語各 ≥4 筆。每一筆都刻意與 persona 台詞不同：部位與修飾詞之間插入時間/方位、
# 不同的時間表達（今天凌晨／剛剛不到一小時前／昨天半夜）、口語（蛋蛋/キンタマ/불알/
# hòn dái）與書面（精巣/음낭/scrotum）混用、有無標點都有。
#
# ⚠️ 標 [P##] 的是 2026-07-27 第三輪主 agent 直接探針裡 **under-trigger 的 7 筆**，
#    一筆都不可以從這裡拿掉（`test_all_probe_under_trigger_cases_are_covered` 釘住）。
PROBE_UNDER_TRIGGER_CASES: tuple[tuple[str, str], ...] = (
    ("zh-TW", "我左邊睪丸兩個小時前突然劇痛，還吐了"),
    ("ja-JP", "二時間前に急に左の睾丸が激しく痛くなり、吐き気もあります"),
    ("ko-KR", "두 시간 전에 갑자기 왼쪽 고환이 심하게 아프고 토했어요"),
    ("vi-VN", "hai tiếng trước tinh hoàn trái đau dữ dội đột ngột, tôi buồn nôn"),
    ("zh-TW", "請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科"),
    ("zh-TW", "醫生請問一下我今天早上睪丸突然很痛痛到吐我不知道要掛哪一科"),
    ("en-US", "my right testicle is in severe pain since this morning"),
)

MUST_FIRE: list[tuple[str, str, str]] = [
    # ── zh-TW ──
    ("zh-TW", "我左邊睪丸兩個小時前突然劇痛，還吐了", "P01 部位與修飾詞間插入時間"),
    ("zh-TW", "請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科", "P15 描述症狀＋問科別"),
    (
        "zh-TW",
        "醫生請問一下我今天早上睪丸突然很痛痛到吐我不知道要掛哪一科",
        "P16 STT 無標點＋問科別",
    ),
    ("zh-TW", "蛋蛋從今天凌晨開始就非常痛，腫得跟雞蛋一樣大", "口語部位＋插入 8 字"),
    ("zh-TW", "右邊陰囊剛剛不到一小時前忽然痛到站不起來", "方位＋不同時間表達"),
    ("zh-TW", "我睪丸昨天半夜開始劇烈疼痛，一直到現在都沒有緩解", "書面語＋句尾含否定詞"),
    # ── en-US ──
    ("en-US", "my right testicle is in severe pain since this morning", "P17 最自然語序"),
    (
        "en-US",
        "two hours ago my left testicle suddenly started hurting badly",
        "對照組（第二輪即命中，不得倒退）",
    ),
    ("en-US", "sudden severe pain in my testicle", "對照組（第二輪即命中）"),
    (
        "en-US",
        "my scrotum has been in excruciating pain since about an hour ago and I threw up",
        "書面部位＋插入助動詞",
    ),
    (
        "en-US",
        "the pain in my left ball came on suddenly at midnight and it is unbearable",
        "口語部位＋詞邊界（ball ≠ eyeball）",
    ),
    (
        "en-US",
        "I woke up this morning with intense pain in my testicles, worst pain of my life",
        "修飾詞在部位詞之前（語序相反）",
    ),
    # ── ja-JP ──
    ("ja-JP", "二時間前に急に左の睾丸が激しく痛くなり、吐き気もあります", "P03 急に…睾丸 不相鄰"),
    ("ja-JP", "今朝から右の精巣がものすごく痛くて歩けません", "正式名称 精巣＋別の時間表現"),
    ("ja-JP", "一時間ほど前から陰嚢が急激に腫れて激痛があります", "陰嚢＋腫脹合併激痛"),
    ("ja-JP", "夜中に突然キンタマがものすごく痛くなって吐きました", "俗語部位＋修飾詞在前"),
    ("ja-JP", "昨夜から左の睾丸の痛みがひどくて我慢できないです", "「痛み…ひどい」語序"),
    # ── ko-KR ──
    ("ko-KR", "두 시간 전에 갑자기 왼쪽 고환이 심하게 아프고 토했어요", "P04 갑자기…고환 不相鄰"),
    ("ko-KR", "오늘 새벽부터 오른쪽 음낭이 너무 아파서 걷기 힘들어요", "음낭＋구어 강조"),
    ("ko-KR", "어젯밤부터 고환 부위가 극심하게 아픕니다", "書面體＋插入「부위가」"),
    ("ko-KR", "불알이 방금 전부터 갑자기 심해졌어요", "俗語部位＋插入時間"),
    ("ko-KR", "고환이 새벽에 꼬인 것처럼 심하게 아프고 구토했어요", "插入 13 字仍須命中"),
    # ── vi-VN ──
    (
        "vi-VN",
        "hai tiếng trước tinh hoàn trái đau dữ dội đột ngột, tôi buồn nôn",
        "P05 方位詞插在部位與修飾之間",
    ),
    ("vi-VN", "bìu bên phải của tôi sưng đau từ sáng nay, đau lắm", "bìu＋插入 18 字"),
    (
        "vi-VN",
        "tinh hoàn của tôi đau dữ dội từ nửa đêm, tôi nôn mấy lần",
        "書面語序＋不同時間表達",
    ),
    ("vi-VN", "tôi bị xoắn tinh hoàn hay sao mà đau quặn từ sáng nay", "修飾詞在部位詞之前"),
    (
        "vi-VN",
        "hòn dái bên trái đau nhói từ hai tiếng trước và tôi buồn nôn",
        "俗語部位＋方位插入",
    ),
]


@pytest.mark.parametrize(
    "language,text,why", MUST_FIRE, ids=[f"{lg}-{i}" for i, (lg, _t, _w) in enumerate(MUST_FIRE)]
)
def test_must_fire(detector, language, text, why):
    """真扭轉描述必須命中規則層 —— 漏報是不可逆的 under-triage。"""
    assert _fired(detector, text, language), f"[{why}] {language} {text!r} 漏報"


# ══════════════════════════════════════════════════════════════
# 語料：反方向（不得命中）
# ══════════════════════════════════════════════════════════════
# 五語各 ≥4 筆，措辭與第二輪 `test_red_flag_over_trigger.py` 的**不重複**
#（那個檔案原樣保留，兩份互為獨立樣本）。
MUST_NOT_FIRE: list[tuple[str, str, str]] = [
    # ── zh-TW ──
    ("zh-TW", "我睪丸痛已經半年了，不會很痛，就是悶悶的", "慢性、部位與嚴重度跨子句且被否定"),
    ("zh-TW", "我沒有睪丸突然劇痛的情形，只是小便有點慢", "前置否定"),
    ("zh-TW", "假如哪天蛋蛋突然很痛，我要打哪支電話", "假設語氣"),
    ("zh-TW", "我想請教一下陰囊很痛要掛哪一科", "純行政詢問（無時間錨點/伴隨症狀）"),
    ("zh-TW", "小便的時候會痛，睪丸腫痛倒是沒有", "子句尾否認"),
    ("zh-TW", "我很多年前睪丸很痛過，開刀之後就痊癒了", "時態否定"),
    # ── en-US ──
    ("en-US", "the eyeball on my right side is in severe pain", "詞邊界：eyeball ≠ ball"),
    (
        "en-US",
        "I've had a dull ache in my testicle for about six months, it's not severe",
        "慢性，嚴重度詞跨子句且被否定",
    ),
    ("en-US", "he denies any sudden scrotal pain or swelling", "前置否定"),
    ("en-US", "suppose my testicle suddenly hurts at night, what do I do", "假設語氣"),
    (
        "en-US",
        "I would like to ask which department treats severe testicle pain",
        "純行政詢問",
    ),
    (
        "en-US",
        "years ago my testicle pain was excruciating but it resolved after surgery",
        "時態否定",
    ),
    # ── ja-JP ──
    ("ja-JP", "半年前から睾丸に鈍い痛みがありますが、ひどくはないです", "慢性＋後置否定"),
    ("ja-JP", "急な睾丸の痛みはありません、排尿時だけ少し違和感があります", "後置否定"),
    ("ja-JP", "もし夜中に睾丸が激しく痛くなったらどうすればいいですか", "假設語氣（條件詞優先於時間錨點）"),
    ("ja-JP", "精巣の激痛は何科に行けばいいか教えてください", "純行政詢問"),
    ("ja-JP", "子供の頃に睾丸が激しく痛みましたが、完治しました", "時態否定"),
    # ── ko-KR ──
    ("ko-KR", "반년 전부터 고환이 은근히 불편한데 심하지는 않아요", "慢性（無急性/嚴重度詞）"),
    ("ko-KR", "갑작스러운 고환 통증은 없어요, 소변볼 때만 조금 불편해요", "後置否定"),
    ("ko-KR", "만약 고환이 갑자기 심하게 아프면 어디로 가야 하나요", "假設語氣"),
    ("ko-KR", "극심한 고환 통증은 무슨 과에 가야 하는지 궁금해요", "純行政詢問"),
    ("ko-KR", "예전에 고환이 심하게 아팠지만 수술 후 다 나았어요", "時態否定"),
    # ── vi-VN ──
    (
        "vi-VN",
        "tôi bị đau âm ỉ ở tinh hoàn khoảng sáu tháng nay, không dữ dội",
        "慢性，嚴重度詞跨子句且被否定",
    ),
    ("vi-VN", "bệnh nhân không có đau tinh hoàn đột ngột", "前置否定"),
    ("vi-VN", "nếu tinh hoàn đau dữ dội vào ban đêm thì tôi phải làm gì", "假設語氣"),
    ("vi-VN", "tôi muốn hỏi đau bìu dữ dội thì khám khoa nào", "純行政詢問"),
    (
        "vi-VN",
        "trước đây tinh hoàn đau dữ dội nhưng sau khi mổ đã khỏi hẳn",
        "時態否定",
    ),
]


# ── 共現組**自己**新增的誤報面（2026-07-27 第三輪獨立對抗集實測）────────
# 共現組把「相鄰」放寬成「同子句 ＋ 距離上限」，於是多出一種新的錯誤：
# 屬於**別的部位**的急性詞被配到睪丸部位詞上。兩筆都是實測出來的，不是想像的。
COOCCURRENCE_OWN_FALSE_POSITIVES: list[tuple[str, str, str]] = [
    (
        "zh-TW",
        "我今天早上肚子突然很痛睪丸沒事",
        "STT 未補標點 → 屬於「肚子」的「突然」被配到「睪丸」；靠子句尾「沒事」擋下",
    ),
    (
        "ja-JP",
        "睾丸は大丈夫ですが、今朝から腰が激しく痛みます",
        "跨子句：屬於「腰」的「激しく」不得配到「睾丸」",
    ),
    (
        "vi-VN",
        "tinh hoàn tôi ổn, nhưng sáng nay bụng đau dữ dội",
        "跨子句：屬於「bụng」的「dữ dội」不得配到「tinh hoàn」",
    ),
    (
        "en-US",
        "the basketball hit me and my eyeball hurts severely",
        "basketball / eyeball 都不得被當成部位詞 ball",
    ),
]

MUST_NOT_FIRE.extend(COOCCURRENCE_OWN_FALSE_POSITIVES)


@pytest.mark.parametrize(
    "language,text,why",
    MUST_NOT_FIRE,
    ids=[f"{lg}-{i}" for i, (lg, _t, _w) in enumerate(MUST_NOT_FIRE)],
)
def test_must_not_fire(detector, language, text, why):
    """非「現在的症狀陳述」不得判 critical —— 誤報＝整場問診被中止。"""
    hits = _critical_hits(detector, text, language)
    assert hits == [], f"[{why}] {language} {text!r} 誤觸發：{hits}"


def test_both_directions_cover_all_five_languages():
    """任一方向少一個語言，那個語言就有一半的防線是空的。"""
    for lang in LANGUAGES:
        fire = [t for lg, t, _ in MUST_FIRE if lg == lang]
        no_fire = [t for lg, t, _ in MUST_NOT_FIRE if lg == lang]
        assert len(fire) >= 4, f"{lang} MUST_FIRE 只有 {len(fire)} 筆（需 ≥4）"
        assert len(no_fire) >= 4, f"{lang} MUST_NOT_FIRE 只有 {len(no_fire)} 筆（需 ≥4）"


def test_all_probe_under_trigger_cases_are_covered():
    """第三輪探針的 7 筆 under-trigger 一筆都不可以從 MUST_FIRE 消失。"""
    present = {(lg, t) for lg, t, _ in MUST_FIRE}
    missing = [c for c in PROBE_UNDER_TRIGGER_CASES if c not in present]
    assert missing == [], f"探針 under-trigger 案例被拿掉：{missing}"


def test_no_case_is_copied_from_the_e2e_persona_line():
    """語料不得抄 e2e persona 台詞（抄了就是拿實作配適測試）。"""
    for lang, text, _why in MUST_FIRE + MUST_NOT_FIRE:
        assert text != E2E_PERSONA_LINE, text
        assert text not in E2E_PERSONA_LINE, f"{lang} {text!r} 是 persona 台詞的子字串"
        assert E2E_PERSONA_LINE not in text, f"{lang} {text!r} 內含整句 persona 台詞"


# ══════════════════════════════════════════════════════════════
# 3. 插入語結構測試 —— 直接釘死「相鄰子字串」這個錯誤實作
# ══════════════════════════════════════════════════════════════
# 每個語言給「部位詞前綴 + 插入語 + 修飾詞後綴」的模板，插入語從 0 字到 8 字。
# 只要有人把共現組改回相鄰複合詞比對，非零插入的那幾筆立刻紅。
_INSERTION_TEMPLATES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # (部位詞結尾的前綴, 修飾詞開頭的後綴, 中間插入語)
    "zh-TW": ("我左邊睪丸", "突然劇烈疼痛，還吐了", ("", "兩個", "兩小時前", "今天早上", "從今天凌晨", "大概兩個小時前")),
    "en-US": (
        "my left testicle ",
        " severe pain since this morning",
        ("", "has", "has been in", "since today has", "started having really"),
    ),
    "ja-JP": ("左の睾丸が", "激しく痛みます", ("", "二時間", "二時間前から", "今朝から", "さっきから")),
    "ko-KR": (
        "왼쪽 고환이 ",
        "심하게 아파요",
        ("", "두 시간 전부터 ", "오늘 아침부터 ", "방금 전부터 ", "어젯밤부터 계속 "),
    ),
    "vi-VN": (
        "tinh hoàn ",
        " đau dữ dội, tôi buồn nôn",
        ("", "bên trái", "bên phải", "từ sáng nay", "từ hai tiếng trước"),
    ),
}

_INSERTION_CASES = [
    pytest.param(lang, prefix + gap + suffix, gap, id=f"{lang}-gap{len(gap)}")
    for lang, (prefix, suffix, gaps) in _INSERTION_TEMPLATES.items()
    for gap in gaps
]


@pytest.mark.parametrize("language,text,gap", _INSERTION_CASES)
def test_insertion_between_site_and_modifier_still_fires(detector, language, text, gap):
    """部位詞與修飾詞之間插入時間/方位詞，仍必須命中。

    這條是本輪最重要的結構性斷言：**相鄰子字串**的實作方式在插入語一出現就失效，
    而真人語序天天在插入時間、方位、程度。gap="" 是對照組（相鄰語序也要照樣命中）。
    """
    assert _fired(detector, text, language), (
        f"插入 {len(gap)} 字（{gap!r}）後漏報 → 共現組退化成相鄰比對：{text!r}"
    )


def test_insertion_templates_cover_non_adjacent_gaps_in_every_language():
    """每語言至少要有一個 2 字以上的插入語，否則這條測試等於沒測到插入。"""
    for lang, (_p, _s, gaps) in _INSERTION_TEMPLATES.items():
        assert any(len(g) >= 2 for g in gaps), lang


# ══════════════════════════════════════════════════════════════
# 4. 同一臨床情境的多種措辭都要命中
# ══════════════════════════════════════════════════════════════
# 情境固定：「數小時前突然發作的單側睪丸劇痛，合併嘔吐」。
# 斷言有兩層：(a) 三種措辭全部命中；(b) 其中至少兩種**完全不含任何相鄰複合
# trigger** —— 也就是它們只能靠共現組接住。沒有 (b)，這條測試可以靠「多列幾句
# 剛好含 persona 同形關鍵字的話」蒙混過去。
_SAME_SCENARIO_PARAPHRASES: dict[str, tuple[str, ...]] = {
    "zh-TW": (
        "我左邊睪丸兩個小時前突然劇痛，還吐了",
        "睪丸大概兩小時前開始劇烈疼痛，痛到吐出來",
        "兩個鐘頭前開始，我的睪丸痛到受不了，還吐了兩次",
    ),
    "en-US": (
        "my right testicle is in severe pain since this morning",
        "about two hours ago I got sudden pain in my right testicle and threw up",
        "the pain in my left testicle is excruciating, started two hours ago",
    ),
    "ja-JP": (
        "二時間前に急に左の睾丸が激しく痛くなり、吐き気もあります",
        "二時間ほど前から左の精巣がものすごく痛くて吐きました",
        "睾丸が二時間前から激痛で、吐き気が止まりません",
    ),
    "ko-KR": (
        "두 시간 전에 갑자기 왼쪽 고환이 심하게 아프고 토했어요",
        "두 시간쯤 전부터 왼쪽 고환 부위가 극심하게 아프고 구토했어요",
        "고환이 두 시간 전부터 너무 아파서 토할 것 같아요",
    ),
    "vi-VN": (
        "hai tiếng trước tinh hoàn trái đau dữ dội đột ngột, tôi buồn nôn",
        "tinh hoàn của tôi đau dữ dội từ hai tiếng trước, tôi nôn mấy lần",
        "khoảng hai tiếng trước bìu bên trái của tôi sưng đau và buồn nôn",
    ),
}


def _adjacent_triggers_present(text: str) -> list[str]:
    """文中出現的**相鄰複合** trigger（不看否定，只看字面 + 詞邊界）。"""
    flag = next(f for f in URO_RED_FLAGS if f["canonical_id"] == TORSION)
    keywords = list(flag.get("triggers") or [])
    for kws in (flag.get("triggers_by_lang") or {}).values():
        keywords.extend(kws)
    lowered = text.lower()
    return [kw for kw in keywords if rfd_module._keyword_in_text(kw, lowered)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_e2e_persona_wording_is_not_the_only_one_that_fires(detector, language):
    """同一臨床情境的 ≥3 種措辭全部要命中，且 ≥2 種只能靠共現組接住。"""
    variants = _SAME_SCENARIO_PARAPHRASES[language]
    assert len(variants) >= 3, language
    for text in variants:
        assert _fired(detector, text, language), f"{language} 措辭變體漏報：{text!r}"

    carried_by_cooccurrence = [t for t in variants if not _adjacent_triggers_present(t)]
    assert len(carried_by_cooccurrence) >= 2, (
        f"{language} 只有 {len(carried_by_cooccurrence)} 種措辭不含相鄰複合 trigger"
        f"——這組測試可能又在配適關鍵字表而不是測行為"
    )


def test_paraphrases_are_not_substrings_of_each_other():
    """三種措辭要真的不同，不能是同一句加減幾個字。"""
    for lang, variants in _SAME_SCENARIO_PARAPHRASES.items():
        for i, a in enumerate(variants):
            for j, b in enumerate(variants):
                if i != j:
                    assert a not in b, f"{lang}: {a!r} 是 {b!r} 的子字串"


# ══════════════════════════════════════════════════════════════
# 5. 結構不變式
# ══════════════════════════════════════════════════════════════


def _cooccurrence_groups() -> list[dict[str, Any]]:
    flag = next(f for f in URO_RED_FLAGS if f["canonical_id"] == TORSION)
    return list(flag.get("trigger_cooccurrence") or [])


def _all_critical_trigger_strings() -> set[str]:
    out: set[str] = set()
    for flag in URO_RED_FLAGS:
        if flag.get("severity") != "critical":
            continue
        out.update(kw for kw in (flag.get("triggers") or []) if kw)
        for kws in (flag.get("triggers_by_lang") or {}).values():
            out.update(kw for kw in kws if kw)
        for group in flag.get("trigger_cooccurrence") or []:
            out.update(group.get("site_terms", []))
            out.update(group.get("acuity_terms", []))
    return out


def test_cooccurrence_group_is_declared_and_wired():
    """共現組要真的存在，而且 detector 要以 canonical_id 查得到它。

    以 canonical_id 查表（而非塞進 rule dict）是刻意的：生產 DB 的 red_flag_rules
    沒有對應欄位，若只從內建 fallback 帶出來，哪天規則表被 seed 就會靜默退回
    「只有相鄰複合詞」的舊行為 —— 正是本輪要修掉的漏報。
    """
    groups = _cooccurrence_groups()
    assert groups, "testicular_pain_severe 沒有共現組"
    assert rfd_module._CANONICAL_COOCCURRENCE.get(TORSION) == groups


def test_cooccurrence_terms_contain_no_bare_pain_word():
    """急性/嚴重度表不得收裸『痛』類詞，否則慢性主訴會全變 critical。

    共現組能同時解掉 over/under 兩個方向，靠的就是「部位 ⨯ 急性/嚴重度」這個
    乘法裡第二項不含裸痛 —— 一旦有人塞進「痛」「pain」「아파」「đau」，
    「我睪丸痛三個月了」立刻變成 abort。
    """
    bare = {"痛", "疼", "疼痛", "pain", "hurt", "hurts", "ache", "痛み", "아파", "아픔",
            "통증", "đau", "痛い"}
    for group in _cooccurrence_groups():
        for term in group.get("acuity_terms", []):
            assert term.lower().strip() not in bare, f"急性詞表混入裸痛詞：{term!r}"
        for term in group.get("site_terms", []):
            assert term.lower().strip() not in bare, f"部位詞表混入裸痛詞：{term!r}"


def test_cooccurrence_terms_are_not_chief_complaint_labels():
    """單一共現詞不得等於主訴選單標籤。

    共現組要求兩個詞同時出現才命中，本來就比裸關鍵字安全；但若某個**單詞**
    就等於主訴標籤（例如把「睪丸疼痛」整個塞進 site_terms），只要病患再講一個
    嚴重度詞就等同複誦主訴被 abort。
    """
    labels = {
        text.lower().strip()
        for by_lang in NAME_FALLBACK_I18N.values()
        for text in by_lang.values()
    }
    offenders = [
        term
        for group in _cooccurrence_groups()
        for key in ("site_terms", "acuity_terms")
        for term in group.get(key, [])
        if term.lower().strip() in labels
    ]
    assert offenders == [], f"共現詞等於主訴標籤：{offenders}"


def test_site_and_acuity_term_sets_are_disjoint():
    """同一個詞不得同時是部位詞與急性詞，否則單獨一個詞就能自我配對成命中。"""
    for group in _cooccurrence_groups():
        sites = {t.lower() for t in group.get("site_terms", [])}
        acuities = {t.lower() for t in group.get("acuity_terms", [])}
        assert sites.isdisjoint(acuities), sites & acuities


def test_current_episode_markers_disjoint_from_critical_triggers():
    """「當前發作證據」詞表不得與任何 critical trigger 字面相交。

    2026-07-27 實測過的破口：越南文的「ói」（嘔吐）是 trigger「đau nhói」的子字串
    → 生成式反例「trước đây đau nhói ... đã khỏi hẳn」被自己的 trigger 當成
    「這件事現在正在發生」，時態否定守衛因此解除 → 誤觸發 critical。
    這個方向的錯誤在人工閱讀時幾乎看不出來，只能靠結構性斷言擋。
    """
    markers = rfd_module._CURRENT_EPISODE_MARKERS
    triggers = _all_critical_trigger_strings()
    offenders = [
        (marker, trigger)
        for marker in markers
        for trigger in triggers
        if marker in trigger or trigger in marker
    ]
    assert offenders == [], f"當前發作證據詞與 critical trigger 相交：{offenders}"


def test_current_episode_markers_cover_all_five_languages():
    """五語都要有時間錨點，否則該語言的行政詢問守衛仍會吃掉真急症。"""
    probes = {
        "zh-TW": "今天",
        "en-US": "this morning",
        "ja-JP": "今朝",
        "ko-KR": "오늘",
        "vi-VN": "sáng nay",
    }
    for lang, probe in probes.items():
        assert probe in rfd_module._CURRENT_EPISODE_MARKERS, lang


# ══════════════════════════════════════════════════════════════
# 6. 語境守衛的兩個方向（BLOCKER B 回歸）
# ══════════════════════════════════════════════════════════════


class TestAdminInquiryGuardBothDirections:
    """行政詢問守衛：純詢問要抑制，但「描述症狀＋順便問科別」不得抑制。"""

    @pytest.mark.parametrize(
        "language,text",
        [
            ("zh-TW", "請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科"),
            ("zh-TW", "醫生請問一下我今天早上睪丸突然很痛痛到吐我不知道要掛哪一科"),
            ("en-US", "I want to ask which department, my testicle has severe pain since this morning and I threw up"),
            ("ja-JP", "今朝から睾丸が激しく痛くて吐き気もあります、何科に行けばいいですか"),
            ("ko-KR", "오늘 아침부터 고환이 심하게 아프고 토했어요, 무슨 과에 가야 하는지 궁금해요"),
            ("vi-VN", "sáng nay tinh hoàn tôi đau dữ dội và buồn nôn, tôi muốn hỏi khám khoa nào"),
        ],
    )
    def test_symptom_plus_department_question_is_not_suppressed(
        self, detector, language, text
    ):
        """病患一邊描述當前症狀一邊問掛哪一科 —— 最常見的真實情境，不得被吃掉。"""
        assert _fired(detector, text, language), f"{language} {text!r} 被行政詢問守衛誤抑制"

    @pytest.mark.parametrize(
        "language,text",
        [
            ("zh-TW", "我想請教一下陰囊很痛要掛哪一科"),
            ("en-US", "I would like to ask which department treats severe testicle pain"),
            ("ja-JP", "精巣の激痛は何科に行けばいいか教えてください"),
            ("ko-KR", "극심한 고환 통증은 무슨 과에 가야 하는지 궁금해요"),
            ("vi-VN", "tôi muốn hỏi đau bìu dữ dội thì khám khoa nào"),
        ],
    )
    def test_pure_department_question_still_suppressed(self, detector, language, text):
        """對照組：沒有時間錨點也沒有伴隨症狀的純行政詢問，仍必須抑制。

        沒有這一組，上面那組可以靠「把行政詢問守衛整個刪掉」通過。
        """
        assert _critical_hits(detector, text, language) == [], f"{language} {text!r}"


class TestPastResolvedGuardBothDirections:
    """時態否定守衛：純過去式要抑制，但「舊病史＋今天復發」不得抑制。"""

    @pytest.mark.parametrize(
        "language,text",
        [
            ("zh-TW", "我以前睪丸很痛過後來好了，今天早上又突然劇痛還吐了"),
            ("en-US", "I used to have testicle pain that went away, but this morning it came on suddenly and severe"),
            ("ja-JP", "昔も睾丸が激しく痛くて治りましたが、今朝からまた激痛です"),
            ("ko-KR", "예전에 고환이 아팠다가 나았는데 오늘 아침부터 갑자기 심하게 아파요"),
            # ⚠️ 舊病史與復發描述必須落在**同一子句**才有共現（逗號是子句邊界）。
            # 這是共現組刻意的取捨：跨子句配對會讓「我眼睛突然很痛，睪丸沒事」誤命中。
            ("vi-VN", "trước đây tinh hoàn tôi đau rồi khỏi nhưng sáng nay tinh hoàn lại đau dữ dội"),
        ],
    )
    def test_old_history_plus_today_recurrence_is_not_suppressed(
        self, detector, language, text
    ):
        assert _fired(detector, text, language), f"{language} {text!r} 被時態否定守衛誤抑制"

    @pytest.mark.parametrize(
        "language,text",
        [
            ("zh-TW", "我很多年前睪丸很痛過，開刀之後就痊癒了"),
            ("en-US", "years ago my testicle pain was excruciating but it resolved after surgery"),
            ("ja-JP", "子供の頃に睾丸が激しく痛みましたが、完治しました"),
            ("ko-KR", "예전에 고환이 심하게 아팠지만 수술 후 다 나았어요"),
            ("vi-VN", "trước đây tinh hoàn đau dữ dội nhưng sau khi mổ đã khỏi hẳn"),
        ],
    )
    def test_pure_past_history_still_suppressed(self, detector, language, text):
        """對照組：真的只是舊病史，仍必須抑制。"""
        assert _critical_hits(detector, text, language) == [], f"{language} {text!r}"


# ══════════════════════════════════════════════════════════════
# 7. 共現組的生成式反例（每個 site × acuity 組合都自動長出反例）
# ══════════════════════════════════════════════════════════════
# 新增部位詞或急性詞時，反例會自動出現 —— 不會再有「補了詞但沒補反例」。
# 用單一 test 迴圈收集失敗（組合數是乘積，parametrize 會炸成上千個 case）。
_COUNTEREXAMPLE_FRAMES: tuple[str, ...] = (
    "我沒有{site}{acuity}的情形",          # 前置否定
    "{site}{acuity}倒是沒有",              # 子句尾否認
    "如果{site}{acuity}要怎麼辦",           # 假設語氣
    "我想問{site}{acuity}要看哪一科",       # 純行政詢問
    "以前{site}{acuity}過，但現在完全好了",  # 時態否定
)


def test_generated_counterexamples_for_every_site_acuity_pair(detector):
    """每個 site × acuity 組合放進五種「非症狀陳述」框架都不得判 critical。"""
    failures: list[str] = []
    for group in _cooccurrence_groups():
        for site in group.get("site_terms", []):
            for acuity in group.get("acuity_terms", []):
                for frame in _COUNTEREXAMPLE_FRAMES:
                    text = frame.format(site=site, acuity=acuity)
                    hits = _critical_hits(detector, text, "zh-TW")
                    if hits:
                        failures.append(f"{text!r} → {hits}")
    assert failures == [], (
        "共現詞在非症狀陳述語境誤觸發 critical（會中止問診），前 10 筆：\n"
        + "\n".join(failures[:10])
        + f"\n（共 {len(failures)} 筆）"
    )


def test_generated_positive_for_every_site_acuity_pair(detector):
    """對照組：同樣的每個組合，放進「現在正在發生」的框架都必須命中。

    沒有這一組，上面的反例測試可以靠「把共現組刪掉」全過 —— 那正是第一輪與
    第二輪各自犯過的單向錯誤。框架刻意帶插入語（「今天早上」在部位與修飾之間），
    順便把相鄰比對再釘一次。
    """
    failures: list[str] = []
    for group in _cooccurrence_groups():
        for site in group.get("site_terms", []):
            for acuity in group.get("acuity_terms", []):
                text = f"我{site}今天早上{acuity}，還吐了"
                if not _fired(detector, text, "zh-TW"):
                    failures.append(repr(text))
    assert failures == [], (
        "共現組在「現在正在發生」的框架下漏報，前 10 筆：\n"
        + "\n".join(failures[:10])
        + f"\n（共 {len(failures)} 筆）"
    )


# ══════════════════════════════════════════════════════════════
# 8. kill-switch 與詞邊界
# ══════════════════════════════════════════════════════════════


class TestOwnFalsePositiveFixesDidNotCreateMisses:
    """為了修共現組自己的誤報而加的兩個機制，各自的**反方向**對照組。

    這兩個機制都是「增加抑制」，也就是這一輪唯一會製造漏報的改動方向 ——
    所以每一個都必須成對釘住它不該抑制的情形。
    """

    @pytest.mark.parametrize(
        "text",
        [
            # 「沒事吧」是病患在**問**自己嚴不嚴重，不是否認症狀
            "睪丸突然很痛沒事吧",
            "醫生我睪丸腫痛沒問題嗎",
            "陰囊剛剛突然劇痛，這樣沒事嗎",
        ],
    )
    def test_tag_question_is_not_a_denial(self, detector, text):
        """子句尾「沒事」pattern 不得把「沒事吧／沒問題嗎」這種反問當成否認。"""
        assert _fired(detector, text, "zh-TW"), f"反問句被當成否認 → 漏報：{text!r}"

    @pytest.mark.parametrize(
        "language,text",
        [
            # CJK 檔（16 字）內的正常插入語一律要命中
            ("zh-TW", "睪丸從昨天半夜開始就突然劇痛"),
            ("ja-JP", "睾丸が三十分ほど前から急に激しく痛みます"),
            ("ko-KR", "고환이 오늘 아침부터 계속 심하게 아파요"),
            # 拉丁檔（30 字元）——一個詞就要 5–10 字元，收到 16 會整批漏掉
            ("en-US", "my testicle has been in severe pain since two hours ago"),
            ("vi-VN", "tinh hoàn từ hai tiếng trước đau dữ dội"),
        ],
    )
    def test_per_script_window_does_not_clip_normal_speech(
        self, detector, language, text
    ):
        """依書寫系統分檔的距離上限，不得把任何一種語言的正常語序切掉。"""
        assert _fired(detector, text, language), f"{language} 距離上限過緊 → 漏報：{text!r}"

    def test_distance_is_measured_in_morpheme_units_not_characters(self):
        """距離上限的單位是語素當量，不是裸字元。

        取代舊的 `test_cjk_window_is_tighter_than_latin`：那條測的是「依書寫系統
        分兩檔字元數」這個**實作手段**，而分兩檔字元數是拿字元近似語素，近似不足
        ——2026-07-27 第三輪 Gate 雙向探針實測，拉丁/越南文的正常語序被 30 字元的
        上限整批切掉（越南文以音節分寫，一個語意單位就要 2–3 個空白分隔音節）。
        現在改成單一上限、以語素當量計距，這條測的是**行為**：
        同一段語意在五種書寫系統下必須換算出相近的距離。
        """
        # CJK：字≈語素，一字一單位（與改用單位前的字元計數完全相同）
        assert rfd_module._span_units("兩個小時前") == 5
        assert rfd_module._span_units("急に激しく") == 5
        # 拉丁/越南文：以空白分隔的詞為單位，詞內字母不計費
        assert rfd_module._span_units("about ninety minutes ago") == 3
        assert rfd_module._span_units("từ lúc nửa đêm bỗng nhiên") == 5
        # 行為判準：同一段語意（「兩小時前」）在五種語言都必須**遠**小於上限，
        # 才不會有任何一種語言被距離系統性地切掉。
        # 註（誠實記下殘餘不對稱）：諺文音節塊仍逐字計 1（韓文 7 單位 vs 英文 2），
        # 所以韓文的有效視窗比拉丁文緊。這是**刻意保留**的——韓文的既有行為是以
        # 字元計數驗收過的，改成按空白計詞會單方面放寬韓文（增加誤報方向），
        # 不在本輪的雙向語料涵蓋範圍內。要改需要先補韓文的雙向語料。
        equivalents = {
            "兩個小時前": 5,
            "two hours ago": 2,
            "二時間前に": 5,
            "두 시간 전에": 7,
            "hai tiếng trước": 2,
        }
        for phrase, expected in equivalents.items():
            assert rfd_module._span_units(phrase) == expected, phrase
            assert (
                rfd_module._span_units(phrase) * 2
                < rfd_module._COOCCURRENCE_WINDOW_UNITS
            ), f"{phrase!r} 佔掉過多預算 → 該語言的正常語序會被切掉"

        # 迴歸釘子：這三句的**字元**長度都超過舊的拉丁 30 字上限（＝當初的漏報），
        # 換算成語素當量之後必須遠低於上限。
        for gap_text in (
            ", about ninety minutes ago, became ",
            " bên phải của tôi từ lúc nửa đêm bỗng nhiên đau ",
            " bên trái khoảng một tiếng trước sưng lên và đau ",
        ):
            assert len(gap_text) > 30
            assert rfd_module._span_units(gap_text) < rfd_module._COOCCURRENCE_WINDOW_UNITS

    def test_other_body_part_in_unpunctuated_clause_fires_by_policy(self, detector):
        """別部位誤配（無標點同一子句）**就是會觸發** —— 這是臨床拍板的政策選擇。

        2026-07-27 臨床拍板：「紅旗規則層偏誤報：寧可多中止幾場。第三人稱轉述、
        別部位誤配這類殘餘誤報就留著。誤中止的代價是病患白等、護理師走一趟，可逆。」

        原本這條是 `xfail(strict=False)`，語意是「缺陷、暫時容忍」——那會誘導下一個
        人把它「修好」，而修法必然是加一條抑制守衛，直接開出漏報（距離分不出
        「別的部位」與「隔著病史敘述的復發描述」，收緊就會把
        「고환…20 字…갑자기」這種真急症變成漏報；改用通用部位詞表則會把
        「睪丸和肚子都突然很痛」抹掉）。所以第四輪 Gate 把它改成**正向斷言**：
        有人加抑制擋掉它的時候，這條會當場變紅。

        ⚠️ 要改這個期待值需要**新的臨床拍板**，不是工程可以自行決定。
        """
        hits = _critical_hits(
            detector, "고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요", "ko-KR"
        )
        assert [canonical for canonical, _kw in hits] == ["testicular_pain_severe"]

    def test_residual_does_not_extend_to_punctuated_clauses(self, detector):
        """對照組：只要有標點（多數語言的多數情況），跨子句就一定不配對。

        這條界定了上面那個殘餘的**範圍** —— 它只在「同一子句且無標點」時成立，
        不是「別的部位急性痛一律誤報」。
        """
        for language, text in (
            ("ko-KR", "고환은 괜찮은데, 오늘 아침부터 배가 심하게 아파요"),
            ("zh-TW", "睪丸沒問題，今天早上肚子突然很痛"),
            ("ja-JP", "睾丸は大丈夫ですが、今朝から腰が激しく痛みます"),
        ):
            assert _critical_hits(detector, text, language) == [], f"{language} {text!r}"


class TestKillSwitchAndBoundary:
    def test_cooccurrence_still_works_with_guard_off(self, monkeypatch):
        """否定守衛關掉時共現組仍要運作（它是比對結構，不是守衛的一部分）。"""
        det = _build(monkeypatch, guard=False)
        assert _fired(det, "我左邊睪丸兩個小時前突然劇痛，還吐了", "zh-TW")

    def test_boundary_still_applies_to_site_terms_with_guard_off(self, monkeypatch):
        """守衛關掉也不能讓 eyeball 變成 ball（詞邊界是比對精度，不隨 kill-switch 走）。"""
        det = _build(monkeypatch, guard=False)
        assert _critical_hits(det, "the eyeball on my right side is in severe pain", "en-US") == []

    @pytest.mark.parametrize(
        "text",
        [
            "the eyeball on my right side is in severe pain",
            "my eyeballs suddenly hurt so much",
            "the ballpark figure was severe, my eyes hurt",
        ],
    )
    def test_site_term_requires_both_word_edges(self, detector, text):
        """部位詞「ball」前後緣都要詞邊界：eyeball / eyeballs / ballpark 都不得命中。"""
        assert _critical_hits(detector, text, "en-US") == [], text

    @pytest.mark.parametrize(
        "text",
        [
            "my left ball started hurting suddenly two hours ago",
            "my balls are in severe pain since midnight",
        ],
    )
    def test_real_ball_complaint_still_fires(self, detector, text):
        """對照組：真的講 ball / balls 仍必須命中（詞邊界不可換成漏報）。"""
        assert _fired(detector, text, "en-US"), text
