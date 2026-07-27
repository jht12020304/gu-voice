"""BLOCKER F：收尾輪「不得發問」的確定性 backstop。

背景
----
收尾輪（`should_conclude=True`）過去只有 prompt 一層防線（極簡收尾 system prompt
＋ `format_messages(conclude=True)` 的前後夾擊）。2026-07-27 真跑 `ed_3b_zh` 兩次，
**同一份碼** run1 的 `r5_wrapup_no_new_question` 紅（收尾輪硬問一題，病患留下懸空問句
就被導去感謝頁）、run2 綠 —— 遵從是機率性的。ED 場 `effective_hard_cap` 正好 15、
收尾輪與硬上限重合、零餘裕，沒有下一輪能補救。

測試表刻意**雙向且對稱**（前兩輪的教訓：只往單一方向加測試 → 一次改出 over-trigger、
一次改出 under-trigger）：
  - 「該命中」：5 語 ×（有問號 / 無問號只有疑問句式）都要被攔下改送制式收尾語。
  - 「不該命中」：5 語的合規收尾語 + 每語一組**近似誤判陷阱**（ja「ですから」、
    ko「니까」、vi「không cần」、en 句首「Have」、zh「是否」）都必須原樣通過。
  - 非收尾輪的正常提問必須完全不受影響（backstop 只作用在收尾輪）。

語料來源聲明
------------
以下所有台詞都是**為本測試新寫的**，不是從 `scripts/e2e_realopenai/driver.py` 的
persona 台詞或既有測試抄來的。e2e 那邊的收尾斷言 `_wrapup_has_no_question` 只比對
`?` / `？` 兩個字元、且從不提供 AI 側語料；本檔的疑問句式（呢 / 有沒有 / ですか /
계십니까 / phải không / 句首 Do）與合規收尾語（原座位、ghế chờ、자리에서、その場…）
在 driver.py 中一句都不存在（已 grep 確認）。
"""

from __future__ import annotations

import pytest

import app.websocket.conversation_handler as ch
from app.utils.i18n_messages import get_message as i18n_get

from .conftest import (
    StubDetector,
    make_settings,
    run_text_turn,
)

WRAP_UP_KEY = "ws.session_terminated_completed_notice"
LOCALES = ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN")


# ══════════════════════════════════════════════════════════════════
# 第一層：`_looks_like_question` 純函式的雙向矩陣
# ══════════════════════════════════════════════════════════════════

# ── 該命中：收尾輪出現這些就是「又發問了」──────────────────────
QUESTION_CORPUS: list[tuple[str, str]] = [
    # zh-TW ── 有問號
    ("zh 問號", "了解了。另外想確認一下，這半年您的體重有明顯往下掉嗎？"),
    # zh-TW ── 無問號，只靠疑問語尾助詞「呢」
    ("zh 無問號-呢", "在結束之前，我還想知道您平常一天大概喝多少水呢。"),
    # zh-TW ── 無問號，正反問句「有沒有」
    ("zh 無問號-有沒有", "最後補一句，您家裡有沒有長輩得過腎臟方面的毛病。"),
    # zh-TW ── 無問號，「請問」
    ("zh 無問號-請問", "資料我都收到了。請問您平時有在服用抗凝血劑。"),
    # en-US ── 有問號
    ("en 問號", "Before we wrap up, have you run a fever at any point this week?"),
    # en-US ── 無問號，句首助動詞
    ("en 無問號-Do", "Thanks for all of that. Do you take any blood thinners such as warfarin."),
    # en-US ── 無問號，句首 wh 詞
    ("en 無問號-When", "One more thing before the doctor sees you. When did the swelling begin."),
    # ja-JP ── 有問號
    ("ja 問號", "最後に一点だけ、これまでに尿路結石と言われたことはありますか？"),
    # ja-JP ── 無問號，丁寧体疑問形
    ("ja 無問號-ますか", "念のための確認です。血液をさらさらにするお薬を飲んでいますか。"),
    # ko-KR ── 有問號
    ("ko 問號", "마지막으로 하나만 더 여쭐게요. 최근에 열이 난 적이 있으신가요?"),
    # ko-KR ── 無問號，격식체 `-ㅂ니까`（습/십 兩種收尾都要抓到）
    ("ko 無問號-계십니까", "확인차 여쭙습니다. 혈액을 묽게 하는 약을 복용하고 계십니까."),
    ("ko 無問號-있습니까", "하나만 더 확인하겠습니다. 소변볼 때 통증이 있습니까."),
    # vi-VN ── 有問號
    ("vi 問號", "Trước khi kết thúc, mấy hôm nay bạn có bị sốt không?"),
    # vi-VN ── 無問號，"phải không"
    ("vi 無問號-phải không", "Tôi hỏi thêm một ý nhỏ, bạn đang uống thuốc chống đông phải không."),
]

# ── 不該命中：合規收尾語（5 語）＋每語一組近似誤判陷阱 ──────────
NON_QUESTION_CORPUS: list[tuple[str, str]] = [
    # zh-TW 合規收尾
    (
        "zh 合規收尾",
        "謝謝您把狀況說得這麼清楚。麻煩您在原座位稍候，醫師看過這些紀錄後就會為您診療。",
    ),
    # zh-TW 陷阱：「是否」出現在陳述句（若把「是否」當疑問詞會誤判）
    ("zh 陷阱-是否", "醫師會依照這些資訊評估是否需要進一步的檢查，請您在原處稍候。"),
    # zh-TW 陷阱：「吧」「了解」等語尾（非疑問）
    ("zh 陷阱-語尾", "您提供的用藥清單很重要，就先保留著讓醫師當面看一下吧。"),
    # en-US 合規收尾
    (
        "en 合規收尾",
        "Thank you for walking me through all of that. Please stay in your seat; "
        "the physician will review these notes and call you shortly.",
    ),
    # en-US 陷阱：句首 "Have" 是祈使句，不是問句
    ("en 陷阱-Have", "Have a seat by the window. Our staff will call your name shortly."),
    # en-US 陷阱：句首 "Will"（被刻意排除）
    ("en 陷阱-Will", "Will be handed straight to the physician along with your notes."),
    # ja-JP 合規收尾
    (
        "ja 合規收尾",
        "詳しくお話しくださりありがとうございました。そのままの席でお待ちください。"
        "医師がすぐに拝見します。",
    ),
    # ja-JP 陷阱：「ですから」是接續助詞，不是疑問形
    ("ja 陷阱-ですから", "とても大切な情報ですから、そのまま医師に引き継ぎます。"),
    # ko-KR 合規收尾
    (
        "ko 合規收尾",
        "자세히 말씀해 주셔서 감사합니다. 자리에서 잠시만 기다려 주시면 "
        "의사 선생님이 곧 봐 드리겠습니다.",
    ),
    # ko-KR 陷阱：「니까」是연결어미（終聲不是 ㅂ），不是격식체 의문형
    ("ko 陷阱-니까", "접수 순서대로 진행되니까 자리에서 그대로 기다려 주세요."),
    # ko-KR 陷阱：「습니다」平敘形只差一個字，不得被當成「습니까」
    ("ko 陷阱-습니다", "말씀해 주신 내용은 모두 의사 선생님께 전달됩니다. 잠시 기다려 주세요."),
    # vi-VN 合規收尾
    (
        "vi 合規收尾",
        "Cảm ơn bạn đã chia sẻ chi tiết. Bạn vui lòng ngồi tại ghế chờ, "
        "bác sĩ sẽ xem thông tin này và khám cho bạn sớm.",
    ),
    # vi-VN 陷阱："không" 用在否定，不是疑問
    ("vi 陷阱-không cần", "Bạn không cần làm thêm gì nữa, chỉ cần ngồi chờ tại chỗ."),
]


@pytest.mark.parametrize("label,text", QUESTION_CORPUS, ids=[c[0] for c in QUESTION_CORPUS])
def test_looks_like_question_positive(label: str, text: str) -> None:
    """該命中：5 語 × 有問號／無問號疑問句式，一律判為發問。"""
    assert ch._looks_like_question(text) is True, f"{label} 應被判為發問：{text!r}"


@pytest.mark.parametrize(
    "label,text", NON_QUESTION_CORPUS, ids=[c[0] for c in NON_QUESTION_CORPUS]
)
def test_looks_like_question_negative(label: str, text: str) -> None:
    """不該命中：合規收尾語與近似陷阱都必須原樣通過（不誤傷）。"""
    assert ch._looks_like_question(text) is False, f"{label} 不應被判為發問：{text!r}"


@pytest.mark.parametrize("lang", LOCALES)
def test_canned_wrap_up_is_not_itself_a_question(lang: str) -> None:
    """冪等性：制式收尾語本身在 5 語下都不得被判成問句，也不得含問號。

    否則 backstop 會把自己的替換品再判一次（未來若有人改成迴圈就會爆），
    且 e2e 的 `_wrapup_has_no_question`（只比對 ? / ？）也必須恆綠。
    """
    canned = i18n_get(WRAP_UP_KEY, lang)
    assert canned, f"{lang} 缺少制式收尾語"
    assert "?" not in canned and "？" not in canned
    assert ch._looks_like_question(canned) is False, f"{lang} 制式收尾語被誤判：{canned!r}"


# ══════════════════════════════════════════════════════════════════
# 第二層：跑完整一輪 `_handle_text_message`，驗病患**實收**的內容
# ══════════════════════════════════════════════════════════════════

def _hard_cap_now() -> object:
    """硬上限 = 1 → 本輪（第一則病患訊息）即收尾輪，且與硬上限重合（零餘裕）。"""
    return make_settings(MAX_PATIENT_TURNS_HARD_CAP=1)


def _benign_context(language: str = "zh-TW") -> dict:
    """K=0 的主訴（排尿疼痛），避免 §3b 動態 cap 加成干擾回合數設定。"""
    return {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "user_id": "user-1",
        "chief_complaint": "排尿疼痛",
        "chief_complaint_display": "排尿疼痛",
        "patient_info": {"name": "測試病患"},
        "language": language,
    }


def test_wrap_up_turn_question_is_replaced_with_canned_text(monkeypatch) -> None:
    """該生效：收尾輪 LLM 仍發問 → 病患實收的是制式收尾語，不是那句問句。"""
    offending = "資料都收齊了。不過在結束前，想再確認一下您最近有沒有發燒過？"
    r = run_text_turn(
        monkeypatch,
        text="這兩天小便的時候刺痛得厲害",
        settings=_hard_cap_now(),
        session_context=_benign_context("zh-TW"),
        llm_programs=[[offending]],
        detector=StubDetector(alerts=[]),
    )

    canned = i18n_get(WRAP_UP_KEY, "zh-TW")
    chunks = r.cap.chunk_texts()

    # 病患「看到／聽到」的每一個 chunk 都是制式收尾語，原問句一個字都沒送出去
    assert chunks == [canned], chunks
    assert offending not in "".join(chunks)
    assert "？" not in "".join(chunks) and "?" not in "".join(chunks)

    # 對話歷史與 DB 落地的也必須是替換後的內容（否則 SOAP 會讀到根本沒送出的問句）
    last_ai = [e for e in r.conversation_history if e["role"] == "assistant"][-1]
    assert last_ai["content"] == canned
    persisted = [c.args for c in r.conv_create.call_args_list if c.args[2] == "assistant"]
    assert persisted and persisted[-1][3] == canned

    # 場次仍照常收尾（backstop 不得改變自動結束的行為）
    assert r.update_status.await_count >= 1
    assert any(
        m["payload"].get("status") == "completed"
        for m in r.cap.messages_of_type("session_status")
    )


@pytest.mark.parametrize(
    "lang,offending",
    [
        ("en-US", "That is everything I needed. Before you go, are you on any blood thinners?"),
        ("ja-JP", "ありがとうございました。最後に、以前に同じ症状が出たことはありますか？"),
        ("ko-KR", "말씀 잘 들었습니다. 끝으로 최근에 열이 난 적이 있으신가요?"),
        ("vi-VN", "Cảm ơn bạn. Trước khi kết thúc, gần đây bạn có bị sốt không?"),
    ],
)
def test_wrap_up_backstop_is_localized(monkeypatch, lang: str, offending: str) -> None:
    """該生效（其餘 4 語）：替換文案跟著場次語言走，不會退回中文。"""
    r = run_text_turn(
        monkeypatch,
        text="pain when urinating",
        language=lang,
        settings=_hard_cap_now(),
        session_context=_benign_context(lang),
        llm_programs=[[offending]],
        detector=StubDetector(alerts=[]),
    )
    assert r.cap.chunk_texts() == [i18n_get(WRAP_UP_KEY, lang)]


def test_compliant_wrap_up_passes_through_untouched(monkeypatch) -> None:
    """不該誤傷（同為收尾輪）：合規收尾語必須原樣送給病患，不被制式語取代。"""
    compliant = (
        "謝謝您耐心說明。麻煩您在原座位稍候，醫師看完這些紀錄就會為您安排診療。"
    )
    r = run_text_turn(
        monkeypatch,
        text="這兩天小便的時候刺痛得厲害",
        settings=_hard_cap_now(),
        session_context=_benign_context("zh-TW"),
        llm_programs=[[compliant]],
        detector=StubDetector(alerts=[]),
    )
    assert "".join(r.cap.chunk_texts()) == compliant
    assert i18n_get(WRAP_UP_KEY, "zh-TW") not in "".join(r.cap.chunk_texts())
    last_ai = [e for e in r.conversation_history if e["role"] == "assistant"][-1]
    assert last_ai["content"] == compliant


def test_non_wrap_up_turn_question_is_never_replaced(monkeypatch) -> None:
    """不該誤傷（最重要的一條）：**非**收尾輪的正常提問完全不受 backstop 影響。

    backstop 若忘了綁 `should_conclude`，整條問診管線會從第一題就被制式收尾語吃掉。
    """
    normal_question = "了解。那這個刺痛是從什麼時候開始的呢？"
    r = run_text_turn(
        monkeypatch,
        text="這兩天小便的時候刺痛得厲害",
        settings=make_settings(MAX_PATIENT_TURNS_HARD_CAP=10),  # 遠未到硬上限
        session_context=_benign_context("zh-TW"),
        llm_programs=[[normal_question]],
        detector=StubDetector(alerts=[]),
    )
    assert "".join(r.cap.chunk_texts()) == normal_question
    assert i18n_get(WRAP_UP_KEY, "zh-TW") not in "".join(r.cap.chunk_texts())
    # 也沒有被誤判成收尾 → 場次不該結束
    assert not any(
        m["payload"].get("status") == "completed"
        for m in r.cap.messages_of_type("session_status")
    )


def test_empty_response_fallback_is_not_clobbered_by_backstop(monkeypatch) -> None:
    """不該誤傷（跨機制）：A1 [D5] 空回應 fallback 自帶問句，backstop 不得覆寫它。

    空回應 fallback 文案本身就是「可以請您再說一次嗎？」，且 `used_empty_fallback`
    會讓軟門檻收尾被 soft_defer 否決（場次多半不會在本輪結束）——若被換成
    「本次問診已經結束」，病患會收到「已結束」卻又被繼續問。
    """
    r = run_text_turn(
        monkeypatch,
        text="這兩天小便的時候刺痛得厲害",
        settings=_hard_cap_now(),  # 收尾輪
        session_context=_benign_context("zh-TW"),
        llm_programs=[[""], [""]],  # 首次空 + retry 仍空 → 走 fallback
        detector=StubDetector(alerts=[]),
    )
    fallback = i18n_get("ws.ai_empty_retry_fallback", "zh-TW")
    assert r.cap.chunk_texts() == [fallback]
    assert i18n_get(WRAP_UP_KEY, "zh-TW") not in "".join(r.cap.chunk_texts())


def test_ed_zero_margin_hard_cap_turn_is_safe(monkeypatch) -> None:
    """重現 BLOCKER F 的實際場景：ED 場 §3b 動態 cap=15，收尾輪與硬上限重合。

    K=3（勃起功能障礙）→ effective_hard_cap = 10 + 3 + 2 = 15。第 15 個病患回合
    同時是「收尾輪」與「最後一輪」，LLM 不從就零餘裕。這裡釘住：即使 LLM 在這一輪
    照樣硬問一題，病患收到的仍是合規收尾語，且場次照常 completed。
    """
    ctx = _benign_context("zh-TW")
    ctx["chief_complaint"] = "勃起功能障礙"
    ctx["chief_complaint_display"] = "勃起障礙"
    settings = make_settings(
        MAX_PATIENT_TURNS_HARD_CAP=10, RISK_FACTOR_HARD_CAP_BUFFER=2
    )
    assert ch._effective_hard_cap(settings, ch._session_risk_factor_count(ctx)) == 15

    history = []
    for i in range(14):  # 本輪的病患訊息會補成第 15 個回合
        history.append({"role": "patient", "content": f"病患第 {i + 1} 句"})
        history.append({"role": "assistant", "content": f"AI 第 {i + 1} 句"})

    r = run_text_turn(
        monkeypatch,
        text="這半年幾乎都硬不起來，晨勃也沒有了",
        settings=settings,
        session_context=ctx,
        conversation_history=history,
        llm_programs=[["謝謝您的說明。對了，您有在服用治療高血壓的藥物嗎？"]],
        detector=StubDetector(alerts=[]),
    )

    joined = "".join(r.cap.chunk_texts())
    assert joined == i18n_get(WRAP_UP_KEY, "zh-TW")
    assert "？" not in joined and "?" not in joined  # ＝ e2e r5_wrapup_no_new_question
    assert any(
        m["payload"].get("status") == "completed"
        for m in r.cap.messages_of_type("session_status")
    )


def test_backstop_logs_llm_noncompliance(monkeypatch, caplog) -> None:
    """可觀測性：替換時必須留 WARNING（含原輸出），讓人知道 LLM 又不從了。"""
    import logging

    caplog.set_level(logging.WARNING, logger=ch.logger.name)
    run_text_turn(
        monkeypatch,
        text="這兩天小便的時候刺痛得厲害",
        settings=_hard_cap_now(),
        session_context=_benign_context("zh-TW"),
        llm_programs=[["好的。順帶一提，您平常一天大概喝多少水呢？"]],
        detector=StubDetector(alerts=[]),
    )
    hits = [rec for rec in caplog.records if "收尾輪 LLM 仍發問" in rec.getMessage()]
    assert hits, [r.getMessage() for r in caplog.records]
    assert "喝多少水" in hits[0].getMessage()
