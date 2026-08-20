"""D-8：`next_focus_guard.is_dont_know` 的雙向語料（MUST_FIRE / MUST_NOT_FIRE）。

## 缺口

`is_dont_know` 原本只做裸子字串比對，**只有 MUST_FIRE 方向**被測到。於是
「我不確定，大概三天前吧」「不知道要打幾分，大概七分」這種**先保留、後給值**的
有效回答會整句被判成拒答，本層對它啟動全套拒答處理：

- `effective_next_focus` 把 pending 指導換成推進指令；
- `build_dont_know_ban` 把該欄的**所有換句話句式**在本輪列為硬性禁令。

結果是病患明明給了值，AI 卻連一次澄清（「所以是三天前開始的嗎」）都不能問。
只往單一方向加斷言 ＝ 在替下一次擺盪鋪路（見 skill「測試設計」第 1 點）。

## 窄化法與 #22 舉證

窄化＝「標記詞 + 同句出現具體**數值 + 單位**」才視為有效回答。這裡的「漏報」是
**該判拒答卻沒判到** → don't-know ban 不啟動 → 可能換句話重問（就是 e2e
`a2_no_duration_reask_after_dontknow` 那個回歸）。舉證：

- 疑問數詞（幾／多少／how many／how long／どのくらい／얼마나／bao lâu）**不在**數詞
  集合裡，且比對前先被挖掉，所以「不知道幾天」「don't know how many days」仍判拒答
  ——那是最常見的拒答句型，也是最容易被寫壞的一條，本檔逐語言釘住。
- 沒有量詞的裸數字不算（「不知道，一開始就這樣」的「一」後面是「開」不是量詞）。
- 量詞白名單只收時間／次數／程度分數——那正是 `FIELD_PATTERNS` 涵蓋的
  onset / duration / severity 三欄會拿到的值型別。

## 措辭

刻意不抄 `dontknow_zh` persona 的台詞（「我真的不知道，不記得了。」／
「不記得了，我真的不知道。」）——e2e 全綠只證明「那兩句會命中」，不證明
「這個臨床情境會命中」。除了保留 persona 兩句當回歸釘子外，其餘全是別的措辭。
"""

from __future__ import annotations

import pytest

from app.pipelines.next_focus_guard import (
    build_dont_know_ban,
    declined_fields_from_history,
    has_concrete_value,
    is_dont_know,
)

# ── MUST_FIRE：真的是拒答 ────────────────────────────────
MUST_FIRE = [
    # zh-TW
    pytest.param("我真的不知道，不記得了。", id="zh-persona-regression"),
    pytest.param("這個我沒印象耶", id="zh-no-impression"),
    pytest.param("說不上來，反正就是這樣", id="zh-cannot-say"),
    pytest.param("不知道幾天了，沒在算", id="zh-question-quantifier-days"),
    pytest.param("不曉得要打幾分", id="zh-question-quantifier-score"),
    pytest.param("不記得多久了", id="zh-question-quantifier-duration"),
    pytest.param("不知道，一開始就這樣了", id="zh-bare-numeral-no-unit"),
    pytest.param("不清楚，沒特別注意過", id="zh-not-noticed"),
    # en-US
    pytest.param("I honestly have no idea", id="en-no-idea"),
    pytest.param("I don't know how many days it's been", id="en-how-many-days"),
    pytest.param("Not sure, I can't recall", id="en-cannot-recall"),
    pytest.param("I don't remember, sorry", id="en-dont-remember"),
    # ja-JP
    pytest.param("はっきりしませんね", id="ja-unclear"),
    pytest.param("どのくらい続いているか分からないです", id="ja-how-long"),
    pytest.param("覚えていないです", id="ja-dont-remember"),
    # ko-KR
    pytest.param("잘 모르겠어요", id="ko-dont-know"),
    pytest.param("며칠인지 모르겠어요", id="ko-how-many-days"),
    pytest.param("기억이 안 나요", id="ko-no-memory"),
    # vi-VN
    pytest.param("Tôi không nhớ rõ", id="vi-dont-remember"),
    pytest.param("Không biết bao lâu rồi", id="vi-how-long"),
    pytest.param("Không chắc lắm", id="vi-not-sure"),
]

# ── MUST_NOT_FIRE：帶保留但**仍給出具體值**的有效回答 ───────
MUST_NOT_FIRE = [
    # zh-TW
    pytest.param("我不確定，大概三天前吧", id="zh-hedged-three-days"),
    pytest.param("不太確定，可能兩個星期了", id="zh-hedged-two-weeks"),
    pytest.param("不知道要打幾分，大概七分吧", id="zh-hedged-score-seven"),
    pytest.param("記不太清楚，大約半年了", id="zh-hedged-half-year"),
    pytest.param("不確定耶，一天大概 5 次", id="zh-hedged-five-times"),
    # en-US
    pytest.param("Not sure, maybe 3 days ago", id="en-hedged-3-days"),
    pytest.param(
        "I don't remember exactly, about three weeks", id="en-hedged-three-weeks"
    ),
    pytest.param("No idea really, roughly 6 months", id="en-hedged-6-months"),
    # ja-JP
    pytest.param("はっきりしませんが、3日前くらいです", id="ja-hedged-3-days"),
    pytest.param("よく分からないけど、2週間くらい", id="ja-hedged-2-weeks"),
    # ko-KR
    pytest.param("잘 모르겠는데 3일 전쯤이요", id="ko-hedged-3-days"),
    pytest.param("확실하진 않지만 2개월 정도요", id="ko-hedged-2-months"),
    # vi-VN
    pytest.param("Không rõ lắm, khoảng 3 ngày trước", id="vi-hedged-3-days"),
    pytest.param("Tôi không nhớ chính xác, chừng 2 tuần", id="vi-hedged-2-weeks"),
]


@pytest.mark.parametrize("text", MUST_FIRE)
def test_must_fire_is_dont_know(text: str) -> None:
    assert is_dont_know(text) is True, (
        f"「{text}」是拒答卻沒判到 → don't-know ban 不啟動 → AI 可能換句話重問"
    )


@pytest.mark.parametrize("text", MUST_NOT_FIRE)
def test_must_not_fire_is_dont_know(text: str) -> None:
    assert is_dont_know(text) is False, (
        f"「{text}」帶保留但給了具體值，不得判成拒答 → 否則該欄整輪禁問、"
        "AI 連一次澄清都不能做"
    )


# ── has_concrete_value 的邊界（窄化法本身） ────────────────
@pytest.mark.parametrize(
    "text",
    ["三天前", "2 weeks", "3日前", "5 lần một ngày", "7 분", "半年"],
)
def test_has_concrete_value_true(text: str) -> None:
    assert has_concrete_value(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "幾天",
        "多少分",
        "how many days",
        "how long",
        "どのくらい",
        "며칠",
        "bao lâu",
        "一開始就這樣",
        "",
    ],
)
def test_has_concrete_value_false(text: str) -> None:
    assert has_concrete_value(text) is False


# ── 後果面：拒答處理有沒有被誤啟動 ─────────────────────────
def _history(ai_question: str, patient_answer: str) -> list[dict]:
    return [
        {"role": "assistant", "content": ai_question},
        {"role": "patient", "content": patient_answer},
    ]


def test_hedged_answer_does_not_trigger_declined_field() -> None:
    """病患答「不確定，大概三天前」→ 不得把 onset/duration 標成剛被拒答。"""
    history = _history("這個情況大概持續多久了呢？", "我不確定，大概三天前吧")
    assert declined_fields_from_history(history) == set()


def test_genuine_refusal_still_triggers_declined_field() -> None:
    """反方向：真的拒答仍必須標記，否則 D-8 的窄化就變成漏報。"""
    history = _history("這個情況大概持續多久了呢？", "不知道幾天，我沒在算")
    assert "duration" in declined_fields_from_history(history)


def test_hedged_answer_produces_no_turn_ban() -> None:
    """沒有 declined 欄位 → 本輪不注入「禁止再問」三明治。"""
    history = _history("是什麼時候開始的？", "不太確定，可能兩個星期了")
    assert build_dont_know_ban(declined_fields_from_history(history), "zh-TW") == ""
