"""next_focus 換句話重問自檢（app/pipelines/next_focus_guard.py）雙向對稱測試。

## 這組測試在守什麼

真 OpenAI e2e `dontknow_zh`（2026-08-17）：病患對 Duration 答「我真的不知道」後，
Supervisor 的 `missing_hpi` 正確剔除了 `duration`，但同一份輸出的 `next_focus`
文字仍是 Duration 的換句話重問，對話 LLM 逐字照抄 → `a2_no_duration_reask_after_dontknow`
FAIL。修法有兩層：supervisor prompt 的一致性規則 + 本模組的輸出自檢。

## 測試設計（依 voice-pipeline-invariants「改偵測邏輯時的測試設計」四點）

1. **雙向對稱**：`MUST_REPLACE`（已覆蓋欄位的換句話重問必須被攔下，duration 至少
   4 種不同措辭）與 `MUST_KEEP`（合法提問不得被誤殺，含 frequency / timing /
   加重因子 / §3b 風險因子 / 單邊句式）同時存在，且同一批 duration 措辭在
   「duration 仍缺失」時必須**全部放行**（`test_same_wording_passes_when_field_still_missing`）
   ——這是對稱性最硬的一條：同一句話的判定只能由 missing_hpi 決定。
2. **措辭不抄 e2e persona／逐字稿**：實測違規句是
   「請問您的頻尿是一直都有，還是間歇出現？」；本檔所有語料都改寫過（整天／斷斷續續、
   從頭到尾／時有時無、持續性／間歇性…），避免驗收套件只證明「那一句會被抓到」。
3. **oracle 不是實作自己**：期望值是逐句人工標註的常數表，不呼叫
   `match_focus_fields` 反推，也不從 `FIELD_PATTERNS` 生成。
4. **注入式回歸**：拿掉 prompt 規則或 sanitize 呼叫時，本檔會紅
   （`test_supervisor_applies_guard_to_stored_guidance` /
   `test_supervisor_prompt_requires_next_focus_missing_hpi_consistency`）。
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.pipelines.next_focus_guard import (
    evaluate_next_focus,
    sanitize_guidance,
)
from app.pipelines.supervisor import SUPERVISOR_SYSTEM_PROMPT, SupervisorEngine

# HPI 十欄裡與本案無關、可用來當「仍缺失」背景的欄位
_OTHER_MISSING = ["characteristics", "aggravating_factors", "associated_symptoms"]


# ── MUST_REPLACE：已覆蓋（已答或已拒答）欄位的換句話重問 ────────────────────
# (next_focus, missing_hpi, 應被判為重問的欄位)
MUST_REPLACE: list[tuple[str, list[str], str]] = [
    # duration 已從 missing_hpi 移除後的四種不同措辭（都不是 e2e 逐字稿原句）
    (
        "請詢問病患排尿不適是整天都在，還是斷斷續續才出現",
        _OTHER_MISSING,
        "duration",
    ),
    (
        "請確認病患的症狀屬於持續性還是間歇性",
        _OTHER_MISSING,
        "duration",
    ),
    (
        "請詢問病患這個狀況大概多久了",
        _OTHER_MISSING,
        "duration",
    ),
    (
        "請詢問病患症狀是從頭到尾都在，或是時有時無",
        _OTHER_MISSING,
        "duration",
    ),
    # 非中文場次（next_focus 隨場次語言輸出，守衛不能只在中文有效）
    (
        "Ask the patient whether the discomfort is constant or comes and goes.",
        _OTHER_MISSING,
        "duration",
    ),
    (
        "症状はずっと続いているのか、それとも時々出るだけなのかを確認してください。",
        _OTHER_MISSING,
        "duration",
    ),
    # onset 已覆蓋後的換句話（prompt 明文列舉的第二種形式）
    (
        "請詢問病患症狀是突然發生的，還是慢慢變明顯的",
        _OTHER_MISSING,
        "onset",
    ),
    # severity 已覆蓋後的換句話（第三種形式）
    (
        "請詢問病患目前的不適大概幾分",
        _OTHER_MISSING,
        "severity",
    ),
    (
        "請詢問病患這個疼痛有多嚴重",
        _OTHER_MISSING,
        "severity",
    ),
    # missing_hpi 全空（十欄皆已覆蓋）時仍指向某一欄 → 一樣是重問
    (
        "請確認病患症狀是一直都在還是偶爾出現",
        [],
        "duration",
    ),
    # 一句帶到兩欄、兩欄都已覆蓋 → 沒有合法解釋，仍要攔
    (
        "請詢問病患這波不適大概多久了，以及最嚴重時有多痛",
        ["timing"],
        "duration",
    ),
]

# ── MUST_KEEP：合法提問，不得被誤殺 ──────────────────────────────────────
# (next_focus, missing_hpi, 為什麼合法)
MUST_KEEP: list[tuple[str, list[str], str]] = [
    # 相鄰欄位：拒答 duration 後改問 timing / characteristics 是**正確行為**
    (
        "請詢問病患夜間睡覺時是否需要起來排尿",
        ["timing", "severity"],
        "timing 仍缺失，這是拒答 duration 後該問的下一欄",
    ),
    (
        "請詢問病患排尿時是灼熱刺痛還是下腹脹痛",
        ["characteristics"],
        "characteristics 仍缺失，性質提問與 duration 無關",
    ),
    # 排尿頻率提問：frequency 不在 HPI 十欄，永遠不可能「已覆蓋」→ 開火即誤殺
    (
        "請詢問病患白天大約排尿幾次、夜間又起來幾次",
        _OTHER_MISSING,
        "頻率提問，frequency 不屬 HPI 十欄",
    ),
    (
        "請詢問病患一天要跑幾次廁所，是不是一直都想上、還是間歇才有",
        _OTHER_MISSING,
        "頻率提問即使帶到「一直／間歇」字眼也不得誤殺",
    ),
    (
        "Ask the patient how often they need to urinate during the day.",
        _OTHER_MISSING,
        "英文頻率提問",
    ),
    # 單邊句式：加重／緩解因子的合法提問常單獨用到二選一句式的一端
    (
        "請詢問病患是否某些時候症狀會特別明顯",
        _OTHER_MISSING,
        "只有「某些時候」單邊，屬加重因子提問",
    ),
    (
        "請詢問病患久坐或喝咖啡之後症狀是否會加重",
        _OTHER_MISSING,
        "加重因子提問，未命中任何欄位形式",
    ),
    (
        "請詢問病患排尿後殘尿感是否會持續一段時間",
        _OTHER_MISSING,
        "只有「持續」單邊，屬緩解因子/伴隨症狀提問",
    ),
    # §3b 風險因子與次要補問：優先序高於本層，帶到欄位字面詞也不得被擋
    (
        "請詢問病患抽菸多久了",
        _OTHER_MISSING,
        "吸菸史屬 §3b 風險因子，不是本次症狀的 Duration",
    ),
    (
        "請詢問病患是否有在服用抗凝血或抗血小板藥物",
        _OTHER_MISSING,
        "用藥風險因子提問",
    ),
    (
        "請詢問病患家族中是否有人罹患泌尿道癌症",
        _OTHER_MISSING,
        "家族史提問",
    ),
    # 該欄仍缺失 → 第一次問（含二選一句式）完全合法
    (
        "請詢問病患症狀是持續性還是間歇性",
        ["duration", "severity"],
        "duration 仍缺失，first-ask 不是重問",
    ),
    (
        "請詢問病患不適程度大概幾分",
        ["severity"],
        "severity 仍缺失",
    ),
    # 一句同時帶到兩欄、其中一欄仍缺失 → 有合法解釋（在問仍缺失的那欄），放行。
    # 本層不負責「一次只問一個問題」，那條由 SINGLE_QUESTION_RULE 管。
    (
        "請詢問病患這波不適大概多久了，以及最嚴重時有多痛",
        ["severity", "timing"],
        "同時命中 duration（已覆蓋）與 severity（仍缺失）→ 仍缺失欄位優先，放行",
    ),
    # 收尾指令
    (
        "請做一次簡短確認後收尾",
        [],
        "收尾指令未指向任何欄位",
    ),
]


@pytest.mark.parametrize("next_focus, missing, field", MUST_REPLACE)
def test_must_replace_reask_of_covered_field(next_focus, missing, field):
    """已從 missing_hpi 移除的欄位，任何換句話形式都必須被判為重問。"""
    verdict = evaluate_next_focus(next_focus, missing)
    assert field in verdict.reask_fields, (
        f"漏抓換句話重問（{field}）：{next_focus!r} / missing={missing}"
    )


@pytest.mark.parametrize("next_focus, missing, why", MUST_KEEP)
def test_must_keep_legitimate_focus(next_focus, missing, why):
    """合法提問不得被誤殺（相鄰欄位、頻率、加重因子、§3b 風險因子、單邊句式）。"""
    verdict = evaluate_next_focus(next_focus, missing)
    assert verdict.reask_fields == (), (
        f"誤殺合法提問（{why}）：{next_focus!r} / missing={missing} "
        f"→ 判成重問 {verdict.reask_fields}"
    )


@pytest.mark.parametrize("next_focus, missing, field", MUST_REPLACE)
def test_same_wording_passes_when_field_still_missing(next_focus, missing, field):
    """對稱性硬條件：同一句措辭，在該欄仍缺失時必須放行。

    判定只能由 missing_hpi 決定；若某句無論如何都被擋，代表守衛退化成關鍵字黑名單
    ——那會在下一輪變成「first-ask 也問不出來」的漏問缺陷。
    """
    verdict = evaluate_next_focus(next_focus, [field, *missing])
    assert verdict.reask_fields == (), (
        f"{field} 仍缺失時 first-ask 被誤擋：{next_focus!r}"
    )


def test_missing_hpi_not_a_list_fails_open():
    """missing_hpi 缺失／型別壞掉時無從判斷一致性 → 一律放行，不動 next_focus。"""
    for bad in (None, "duration", 3, {"duration": True}):
        assert evaluate_next_focus("請詢問症狀是持續性還是間歇性", bad).reask_fields == ()


def test_sanitize_replaces_with_still_missing_fields():
    """命中時換成指向仍缺失欄位的推進指令，且不得清空 next_focus（那是 R19 的坑）。"""
    guidance = {
        "next_focus": "請確認病患的症狀屬於持續性還是間歇性",
        "missing_hpi": ["timing", "severity"],
        "hpi_completion_percentage": 60,
    }
    out = sanitize_guidance(guidance, "zh-TW")
    assert out["next_focus"] != guidance["next_focus"]
    assert out["next_focus"].strip()
    assert "Timing" in out["next_focus"] and "Severity" in out["next_focus"]
    assert out["next_focus_guard"]["reask_fields"] == ["duration"]
    assert out["next_focus_guard"]["original_next_focus"] == guidance["next_focus"]


def test_sanitize_preserves_third_state_fields():
    """「不知道是第三態」：守衛只改文字，不得改 missing_hpi / 完整度。"""
    guidance = {
        "next_focus": "請詢問病患這個狀況大概多久了",
        "missing_hpi": ["severity"],
        "hpi_completion_percentage": 85,
    }
    out = sanitize_guidance(guidance, "zh-TW")
    assert out["missing_hpi"] == ["severity"]
    assert out["hpi_completion_percentage"] == 85
    # 原 dict 不得被就地改動
    assert guidance["next_focus"] == "請詢問病患這個狀況大概多久了"


def test_sanitize_wrap_up_when_nothing_missing():
    """十欄皆覆蓋時，替代指令改為「簡短確認後收尾」而不是再指向某一欄。"""
    out = sanitize_guidance(
        {
            "next_focus": "請確認病患症狀是一直都在還是偶爾出現",
            "missing_hpi": [],
            "hpi_completion_percentage": 90,
        },
        "zh-TW",
    )
    assert "收尾" in out["next_focus"]


def test_sanitize_localizes_replacement():
    """替代指令走 i18n：英文場次不得拿到中文 next_focus（會污染對話 LLM 輸出語言）。"""
    out = sanitize_guidance(
        {
            "next_focus": "Ask whether the symptom is constant or comes and goes.",
            "missing_hpi": ["timing"],
            "hpi_completion_percentage": 60,
        },
        "en-US",
    )
    assert out["next_focus"].isascii()
    assert "Timing" in out["next_focus"]


def test_sanitize_noop_keeps_object_untouched():
    """未命中時原封不動回傳（不得加 next_focus_guard 噪音）。"""
    guidance = {
        "next_focus": "請詢問病患夜間是否需要起來排尿",
        "missing_hpi": ["timing"],
        "hpi_completion_percentage": 60,
    }
    out = sanitize_guidance(guidance, "zh-TW")
    assert out is guidance
    assert "next_focus_guard" not in out


# ── 消費端：一輪延遲的 guidance 撞上「不知道」 ────────────────────────────
#
# 第二輪 e2e 實證：Supervisor 產出的 next_focus 已乾淨，但對話端這一輪讀到的是
# **上一輪**算的 guidance，正好指向病患剛剛拒答的那一欄 → LLM 換句話問出來。
# 這組測試同樣雙向：拒答欄位的過期指導必須被換掉；指向別欄的指導不得被動到。


def _history(ai_question: str, patient_reply: str) -> list[dict]:
    return [
        {"role": "assistant", "content": "您好，請問您的頻尿是什麼時候開始的？"},
        {"role": "patient", "content": "大概上個月吧。"},
        {"role": "assistant", "content": ai_question},
        {"role": "patient", "content": patient_reply},
    ]


# 拒答措辭刻意不抄 persona 台詞（persona 講的是「我真的不知道，不記得了。」）
DONT_KNOW_REPLIES = [
    "這個我沒特別注意，說不上來。",
    "抱歉，我不曉得。",
    "I'm not sure, I can't recall.",
    "はっきり覚えてないです。",
    "잘 모르겠어요.",
    "Tôi không nhớ rõ.",
]


@pytest.mark.parametrize("reply", DONT_KNOW_REPLIES)
def test_stale_guidance_pointing_at_just_declined_field_is_replaced(reply):
    """病患剛對「持續多久」說不知道 → pending 的 duration 指導必須換掉。"""
    history = _history("這個頻尿大概持續多久了呢？", reply)
    guidance = {
        "next_focus": "請問這個頻尿大概持續多久了？",
        "missing_hpi": ["duration", "characteristics", "timing"],
        "hpi_completion_percentage": 25,
    }
    from app.pipelines.next_focus_guard import effective_next_focus

    out = effective_next_focus(history, guidance, "zh-TW")
    assert "多久" not in out, f"過期的 duration 指導仍被注入：{out!r}"
    assert out.strip(), "不得清空（那會退化成 R19 的無指導自由發揮）"
    # 替代指令不得再把剛拒答的欄位列進去
    assert "Duration" not in out
    assert "Characteristics" in out or "Timing" in out


def test_guidance_pointing_at_other_field_is_untouched_after_dontknow():
    """拒答 duration 後，指向 timing 的指導是**正確行為**，不得被攔。"""
    from app.pipelines.next_focus_guard import effective_next_focus

    history = _history("這個頻尿大概持續多久了呢？", "我真的沒印象。")
    guidance = {
        "next_focus": "這個頻尿在晚上會特別明顯嗎？",
        "missing_hpi": ["timing", "severity"],
        "hpi_completion_percentage": 40,
    }
    assert (
        effective_next_focus(history, guidance, "zh-TW")
        == "這個頻尿在晚上會特別明顯嗎？"
    )


def test_guidance_untouched_when_patient_actually_answered():
    """病患正常作答時，本層完全不介入（即使指導與上一題同欄）。"""
    from app.pipelines.next_focus_guard import effective_next_focus

    history = _history("這個頻尿大概持續多久了呢？", "大概持續三個月了。")
    guidance = {
        "next_focus": "請問這個頻尿大概持續多久了？",
        "missing_hpi": ["duration", "timing"],
        "hpi_completion_percentage": 25,
    }
    assert (
        effective_next_focus(history, guidance, "zh-TW")
        == "請問這個頻尿大概持續多久了？"
    )


def test_guidance_untouched_when_declined_field_unknown():
    """拒答的是對應不到 HPI 欄位的問題（例如 Location）→ 不介入，原樣注入。"""
    from app.pipelines.next_focus_guard import effective_next_focus

    history = _history("您主要是哪個部位不舒服呢？", "我不曉得耶。")
    guidance = {
        "next_focus": "請問這個頻尿大概持續多久了？",
        "missing_hpi": ["duration"],
        "hpi_completion_percentage": 20,
    }
    assert (
        effective_next_focus(history, guidance, "zh-TW")
        == "請問這個頻尿大概持續多久了？"
    )


def test_format_messages_injects_replacement_not_stale_focus():
    """端到端（消費端）：system prompt 裡不得出現過期的 duration 指導。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = _history("這個頻尿大概持續多久了呢？", "我沒特別注意，說不上來。")
    messages = engine.format_messages(
        history,
        "SYSTEM",
        {
            "next_focus": "請問這個頻尿大概持續多久了？",
            "missing_hpi": ["duration", "characteristics"],
            "hpi_completion_percentage": 25,
        },
        language="zh-TW",
    )
    system = messages[0]["content"]
    assert "請問這個頻尿大概持續多久了？" not in system
    assert "Characteristics" in system


def test_format_messages_keeps_guidance_for_other_field():
    """對稱：指向別欄的指導必須照常注入（不得因為病患說不知道就整段消失）。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = _history("這個頻尿大概持續多久了呢？", "我沒特別注意，說不上來。")
    messages = engine.format_messages(
        history,
        "SYSTEM",
        {
            "next_focus": "這個頻尿在晚上會特別明顯嗎？",
            "missing_hpi": ["timing"],
            "hpi_completion_percentage": 40,
        },
        language="zh-TW",
    )
    assert "這個頻尿在晚上會特別明顯嗎？" in messages[0]["content"]


# ── 本輪限定的「剛被拒答的面向禁止再問」禁令（三明治注入） ────────────────


def test_dont_know_ban_is_sandwiched_with_field_specific_examples():
    """拒答 Duration 的那一輪：禁令要在最前與最後，且列的是 Duration 的句式。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = _history("這個頻尿大概持續多久了呢？", "我沒特別注意，說不上來。")
    system = engine.format_messages(history, "SYSTEM", None, language="zh-TW")[0][
        "content"
    ]
    assert "一直都有" in system and "間歇" in system, "禁令沒有列出 Duration 的換句話句式"
    assert system.startswith("【本輪硬性禁令"), "禁令沒有放在最前（最高優先）"
    assert system.rstrip().endswith("請直接改問其他尚未釐清的面向。"), (
        "禁令沒有放在最後（最高 recency）"
    )


def test_dont_know_ban_does_not_over_ban_other_fields():
    """誤殺防線：拒答 Onset 那一輪，不得順手把 Duration 的句式也列成禁令。

    列進去會讓 Duration 這一欄再也問不出來（把重問缺陷換成漏問缺陷）。
    """
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = [
        {"role": "assistant", "content": "請問這個症狀是什麼時候開始的？"},
        {"role": "patient", "content": "我不曉得，想不起來。"},
    ]
    system = engine.format_messages(history, "SYSTEM", None, language="zh-TW")[0][
        "content"
    ]
    assert "突然發生" in system, "Onset 的換句話句式應列入禁令"
    assert "持續性還是間歇性" not in system
    assert "一直都有" not in system


def test_no_ban_when_patient_answered():
    """病患正常作答的輪次不得出現禁令（否則等於每輪都在削減可問範圍）。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = _history("這個頻尿大概持續多久了呢？", "大概三個月了。")
    system = engine.format_messages(history, "SYSTEM", None, language="zh-TW")[0][
        "content"
    ]
    assert "本輪硬性禁令" not in system


def test_no_ban_on_wrap_up_turn():
    """收尾輪不加禁令（該輪本來就零發問，多一段指令只會與收尾規則競爭）。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = _history("這個頻尿大概持續多久了呢？", "我沒特別注意，說不上來。")
    system = engine.format_messages(
        history, "SYSTEM", None, language="zh-TW", conclude=True
    )[0]["content"]
    assert "本輪硬性禁令" not in system


def test_dont_know_ban_is_localized():
    """非中文場次的禁令必須是該語言（中文段落會提高中文洩漏到病患回覆的機率）。"""
    from app.pipelines.llm_conversation import LLMConversationEngine

    engine = LLMConversationEngine(Settings())
    history = [
        {"role": "assistant", "content": "How long has this been going on?"},
        {"role": "patient", "content": "I'm not sure, I can't recall."},
    ]
    system = engine.format_messages(history, "SYSTEM", None, language="en-US")[0][
        "content"
    ]
    assert "Hard ban for THIS turn" in system
    assert "constant or does it come and go" in system


# ── 注入式回歸的兩個錨點：prompt 規則 + supervisor 真的有呼叫守衛 ──────────


def test_supervisor_prompt_requires_next_focus_missing_hpi_consistency():
    """第一層（prompt）：next_focus 與 missing_hpi 的一致性規則必須在 prompt 裡。"""
    assert "next_focus 必須與你自己的 missing_hpi 一致" in SUPERVISOR_SYSTEM_PROMPT
    # prompt 必須明文列舉三種換句話形式，否則 LLM 只拿到抽象規則（實測不夠）
    assert "持續性還是間歇性" in SUPERVISOR_SYSTEM_PROMPT
    assert "突然發生還是慢慢變明顯" in SUPERVISOR_SYSTEM_PROMPT
    assert "大概幾分" in SUPERVISOR_SYSTEM_PROMPT


class _ReaskClient:
    """回傳「missing_hpi 正確、next_focus 卻重問 duration」的實測缺陷樣態。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "next_focus": "請確認病患症狀是整天持續，還是斷斷續續出現",
            "missing_hpi": ["characteristics", "severity", "timing"],
            "hpi_completion_percentage": 40,
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(payload, ensure_ascii=False)
                    )
                )
            ]
        )


class _FakeRedis:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def setex(self, key, ttl, value):  # noqa: ANN001
        self.stored[key] = value


def test_supervisor_applies_guard_to_stored_guidance():
    """第二層（代碼）：寫進 Redis 的 guidance 必須已消毒——消費端只讀 Redis。"""
    engine = SupervisorEngine(Settings())
    engine._client = _ReaskClient()  # noqa: SLF001
    redis = _FakeRedis()
    asyncio.run(
        engine.analyze_next_step(
            session_id="guard-test",
            conversation_history=[
                {"role": "assistant", "content": "請問這個頻尿大概持續多久了？"},
                {"role": "patient", "content": "我真的不知道，不記得了。"},
            ],
            chief_complaint="頻尿",
            patient_info={"age": 60, "gender": "male"},
            redis=redis,
            language="zh-TW",
        )
    )
    assert redis.stored, "guidance 未寫入 Redis"
    stored = json.loads(next(iter(redis.stored.values())))
    assert "斷斷續續" not in stored["next_focus"], (
        "重問 duration 的 next_focus 未被攔下就寫進 Redis"
    )
    assert stored["next_focus_guard"]["reask_fields"] == ["duration"]
    # 結構化欄位（第三態語意）必須原樣保留
    assert stored["missing_hpi"] == ["characteristics", "severity", "timing"]
    assert stored["hpi_completion_percentage"] == 40
