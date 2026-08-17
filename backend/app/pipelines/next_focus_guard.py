"""
next_focus 自檢層 — 擋掉「已覆蓋 / 已拒答欄位的換句話重問」

## 這層在修什麼（2026-08-17 真 OpenAI e2e `dontknow_zh` 實證）

病患對 Duration 答「我真的不知道」後，Supervisor 的**結構化欄位處理是正確的**——
`missing_hpi` 已把 `duration` 剔除、`hpi_completion_percentage` 沒被壓低——
但同一份輸出的 `next_focus` **自然語言文字**仍寫成：

    「請問您的頻尿是一直都有，還是間歇出現？」

語意上就是 Duration 的換句話重問（`llm_conversation.py` 的問診準則明文列舉
「已問過 Duration 卻改問『間歇性還是持續性』」為禁止形式），而對話 LLM 幾乎逐字照抄
next_focus → e2e 斷言 `a2_no_duration_reask_after_dontknow` FAIL。

**與 R19 的區別**：R19 是「第 1 輪 guidance 尚不存在、對話 LLM 只能自由發揮」；
本層處理的是「guidance 存在、欄位標籤也正確，但 Supervisor 產生的措辭與自己的
欄位判斷自相矛盾」。

## 判準：用 Supervisor 自己的結構化輸出當權威，不另建 don't-know 偵測器

本模組**刻意不做**「掃逐字稿判斷病患拒答了哪一欄」這種偵測——那需要把 AI 問句分類到
HPI 欄位，誤判就會把「病患其實沒拒答的欄位」永久關掉（漏問）。實測顯示 Supervisor
對「哪些欄位已覆蓋/已拒答」判斷正確（missing_hpi 準確剔除），缺的只是讓**文字**服從
同一個結論。因此判準是**內部一致性**：

    next_focus 若語意上指向 HPI 十欄中的某一欄，該欄必須仍在同一份輸出的
    missing_hpi 裡；否則就是在重問已覆蓋（已回答或已表示不知道）的欄位。

「不知道是第三態」不變式不受影響：拒答欄位仍然只是「從 missing 清單消失」，
本層不改那個語意，只是讓 next_focus 文字跟上。

## fail-open 的四道閘門（為什麼不會誤殺合法的相鄰欄位提問）

1. **仍缺失欄位優先**：只要 next_focus 命中的欄位裡**有任何一欄仍在 missing_hpi**，
   一律放行。合法的相鄰欄位提問（frequency/timing 的問句偶爾會帶到「一直」「間歇」
   這類詞）因此不會被誤殺——那一欄還缺，就有合法解釋。
2. **頻率否決詞**：句中出現「幾次 / 次數 / 多久一次 / how often …」→ 這是排尿頻率
   提問（frequency 根本不在 HPI 十欄，永遠不可能「已覆蓋」），直接放行。
3. **非 HPI 主題否決詞**：抽菸 / 喝酒 / 用藥 / 家族史 / 手術 / 過敏 等 §3b 風險因子與
   次要補問主題。「請問您抽菸多久了？」帶著 Duration 的字面詞，但問的不是本次症狀的
   持續時間——這類一律放行（§3b 必問清單優先序最高，絕不能被本層擋掉）。
4. **證據要夠強**：只認 (a) 明確的欄位提問詞（「持續多久」「多久了」「幾分」）與
   (b) prompt 自己列舉的**二選一句式**（「一直/持續」×「間歇/斷斷續續」、
   「突然」×「漸進」）——單邊命中不算（「有沒有某些時候比較明顯」是加重因子提問）。
   涵蓋欄位刻意只取 onset / duration / severity 三欄：那正是 llm_conversation 問診準則
   明文列舉的三種換句話形式，其餘欄位不進場，把誤殺面積壓到最小。

`missing_hpi` 不是 list（LLM 沒回、型別壞掉）時同樣一律放行——無從判斷內部一致性時
不動作，寧可保留原 next_focus。

## 命中之後

不是刪掉 next_focus（那會退化成 R19 的「無指導、LLM 自由發揮」），而是換成
**指向仍缺失欄位**的中性推進指令（i18n，隨場次語言）；若已無缺失欄位則換成
「做一次簡短確認後收尾」——與 Supervisor prompt 本身的收尾規則一致。
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from app.pipelines.prompts.shared import HPI_FIELD_IDS, HPI_STEPS
from app.utils.i18n_messages import get_message as _i18n_get

logger = logging.getLogger(__name__)


class FieldPattern(NamedTuple):
    """某個 HPI 欄位的「提問形式」比對規則。

    direct  單獨出現即足以判定該欄位的提問詞（「持續多久」「多久了」「幾分」）。
    pair_a  二選一句式的一端（連續/突然）。
    pair_b  二選一句式的另一端（間歇/漸進）。**a 與 b 同句同時出現**才算命中——
            單邊命中在正常問診裡另有合法用途（加重因子、緩解因子）。
    veto    命中即視為「這句不是在問本欄」（frequency 提問對 duration 的否決）。
    """

    direct: tuple[str, ...] = ()
    pair_a: tuple[str, ...] = ()
    pair_b: tuple[str, ...] = ()
    veto: tuple[str, ...] = ()


# 排尿頻率提問的標記。frequency **不是** HPI 十欄之一（十欄見 shared.HPI_STEPS），
# 所以它永遠不會出現在 missing_hpi、也永遠不可能「已覆蓋」——對它開火只會是誤殺。
_FREQUENCY_MARKERS: tuple[str, ...] = (
    "幾次", "次數", "多久一次", "頻率", "頻繁",
    "how often", "times a day", "times per", "how many times",
    "何回", "回数", "頻度",
    "몇 번", "횟수", "얼마나 자주",
    "bao nhiêu lần", "mấy lần", "bao lâu một lần",
)

# 非 HPI 主題（§3b 風險因子 + 次要補問）。這些主題的提問**優先序高於本層**，
# 帶到欄位字面詞（「抽菸多久了」）時一律放行。
_NON_HPI_TOPIC_MARKERS: tuple[str, ...] = (
    "抽菸", "吸菸", "抽煙", "菸酒", "喝酒", "飲酒", "咖啡因", "喝水",
    "藥", "用藥", "服用", "抗凝血", "抗血小板",
    "家族", "遺傳", "手術", "開刀", "過敏", "病史", "慢性病",
    "smok", "alcohol", "drink", "caffeine", "medication", "medicine",
    "anticoagul", "antiplatelet", "family history", "surgery", "allerg",
    "喫煙", "飲酒", "薬", "家族歴", "手術", "アレルギー",
    "흡연", "담배", "음주", "약", "가족력", "수술", "알레르기",
    "hút thuốc", "rượu", "thuốc", "tiền sử gia đình", "phẫu thuật", "dị ứng",
)

# 涵蓋欄位＝llm_conversation 問診準則明文列舉的三種換句話形式對應的欄位。
# 其餘七欄刻意不進場（見模組 docstring 第 4 道閘門）。
FIELD_PATTERNS: dict[str, FieldPattern] = {
    "onset": FieldPattern(
        direct=(
            "什麼時候開始", "何時開始", "什麼時候發生", "從什麼時候", "開始的時間",
            "什麼時候出現", "幾時開始",
            "when did it start", "when did they start", "when it started",
            "when did you first",
            "いつから", "いつ始ま",
            "언제부터", "언제 시작",
            "bắt đầu từ khi nào", "khi nào bắt đầu",
        ),
        pair_a=("突然", "忽然", "一下子", "急性", "sudden", "abrupt", "急に", "갑자기", "đột ngột"),
        pair_b=(
            "漸進", "逐漸", "慢慢", "漸漸", "越來越",
            "gradual", "slowly", "だんだん", "徐々", "점점", "서서히", "từ từ", "dần dần",
        ),
    ),
    "duration": FieldPattern(
        direct=(
            "持續多久", "持續多長", "多久了", "多長時間", "多長的時間",
            "幾天了", "幾週了", "幾個月了", "多少天了",
            "how long have", "how long has", "how long did",
            "どのくらい続", "どれくらい続", "いつまで続",
            "얼마나 됐", "얼마나 지속", "얼마 동안",
            "kéo dài bao lâu", "bao lâu rồi",
        ),
        pair_a=(
            "一直", "持續", "都是這樣", "都這樣", "整天", "從頭到尾",
            "constant", "continuous", "all the time", "ずっと", "続いて",
            "계속", "쭉", "liên tục", "suốt",
        ),
        pair_b=(
            "間歇", "偶爾", "有時候", "某些時候", "斷斷續續", "時好時壞", "來來去去", "時有時無",
            "intermittent", "comes and goes", "come and go", "on and off", "off and on",
            "時々", "断続", "たまに",
            "간헐", "가끔", "때때로",
            "ngắt quãng", "thỉnh thoảng", "lúc có lúc không",
        ),
        veto=_FREQUENCY_MARKERS,
    ),
    "severity": FieldPattern(
        direct=(
            "幾分", "0到10", "0 到 10", "1到10", "1 到 10", "十分之", "打幾分",
            "多嚴重", "嚴重程度", "有多痛", "多不舒服",
            "scale of", "0 to 10", "1 to 10", "how severe", "how bad", "how painful",
            "10段階", "どのくらい痛", "どれくらいひど",
            "몇 점", "얼마나 심", "얼마나 아프",
            "thang điểm", "mức độ nặng", "đau đến mức nào",
        ),
    ),
}


def _normalize(text: str) -> str:
    return (text or "").lower()


def match_focus_fields(next_focus: str) -> set[str]:
    """回傳這段 next_focus 文字語意上指向的 HPI 欄位集合（可能為空）。

    純比對，不看 missing_hpi——是否算違規由 `evaluate_next_focus` 合成判斷。
    """
    text = _normalize(next_focus)
    if not text.strip():
        return set()
    if any(marker in text for marker in _NON_HPI_TOPIC_MARKERS):
        # 非 HPI 主題（風險因子 / 次要補問）→ 本層不介入。
        return set()

    matched: set[str] = set()
    for field, spec in FIELD_PATTERNS.items():
        if spec.veto and any(v in text for v in spec.veto):
            continue
        if any(term in text for term in spec.direct):
            matched.add(field)
            continue
        if (
            spec.pair_a
            and spec.pair_b
            and any(a in text for a in spec.pair_a)
            and any(b in text for b in spec.pair_b)
        ):
            matched.add(field)
    return matched


class FocusVerdict(NamedTuple):
    """`evaluate_next_focus` 的判定結果。

    reask_fields 非空 ＝ next_focus 在重問已覆蓋（已答或已表示不知道）的欄位。
    """

    reask_fields: tuple[str, ...]
    matched_fields: tuple[str, ...]


def evaluate_next_focus(next_focus: str, missing_hpi: Any) -> FocusVerdict:
    """判斷 next_focus 是否重問了已從 missing_hpi 移除的欄位。

    fail-open：missing_hpi 型別不對、命中欄位裡有任何一欄仍缺失、或完全沒命中 →
    皆判為無違規。
    """
    if not isinstance(missing_hpi, list):
        return FocusVerdict((), ())
    matched = match_focus_fields(next_focus)
    if not matched:
        return FocusVerdict((), ())
    still_missing = {m for m in missing_hpi if isinstance(m, str)} & set(HPI_FIELD_IDS)
    if matched & still_missing:
        # 命中的欄位裡還有沒問完的 → 有合法解釋，放行（避免誤殺相鄰欄位提問）。
        return FocusVerdict((), tuple(sorted(matched)))
    return FocusVerdict(tuple(sorted(matched - still_missing)), tuple(sorted(matched)))


# fallback 指令最多列幾個仍缺失欄位（next_focus 有 60 字上限，且「一次只問一個問題」）。
_MAX_FALLBACK_FIELDS = 3

# HPI 欄位在替代指令裡的顯示名。取 HPI_STEPS 標籤「Onset(發生時間)」的英文前綴——
# 與對話端 prompt 的 HPI 清單標題逐字相同（對話 LLM 查得到對應），且**不含中文**：
# next_focus 會進對話 LLM 的 system prompt，塞中文標籤會給非中文場次多一個把中文
# 洩漏到病患回覆的機會（不變式 #12 語言鐵律）。
_FIELD_DISPLAY: dict[str, str] = {
    step["id"]: (step["zh"].split("(", 1)[0].strip() or step["id"])
    for step in HPI_STEPS
}


def build_fallback_focus(missing_hpi: Any, language: str | None) -> str:
    """命中違規時的替代 next_focus：指向仍缺失欄位，或改為簡短確認後收尾。"""
    ordered = (
        [m for m in missing_hpi if isinstance(m, str) and m in HPI_FIELD_IDS]
        if isinstance(missing_hpi, list)
        else []
    )
    if ordered:
        return _i18n_get(
            "llm.supervisor_next_focus_redirect",
            language,
            fields=" / ".join(
                _FIELD_DISPLAY.get(f, f) for f in ordered[:_MAX_FALLBACK_FIELDS]
            ),
        )
    return _i18n_get("llm.supervisor_next_focus_wrap_up", language)


# =============================================================================
# 消費端：一輪延遲的 guidance 撞上「不知道」（2026-08-17 第二輪 e2e 實證）
# =============================================================================
# 第一輪修復（prompt + 產出自檢）之後重跑 `dontknow_zh`：Supervisor 這次的 next_focus
# **全部乾淨**（拒答 duration 後那一版是「這個頻尿在晚上會特別明顯嗎？」＝timing），
# 但對話 LLM 仍問出「那這個頻尿是一直都這樣，還是只有某些時候才特別明顯呢？」。
#
# 根因在**時序**而非措辭：supervisor 是 fire-and-forget，對話端這一輪讀到的是
# **上一輪**算出來的 guidance（llm_conversation `#2` 註記）。病患剛對「持續多久了」
# 答不知道，而 pending 的 next_focus 正是「請問這個頻尿大概持續多久了？」——
# 那份 guidance 是在病患拒答**之前**算的。既有的 `llm.supervisor_guidance_no_repeat`
# 護欄只是叫 LLM 自己判斷「已答過就別問」，實測 LLM 選擇「換句話問得軟一點」。
#
# 對策（確定性，不靠 LLM 自律）：病患**最後一則**訊息是「不知道」時，它必然是對
# **上一則 AI 問句**的回答；若 pending next_focus 指向同一個欄位，這份 guidance 對
# 該欄位已確定過期 → 換成指向其他仍缺失欄位的推進指令（沿用同一組 i18n 文案）。
#
# 誤殺分析：
# - 只在「最後一則病患訊息是拒答」時才啟動，其餘輪次完全不介入。
# - 還要求 pending next_focus 與**剛被拒答的那一欄**是同一欄；指向別欄一律原樣注入
#   （拒答 A 後 guidance 指向 B 是正確行為，不得攔）。
# - 只改注入對話 LLM 的文字，**不動 Redis 裡的 guidance**：missing_hpi 與完整度
#   仍是 Supervisor 說了算（「不知道是第三態」語意不變），下一輪若 Supervisor 認為
#   該欄仍該問，它會再出現——本層沒有永久關閉任何欄位。

# 「不知道／記不得／無法回答」的五語表達。**刻意獨立於 e2e driver 的
# `DONTKNOW_PATTERNS`**（那是驗收端 oracle），也刻意不抄 persona 台詞。
_DONT_KNOW_MARKERS: tuple[str, ...] = (
    "不知道", "不曉得", "不清楚", "不記得", "沒印象", "想不起", "說不上來",
    "不確定", "沒注意", "答不出",
    "don't know", "do not know", "dunno", "not sure", "no idea",
    "can't remember", "cannot remember", "don't remember", "can't recall",
    "わからな", "分からな", "わかりません", "覚えていない", "覚えてない",
    "記憶にない", "はっきりしません",
    "모르겠", "몰라요", "모릅니다", "기억이 안", "기억나지 않", "잘 모르",
    "không biết", "không nhớ", "không rõ", "không chắc",
)


def is_dont_know(text: str) -> bool:
    """這句病患回答是否為「不知道／記不得／無法回答」。"""
    lowered = _normalize(text)
    return any(marker in lowered for marker in _DONT_KNOW_MARKERS)


def declined_fields_from_history(history: list[dict[str, Any]]) -> set[str]:
    """病患**最後一則**訊息若是拒答，回傳它拒答掉的 HPI 欄位（可能為空集合）。

    判定鏈很短且可證：最後一則病患訊息是對「上一則 AI 問句」的回答，故只要那則
    AI 問句能對應到某個 HPI 欄位，該欄位就是剛剛被拒答的欄位。對應不到（例如問
    Location）→ 空集合 → 本層不介入。
    """
    last_patient_index: int | None = None
    for index in range(len(history) - 1, -1, -1):
        if history[index].get("role") in ("patient", "user"):
            last_patient_index = index
            break
    if last_patient_index is None:
        return set()
    if not is_dont_know(str(history[last_patient_index].get("content") or "")):
        return set()
    for index in range(last_patient_index - 1, -1, -1):
        if history[index].get("role") in ("assistant", "ai"):
            return match_focus_fields(str(history[index].get("content") or ""))
    return set()


def effective_next_focus(
    history: list[dict[str, Any]],
    guidance: dict[str, Any],
    language: str | None = None,
) -> str:
    """回傳本輪真正該注入的 next_focus 文字（可能是原文，也可能是替代指令）。

    只在「病患剛拒答的欄位 ∩ next_focus 指向的欄位」非空時替換——那份 guidance 是
    在拒答之前算的，對該欄位已確定過期。
    """
    next_focus = guidance.get("next_focus") or ""
    if not isinstance(next_focus, str) or not next_focus.strip():
        return ""
    declined = declined_fields_from_history(history)
    if not declined or not (match_focus_fields(next_focus) & declined):
        return next_focus

    missing = guidance.get("missing_hpi")
    remaining = [
        m
        for m in (missing if isinstance(missing, list) else [])
        if isinstance(m, str) and m in HPI_FIELD_IDS and m not in declined
    ]
    logger.info(
        "next_focus 過期（病患剛拒答 %s，pending 指導仍指向同欄）→ 改注入推進指令",
        sorted(declined),
    )
    return build_fallback_focus(remaining, language)


def build_dont_know_ban(declined: set[str] | tuple[str, ...], language: str | None) -> str:
    """本輪限定的「剛被拒答的面向禁止再問」硬性禁令（含該欄位的換句話例句）。

    2026-08-17 第三輪 e2e 的必要性證據：把過期指導換掉之後（上面那一層），
    Supervisor 與注入文字都不再提 Duration，對話 LLM **仍然**自己問出
    「頻尿的感覺是一直都有，還是有時候才會出現呢？」——靜態 prompt 中段那條
    「不得換句話重問」規則（`build_system_prompt` 的問診準則）在長 prompt 中段
    競爭不過當下語境。作法沿用本檔案已驗證有效的「收尾三明治」：把**本輪限定**的
    禁令放到 system prompt 最前與最後（最高優先＋最高 recency），並**只列出剛被
    拒答那一欄**的換句話例句。

    ⚠️ 例句必須逐欄給：拒答 Onset 那一輪若順手把 Duration 的句式也列成禁令，
    會讓 Duration 這一欄再也問不出來（漏問）。這是本層最主要的誤殺風險。
    """
    fields = [f for f in sorted(declined) if f in FIELD_PATTERNS]
    if not fields:
        return ""
    examples = "；".join(
        _i18n_get(f"llm.dont_know_ban_examples.{field}", language) for field in fields
    )
    return _i18n_get(
        "llm.dont_know_turn_ban",
        language,
        fields=" / ".join(_FIELD_DISPLAY.get(f, f) for f in fields),
        examples=examples,
    )


def sanitize_guidance(
    guidance: dict[str, Any], language: str | None = None
) -> dict[str, Any]:
    """對 Supervisor 輸出做 next_focus 自檢；命中則就地換成中性推進指令。

    回傳新的 dict（不就地改 caller 的物件）。命中時額外寫入 `next_focus_guard`
    診斷欄位（原文 + 被判定重問的欄位），供 e2e 逐字稿與線上除錯佐證；
    消費端（format_messages / conclusion_policy / WS 廣播）只讀 canonical 欄位，
    多這個 key 不影響行為。
    """
    if not isinstance(guidance, dict):
        return guidance
    next_focus = guidance.get("next_focus")
    if not isinstance(next_focus, str) or not next_focus.strip():
        return guidance

    verdict = evaluate_next_focus(next_focus, guidance.get("missing_hpi"))
    if not verdict.reask_fields:
        return guidance

    replacement = build_fallback_focus(guidance.get("missing_hpi"), language)
    logger.warning(
        "next_focus 自檢命中：重問已覆蓋欄位 %s，已替換 | original=%r",
        list(verdict.reask_fields),
        next_focus,
    )
    sanitized = dict(guidance)
    sanitized["next_focus"] = replacement
    sanitized["next_focus_guard"] = {
        "replaced": True,
        "reask_fields": list(verdict.reask_fields),
        "original_next_focus": next_focus,
    }
    return sanitized
