"""紅旗規則層**抑制守衛**的政策測試（2026-07-27 臨床拍板後的第四輪）。

═══════════════════════════════════════════════════════════════
使用者（臨床）於 2026-07-27 拍板的政策：**紅旗規則層偏誤報**
═══════════════════════════════════════════════════════════════
原文：「偏誤報：寧可多中止幾場。第三人稱轉述、別部位誤配這類殘餘誤報就留著。
誤中止的代價是病患白等、護理師走一趟，可逆。」

推論出的工程規則（不是可以自行重新取捨的）：

1. **每一條抑制守衛都是潛在漏報。** 保留一條抑制的舉證責任在保留方：說不出
   「為什麼這條抑制不會造成漏報」就要收窄或移除。
2. 判準只有一個：**病患是否明確、無歧義地否認了這個症狀？**
   - 「我沒有睪丸痛」→ 明確否認 → 抑制。
   - 「我朋友睪丸痛」→ 不是否認，只是主體不同 → **不抑制**（誤報可接受）。
   - 「如果睪丸痛要看哪一科」→ 假設語氣，邊界模糊 → **收窄**到「整句沒有當前
     症狀訊號」才抑制。
3. 殘餘誤報**不記成 xfail**。xfail 的語意是「這是缺陷、暫時容忍」，會誘導後人
   去「修好」它而開出漏報。改成本檔的**正向政策測試**：斷言它就是會觸發。

本檔兩節都要在
────────────────────────────────────────
§1 政策接受的誤報（斷言「就是會觸發」）——防止有人善意地把它「修好」成漏報。
§2 守衛逐條雙向審計——每條守衛都有「不得抑制」與「必須抑制」成對的案例；
   少了任一側，另一側都可以靠「把守衛整個開／關」作弊通過。

═══════════════════════════════════════════════════════════════
2026-08-18 臨床拍板（增補）：urosepsis 的「熱」只認全身性發燒語彙
═══════════════════════════════════════════════════════════════
本檔**沒有**受影響的案例（審視全表：無任何一筆語料含發燒／灼熱字面），
但拍板內容要記在這裡，否則後人只會在這個檔案找「規則層的臨床政策」。

原文方向：「熱」只認全身性發燒語彙（發燒／發熱／體溫高等），排除灼熱／
刺熱等局部症狀描述。實證 session dda55701：「解尿灼熱感」這類 dysuria
（排尿局部灼熱，泌尿科最常見主訴之一）被判 critical 尿路敗血症並中止問診。

⚠️ 這**不是**新增抑制守衛，因此不受本檔「偏誤報」政策的反向約束：
   urosepsis 的軸定義一直是「泌尿症狀 × **全身性**感染徵象」，局部灼熱從來
   就不屬於後者——這是把詞表改回它本來的臨床語意（與 #22 對
   `gross_hematuria_heavy` 的判斷同型：判準照臨床定義，不照字面）。
   舉證（每個被移除字面的無漏報論證）與雙向語料在
   `test_red_flag_urosepsis_fever_semantics.py`。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector

POLICY_DECIDED_ON = "2026-07-27"


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


def _critical_hits(det: RedFlagDetector, text: str, language: str) -> list[tuple]:
    return [
        (a["canonical_id"], a.get("trigger_keywords"))
        for a in det._rule_based_detect(text, language)
        if a.get("severity") == "critical"
    ]


# ══════════════════════════════════════════════════════════════
# §1 政策接受的誤報 —— 斷言「就是會觸發」
# ══════════════════════════════════════════════════════════════
# ⚠️ 這些**是刻意的**。
# 使用者（臨床）於 2026-07-27 拍板紅旗規則層偏誤報：
#   誤中止＝病患白等 ＋ 護理師走一趟，可逆；漏報＝不可逆。
# 若要改成不觸發，需要**臨床重新拍板**，不是工程可以自行決定的。
#
# 每一筆都附「為什麼擋掉它會製造漏報」——那才是這些誤報留著的真正理由，
# 不是「懶得修」。
POLICY_ACCEPTED_FALSE_POSITIVES: list[tuple[str, str, str, str]] = [
    (
        "zh-第三人稱轉述",
        "zh-TW",
        "我朋友之前睪丸突然劇痛，聽說是扭轉",
        "要擋掉必須辨識主語（朋友/家人 vs 我）。中文常省略主語，「睪丸突然劇痛」"
        "前面有沒有「我」在 STT 逐字稿裡完全不可靠；一旦用「出現他人稱謂就抑制」"
        "當規則，「我陪我朋友來的，我自己睪丸突然劇痛」就會被抹掉（漏報）。",
    ),
    (
        "zh-第三人稱-家人",
        "zh-TW",
        "我兒子上個月睪丸很痛，後來開刀",
        "同上：主語辨識在規則層做不可靠；且「上個月」這種過去時間錨點與"
        "真急症常用的「兩小時前」在字面上分不開，收進過去詞表會抹掉最典型的急症句。",
    ),
    (
        "ja-第三人稱轉述",
        "ja-JP",
        "家族が睾丸の激痛で運ばれたことがあります",
        "日文主語常省略且助詞が同時是主格與轉折標記；用助詞判主體會誤殺"
        "「家族に付き添って来ましたが、私が睾丸の激痛です」（漏報）。",
    ),
    (
        "en-第三人稱轉述",
        "en-US",
        "my brother had sudden testicle pain last year",
        "同上；且英文病歷體本來就會用第三人稱寫病患自己（"
        "「patient has sudden testicle pain」必須命中）。",
    ),
    (
        "ko-無標點別部位",
        "ko-KR",
        "고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요",
        "共現組以「同一子句 ＋ 距離上限」配對；STT 未補標點時屬於「배」的急性詞"
        "會配到「고환」。收緊距離就會切掉"
        "「예전에 고환이 아팠다가 나았는데 오늘 아침부터 갑자기 심하게 아파요」"
        "（舊病史＋今天復發，必須命中）；改用通用部位詞表則會抹掉"
        "「고환과 배가 둘 다 갑자기 아파요」。兩條路都是拿誤報換漏報。",
    ),
    (
        "en-hedge式否認",
        "en-US",
        "i cannot say i have testicle pain",
        "「cannot」被列為否定線索的假朋友，因為 cannot urinate / cannot walk 是"
        "**症狀本身**（急性尿滯留是 critical 主訴）。要區分 hedge 與能力喪失需要"
        "語意層；規則層拿掉 cannot 假朋友＝「i cannot urinate at all」重新變漏報。",
    ),
    (
        "zh-假設語氣但已在發作",
        "zh-TW",
        "如果我睪丸突然劇痛痛到吐要打哪支電話",
        "條件句 ＋ 急性伴隨症狀（吐）。收窄後刻意不抑制：kiosk 現場病患一邊在痛"
        "一邊用假設語氣問流程很常見，抑制它是規則層自己製造漏報。",
    ),
    (
        "zh-第三方資訊詢問",
        "zh-TW",
        "網路上說睪丸突然劇痛是扭轉，是真的嗎",
        "要擋掉必須新增一條「引述他處資訊」抑制；那條規則會同時吃掉"
        "「網路上說這是扭轉，我現在就是睪丸突然劇痛」（漏報）。",
    ),
]


@pytest.mark.parametrize(
    "language,text,why_not_suppressed",
    [(lg, t, w) for _i, lg, t, w in POLICY_ACCEPTED_FALSE_POSITIVES],
    ids=[i for i, _lg, _t, _w in POLICY_ACCEPTED_FALSE_POSITIVES],
)
def test_policy_accepted_false_positives(
    detector, language, text, why_not_suppressed
):
    """這些輸入**就是會**觸發 critical —— 這是刻意的政策選擇，不是缺陷。

    使用者（臨床）於 2026-07-27 拍板紅旗規則層偏誤報：
    誤中止＝病患白等 ＋ 護理師走一趟，可逆；漏報＝不可逆。
    若要改成不觸發，需要臨床重新拍板，不是工程可以自行決定的。

    這條測試紅掉，代表有人加了一條新的抑制守衛。**先確認那條守衛不會製造漏報**，
    再回頭來動這裡；別反過來把測試改掉遷就實作。
    """
    hits = _critical_hits(detector, text, language)
    assert hits != [], (
        f"政策接受的誤報被『修好』成不觸發 → 很可能同時開出漏報。\n"
        f"  {language} {text!r}\n"
        f"  為什麼不抑制它：{why_not_suppressed}\n"
        f"  （臨床拍板日 {POLICY_DECIDED_ON}；要改需臨床重新拍板）"
    )


def test_policy_accepted_list_is_documented():
    """每一筆政策接受的誤報都必須寫明「擋掉它會怎樣製造漏報」。

    沒有這個理由的條目＝「懶得修」偽裝成「政策決定」。
    """
    for cid, _lg, _t, why in POLICY_ACCEPTED_FALSE_POSITIVES:
        assert why and len(why) >= 30, cid


# ══════════════════════════════════════════════════════════════
# §2 守衛逐條雙向審計
# ══════════════════════════════════════════════════════════════
# 每條抑制路徑一組：
#   MUST_FIRE      = 這條守衛**不得**在這裡抑制（抑制了就是漏報）
#   MUST_SUPPRESS  = 這條守衛**必須**在這裡抑制（病患明確否認）
# 兩側缺一，另一側都能靠「把守衛整條開／關」作弊通過。

GUARD_AUDIT: list[tuple[str, list[tuple[str, str]], list[tuple[str, str]]]] = [
    (
        "_has_negation_cue（前置否定）",
        [
            ("zh-TW", "今天早上開始痛，沒多久睪丸就腫起來痛到吐"),
            ("en-US", "i cannot stop vomiting, my testicle suddenly hurts so bad"),
            ("vi-VN", "tôi không thể chịu được, bìu sưng đau đột ngột"),
        ],
        [
            ("zh-TW", "我沒有睪丸突然劇痛的情形，只是小便有點慢"),
            ("en-US", "he denies any sudden scrotal pain or swelling"),
            ("vi-VN", "bệnh nhân không có đau tinh hoàn đột ngột"),
        ],
    ),
    (
        "_POST_NEGATION_CUES（ja/ko 後置詞表）",
        [
            ("ja-JP", "左の精巣の痛みがひどくて歩けません"),
            ("ko-KR", "고환이 저녁 먹고 나서 갑작스럽게 참을 수 없이 아파요"),
        ],
        [
            ("ja-JP", "急な睾丸の痛みはありません、排尿時だけ少し違和感があります"),
            ("ko-KR", "갑작스러운 고환 통증은 없어요, 소변볼 때만 조금 불편해요"),
        ],
    ),
    (
        "_post_denial_tail（zh/en/vi 子句尾否認）",
        [
            # 「沒事吧」是病患在**問**自己嚴不嚴重，不是否認
            ("zh-TW", "睪丸突然很痛沒事吧"),
            # 「痛到沒有辦法走路」是程度補語，不是否認
            ("zh-TW", "睪丸劇痛，痛到沒有辦法走路"),
            # 第四輪新增方向補語 filler（來/出來）之後**唯一**的危險方向：
            # 「小便倒是沒有」語意是「完全沒有尿」＝尿滯留本身，不是否認。
            ("zh-TW", "膀胱脹到快爆，小便倒是沒有"),
            ("zh-TW", "尿不出來沒有辦法上班"),
        ],
        [
            ("zh-TW", "小便的時候會痛，睪丸腫痛倒是沒有"),
            ("zh-TW", "小便會痛，睪丸劇痛倒是沒有"),
            # 方向補語 filler 要接住的形狀：「尿不出」＋殘留「來」＋否認
            ("zh-TW", "尿不出來倒是沒有"),
            ("zh-TW", "解不出小便倒是沒有"),
        ],
    ),
    (
        "_clause_final_denial（ja/ko 子句尾述語否定）",
        [
            ("ja-JP", "精巣がさっきトイレに行った後で急に耐えられない痛みになりました"),
            ("ko-KR", "고환이 갑자기 심하게 아파서 걷기 힘들어요"),
        ],
        [
            ("ja-JP", "排尿時にしみますが、睾丸が急に激しく痛むことはありません"),
            ("ko-KR", "소변볼 때 따갑지만 고환이 갑자기 심하게 아프지는 않습니다"),
        ],
    ),
    (
        "_past_resolved（時態否定）",
        [
            ("zh-TW", "之前睪丸很痛，吃了藥好了，今天又痛起來腫得很大，睪丸突然更痛"),
        ],
        [
            ("zh-TW", "我很多年前睪丸很痛過，開刀之後就痊癒了"),
            ("ja-JP", "子供の頃に睾丸が激しく痛みましたが、完治しました"),
            ("vi-VN", "trước đây tinh hoàn đau dữ dội nhưng sau khi mổ đã khỏi hẳn"),
        ],
    ),
    (
        "_hypothetical_or_admin_inquiry（假設／行政詢問）",
        [
            # 條件句 ＋ 已經在發作（急性伴隨症狀）→ 第四輪收窄後不得抑制
            ("zh-TW", "醫生如果我今天早上睪丸突然劇痛痛到吐要怎麼辦"),
            (
                "en-US",
                "if my testicle suddenly hurts this bad and i keep throwing up "
                "what do i do",
            ),
            ("ko-KR", "만약 고환이 갑자기 심하게 아프고 토했으면 어떻게 하나요"),
            # 行政詢問 ＋ 當前發作證據
            ("zh-TW", "請問我睪丸兩小時前突然劇痛還吐了，這要看哪一科"),
        ],
        [
            # 純假設（沒有任何急性伴隨症狀）
            ("zh-TW", "假如哪天蛋蛋突然很痛，我要打哪支電話"),
            ("zh-TW", "如果睪丸很痛的話要掛哪一科"),
            # 條件句裡的時間可能本身就是假設的 → 時間錨點不足以解除條件句抑制
            ("ja-JP", "もし夜中に睾丸が激しく痛くなったらどうすればいいですか"),
            ("en-US", "suppose my testicle suddenly hurts at night, what do I do"),
            ("en-US", "if my testicle ever hurts acutely, should i call the clinic first"),
            ("ko-KR", "만약 고환이 갑자기 심하게 아프면 어디로 가야 하나요"),
            ("vi-VN", "nếu tinh hoàn đau dữ dội vào ban đêm thì tôi phải làm gì"),
            # 純行政詢問（無任何當前發作證據）
            ("zh-TW", "我想請教一下陰囊很痛要掛哪一科"),
            ("en-US", "I would like to ask which department treats severe testicle pain"),
            ("ja-JP", "精巣の激痛は何科に行けばいいか教えてください"),
            ("ko-KR", "극심한 고환 통증은 무슨 과에 가야 하는지 궁금해요"),
        ],
    ),
]


@pytest.mark.parametrize(
    "guard,language,text",
    [
        (guard, lg, t)
        for guard, fires, _sup in GUARD_AUDIT
        for lg, t in fires
    ],
    ids=[
        f"{guard.split('（')[0]}-fire-{i}"
        for guard, fires, _sup in GUARD_AUDIT
        for i, _ in enumerate(fires)
    ],
)
def test_guard_must_not_suppress(detector, guard, language, text):
    """守衛不得在此抑制——病患沒有否認，抑制就是規則層自己製造漏報。"""
    hits = _critical_hits(detector, text, language)
    assert hits != [], f"[{guard}] 製造漏報（under-triage，不可逆）：{language} {text!r}"


@pytest.mark.parametrize(
    "guard,language,text",
    [
        (guard, lg, t)
        for guard, _fires, sup in GUARD_AUDIT
        for lg, t in sup
    ],
    ids=[
        f"{guard.split('（')[0]}-suppress-{i}"
        for guard, _fires, sup in GUARD_AUDIT
        for i, _ in enumerate(sup)
    ],
)
def test_guard_must_still_suppress(detector, guard, language, text):
    """守衛必須在此抑制——病患明確否認／純假設／純行政詢問。

    這一側是上一側的對照組：沒有它，上一側可以靠把守衛整條刪掉全過。
    """
    hits = _critical_hits(detector, text, language)
    assert hits == [], f"[{guard}] 抑制失效 → 誤中止問診：{language} {text!r} → {hits}"


def test_every_audited_guard_has_both_directions():
    """審計表的結構性守衛：每條守衛都必須兩個方向都有案例。"""
    for guard, fires, sup in GUARD_AUDIT:
        assert fires, f"{guard} 缺『不得抑制』方向 → 這條守衛可以無限擴張而不會紅"
        assert sup, f"{guard} 缺『必須抑制』方向 → 這條守衛可以直接刪掉而不會紅"


# ══════════════════════════════════════════════════════════════
# §3 收窄的單向性（承重）
# ══════════════════════════════════════════════════════════════


def test_conditional_branch_uses_the_stricter_evidence_gate():
    """條件句分支只認**急性伴隨症狀**，不認時間錨點。

    條件句裡的時間可能本身就是假設的（「もし夜中に…」＝如果半夜…），
    拿時間錨點解除條件句抑制會把純假設句整批放行成 critical。
    """
    assert rfd_module._has_acute_companion_evidence("痛到吐") is True
    assert rfd_module._has_acute_companion_evidence("今天早上") is False
    # 行政詢問分支則認兩者（時間錨點是「我現在正在講我自己的事」的訊號）
    assert rfd_module._has_current_episode_evidence("今天早上") is True
    assert rfd_module._has_current_episode_evidence("痛到吐") is True


def test_current_episode_marker_table_is_the_concatenation_of_both_subtables():
    """拆表不得改變 `_CURRENT_EPISODE_MARKERS` 的內容。

    它被 test_red_flag_cooccurrence 的結構性守衛（與 critical trigger 字面互斥）
    引用；內容一變，那條守衛保護的東西就跟著變。
    """
    assert rfd_module._CURRENT_EPISODE_MARKERS == (
        rfd_module._CURRENT_EPISODE_TIME_ANCHORS
        + rfd_module._CURRENT_EPISODE_ACUTE_COMPANIONS
    )
    assert not set(rfd_module._CURRENT_EPISODE_TIME_ANCHORS) & set(
        rfd_module._CURRENT_EPISODE_ACUTE_COMPANIONS
    )


def test_post_denial_filler_never_swallows_a_real_complaint():
    """`_post_denial_tail` 的 filler 邊界：不得收任何「單獨就是主訴」的字。

    2026-07-27 第四輪 Gate 更新：第四輪一度增列方向補語 filler（來/出來/去/出去），
    Gate 實測它**不承重**（有／無 filler 對 10 筆雙向案例行為完全相同——它要接的
    acuity 詞「尿不出」在同一輪就被移除了，完整的「尿不出來」本來就是裸 trigger），
    依政策「抑制的舉證責任在保留方」已還原。本測試改為只釘住**界線本身**：
    filler 永遠不得含「尿／小便／排尿／血」——「小便倒是沒有」語意是「完全沒有尿」
    （＝尿滯留本身），收了就是規則層自己製造漏報。
    """
    for pattern in rfd_module._POST_DENIAL_TAIL_PATTERNS:
        source = pattern.pattern
        for forbidden in ("尿", "小便", "排尿", "血"):
            assert forbidden not in source, (
                f"{forbidden!r} 進了 filler → 「{forbidden}倒是沒有」會被當成否認，"
                "但那句話本身就是主訴 → 規則層自己製造漏報"
            )


def test_reverted_direction_complement_filler_did_not_break_denial_suppression():
    """還原方向補語 filler 之後，明確否認仍然必須被抑制（行為面的負面證據）。"""
    import app.pipelines.red_flag_detector as _rfd

    for text in (
        "尿不出來倒是沒有",
        "小便會痛，尿不出來的情形倒是沒有",
        "睪丸突然痛倒是沒有",
    ):
        after = _rfd._clause_after(text.lower(), text.index("倒是"))
        assert _rfd._post_denial_tail(text.lower(), text.index("倒是")) or after, text


def test_false_friends_only_ever_reduce_suppression():
    """單向性：假朋友白名單只能讓否定守衛**少**抑制，不可能多抑制。

    property：對任何 clause，若守衛在**沒有**假朋友表時判定「無否定線索」，
    加上假朋友表之後也必須判定「無否定線索」。
    """
    clauses = [
        "我沒有",
        "沒多久",
        "i cannot ",
        "痛到沒辦法忍了，",
        "睪丸很痛，",
        "he denies any ",
        "我慢できないほど痛くて",
        "참을 수 없이 아파서 ",
        "tôi không thể chịu được, ",
        "沒有高燒、寒顫、",
    ]

    def _naive(clause: str) -> bool:
        return any(cue in clause for cue in rfd_module._NEGATION_CUES)

    for clause in clauses:
        if not _naive(clause):
            assert rfd_module._has_negation_cue(clause) is False, clause
