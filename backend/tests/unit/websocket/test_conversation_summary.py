"""`session_context["conversation_summary"]` 必須真的被寫入（原本是死 key）。

`red_flag_detector._semantic_detect` 會讀 `session_context["conversation_summary"]`
並以「對話摘要：…」放進 LLM 的病患背景，但這個 key 從 session_context 建立
（`conversation_websocket`）到全程都沒有任何地方寫入，全 repo 也搜不到寫入點
→ 語意層永遠拿到 None。後果是紅旗兩層都只看得到「本輪單句 + 主訴字串」，
**跨輪累積型 critical 偵測不到**（前輪講發燒、本輪講腰痛＝urosepsis；
前輪講尿不出來、本輪講脹痛）。

長度必須有上限：整場逐字稿塞進紅旗 prompt 既燒 token 又稀釋最新症狀。
"""

from __future__ import annotations

from typing import Any

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    StubDetector,
    make_settings,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID
_build = ch._build_conversation_summary


def _turn(patient: str, ai: str) -> list[dict[str, Any]]:
    return [
        {"role": "patient", "content": patient},
        {"role": "assistant", "content": ai},
    ]


# ── 純函式：格式 ────────────────────────────────────────
def test_empty_history_returns_empty_string():
    assert _build([]) == ""


def test_history_without_dialog_returns_empty_string():
    """只有 _cap_conversation_history 壓出來的 system 摘要 → 不進紅旗 prompt。"""
    assert _build([{"role": "system", "content": "前 20 輪摘要：……"}]) == ""


def test_blank_content_entries_are_dropped():
    assert _build([{"role": "patient", "content": "   "}]) == ""


def test_formats_speaker_labelled_lines_oldest_first():
    history = _turn("早上開始發燒到三十九度", "發燒有多久了？")
    assert _build(history) == "病患：早上開始發燒到三十九度\nAI：發燒有多久了？"


def test_user_role_is_treated_as_patient():
    """歷史上兩種 role 名稱都出現過（patient / user）。"""
    assert _build([{"role": "user", "content": "會痛"}]) == "病患：會痛"


def test_newlines_inside_content_are_flattened():
    """單則發言不可換行，否則會破壞「一行一則」的可讀格式。"""
    out = _build([{"role": "patient", "content": "會痛\n而且有血"}])
    assert out == "病患：會痛 而且有血"


# ── 純函式：上限 ────────────────────────────────────────
def test_keeps_only_most_recent_turns():
    history: list[dict[str, Any]] = []
    for i in range(10):
        history += _turn(f"病患第{i}句", f"AI第{i}句")
    out = _build(history, max_turns=3)
    assert out.count("\n") == 5  # 3 組來回 = 6 行
    assert "病患第9句" in out and "AI第9句" in out
    assert "病患第6句" not in out, "應只保留最近 3 組"


def test_long_entry_is_truncated_with_ellipsis():
    out = _build([{"role": "patient", "content": "痛" * 500}], entry_max_chars=20)
    assert out.startswith("病患：" + "痛" * 20 + "…")
    assert len(out) == len("病患：") + 21


def test_total_length_cap_drops_oldest_first():
    history: list[dict[str, Any]] = []
    for i in range(6):
        history += _turn(f"P{i}" + "痛" * 60, f"A{i}" + "嗯" * 60)
    out = _build(history, max_turns=6, max_chars=200)
    assert len(out) <= 200
    assert "A5" in out, "最新一則必須留著（紅旗判的是『現在』的風險）"
    assert "P0" not in out


def test_default_caps_are_bounded():
    """預設值本身就要是有界的，避免呼叫端忘了傳參數就把整場塞進 prompt。"""
    history: list[dict[str, Any]] = []
    for i in range(50):
        history += _turn("排尿灼熱感" * 30, "了解，還有其他症狀嗎" * 30)
    out = _build(history)
    assert len(out) <= ch._CONVERSATION_SUMMARY_MAX_CHARS
    assert out.count("\n") + 1 <= ch._CONVERSATION_SUMMARY_MAX_TURNS * 2


# ── 接線：偵測器真的收得到 ────────────────────────────────
class _CapturingDetector(StubDetector):
    """記下每次 detect 收到的 session_context 快照。"""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.seen: list[dict[str, Any]] = []

    async def detect(self, text: str, session_context: dict[str, Any]):
        self.seen.append(dict(session_context))
        return await super().detect(text, session_context)


def _ctx() -> dict[str, Any]:
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "排尿疼痛",
        "chief_complaint_display": "排尿疼痛",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }


def test_first_turn_has_no_summary(monkeypatch):
    """第一輪沒有前文 → 不寫這個 key（`_semantic_detect` 才會略過整行，
    而不是印出「對話摘要：」後面空無一物）。"""
    det = _CapturingDetector()
    run_text_turn(
        monkeypatch, text="我排尿會痛", detector=det, session_context=_ctx()
    )
    assert det.seen
    assert "conversation_summary" not in det.seen[0]


def test_second_turn_detector_sees_previous_turns(monkeypatch):
    """跨輪累積：第二輪的紅旗偵測要看得到前一輪講過發燒。"""
    ctx = _ctx()
    history: list[dict[str, Any]] = []
    settings = make_settings(MAX_PATIENT_TURNS_HARD_CAP=10)

    det1 = _CapturingDetector()
    run_text_turn(
        monkeypatch,
        text="我早上開始發燒到三十九度",
        detector=det1,
        settings=settings,
        session_context=ctx,
        conversation_history=history,
        llm_programs=[["發燒多久了？"]],
    )

    det2 = _CapturingDetector()
    run_text_turn(
        monkeypatch,
        text="現在右邊腰很痛",
        detector=det2,
        settings=settings,
        session_context=ctx,
        conversation_history=history,
        llm_programs=[["好的。"]],
    )

    summary = det2.seen[0].get("conversation_summary")
    assert summary, "第二輪的 session_context 仍然沒有 conversation_summary（死 key）"
    assert "發燒" in summary, f"跨輪線索沒進摘要：{summary!r}"
    assert "發燒多久了？" in summary, "AI 的追問也要在摘要裡（提供上下文）"
    assert "現在右邊腰很痛" not in summary, (
        "本輪這句已由 detect(text, …) 單獨帶入，不可在摘要裡重複一次"
    )


def test_summary_refreshes_every_turn(monkeypatch):
    """第三輪的摘要要含第二輪，且仍不含第三輪自己。"""
    ctx = _ctx()
    history: list[dict[str, Any]] = []
    settings = make_settings(MAX_PATIENT_TURNS_HARD_CAP=10)
    for text, reply in (("尿不出來", "多久了？"), ("兩天了", "有脹痛嗎？")):
        run_text_turn(
            monkeypatch,
            text=text,
            detector=_CapturingDetector(),
            settings=settings,
            session_context=ctx,
            conversation_history=history,
            llm_programs=[[reply]],
        )
    det3 = _CapturingDetector()
    run_text_turn(
        monkeypatch,
        text="下腹脹得受不了",
        detector=det3,
        settings=settings,
        session_context=ctx,
        conversation_history=history,
        llm_programs=[["了解。"]],
    )
    summary = det3.seen[0]["conversation_summary"]
    assert "尿不出來" in summary and "兩天了" in summary
    assert "下腹脹得受不了" not in summary
