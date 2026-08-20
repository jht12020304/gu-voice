"""D-8 殘項兩則：Supervisor guidance 的 Redis key 前綴，以及壓縮摘要真的進 LLM。

## (2) guidance 讀取端的硬編碼 `"gu:"`

寫入端（`supervisor.analyze_next_step`）用 `settings.REDIS_KEY_PREFIX` 組 key，讀取端
（`_handle_text_message`）卻硬寫 `f"gu:session:{sid}:supervisor_guidance"`。只要環境把
REDIS_KEY_PREFIX 設成別的值（多環境共用一台 Redis 時就會），讀取端永遠讀不到 →
**supervisor 整條指導管線靜默失效**：沒有 next_focus、也沒有 hpi_completion_percentage
可觸發軟門檻收尾，而且不會有任何錯誤訊息。

觀測點選「軟門檻收尾有沒有發生」而不是「有沒有 read 到某個 key」——後者會把測試的
oracle 綁在實作細節上。

## (3) `_cap_conversation_history` 的摘要從來沒進過 LLM

壓縮那則寫成 `role="system"`，但 `format_messages` 無條件跳過所有 system 歷史 →
壓縮等於丟棄，長場次的前段病史對對話 LLM 完全消失（原意正好相反：那段程式碼刻意
「不靜默丟棄舊輪次，以免遺失紅旗臨床脈絡」）。
"""

from __future__ import annotations

import json

from app.core.config import Settings
from app.pipelines.llm_conversation import (
    HISTORY_SUMMARY_PREFIX,
    LLMConversationEngine,
)
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    make_settings,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID
_GUIDANCE = json.dumps(
    {"next_focus": "請詢問夜尿次數", "missing_hpi": [], "hpi_completion_percentage": 95},
    ensure_ascii=False,
)


def _ctx() -> dict:
    # 頻尿＝非 §3b 主訴（K=0）→ 軟門檻下限就是 MIN_PATIENT_TURNS_BEFORE_AUTO_END
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "頻尿",
        "chief_complaint_display": "頻尿",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }


def _concluded(update_status_mock) -> bool:
    return any(
        "completed" in call.args for call in update_status_mock.call_args_list
    )


def _run(monkeypatch, *, key_prefix: str, stored_key_prefix: str):
    redis = FakeRedis()
    redis.kv[f"{stored_key_prefix}session:{SID}:supervisor_guidance"] = _GUIDANCE
    return run_text_turn(
        monkeypatch,
        text="晚上要起來三次",
        settings=make_settings(
            REDIS_KEY_PREFIX=key_prefix,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            MAX_PATIENT_TURNS_HARD_CAP=99,  # 排除硬上限干擾，只驗軟門檻路徑
        ),
        session_context=_ctx(),
        redis=redis,
    )


def test_guidance_read_with_default_prefix(monkeypatch) -> None:
    """基準線：預設前綴下 guidance 讀得到 → HPI 95% 觸發軟門檻收尾。"""
    out = _run(monkeypatch, key_prefix="gu:", stored_key_prefix="gu:")
    assert _concluded(out.update_status)


def test_guidance_read_with_custom_prefix(monkeypatch) -> None:
    """修復核心：REDIS_KEY_PREFIX 換掉後，讀取端要跟著換（寫入端本來就會）。"""
    out = _run(monkeypatch, key_prefix="staging:", stored_key_prefix="staging:")
    assert _concluded(out.update_status), (
        "自訂 REDIS_KEY_PREFIX 下讀不到 guidance → supervisor 指導管線靜默失效"
    )


def test_guidance_not_read_from_hardcoded_prefix(monkeypatch) -> None:
    """反方向釘子：前綴設成 staging: 時，不得再去讀寫死的 gu: key。"""
    out = _run(monkeypatch, key_prefix="staging:", stored_key_prefix="gu:")
    assert not _concluded(out.update_status)


# ── (3) 壓縮摘要必須進 LLM ──────────────────────────────
def _engine() -> LLMConversationEngine:
    return LLMConversationEngine(Settings())


def test_history_summary_reaches_llm_messages() -> None:
    """`[前段對話摘要]` 那一則必須出現在送給 OpenAI 的 messages 裡。"""
    history = [
        {
            "role": "system",
            "content": f"{HISTORY_SUMMARY_PREFIX} 前 20 輪：病患主訴無痛肉眼血尿，"
            "已述吸菸 30 年、服用 warfarin。",
        },
        {"role": "patient", "content": "今天又有血塊"},
    ]
    messages = _engine().format_messages(history, "SYSTEM")
    contents = [m["content"] for m in messages]
    assert any(c.startswith(HISTORY_SUMMARY_PREFIX) for c in contents), (
        "壓縮摘要沒進 LLM → _cap_conversation_history 的壓縮等於靜默丟棄舊輪次"
    )
    assert any("warfarin" in c for c in contents)
    # 系統提示仍在最前（budget_messages 靠 messages[0] 保住它）
    assert messages[0]["content"] == "SYSTEM"


def test_other_system_history_entries_are_still_skipped() -> None:
    """只放行帶摘要前綴的那一則；其餘 system 歷史仍不得進 LLM。"""
    history = [
        {"role": "system", "content": "內部除錯訊息，不該進 prompt"},
        {"role": "patient", "content": "會痛"},
    ]
    messages = _engine().format_messages(history, "SYSTEM")
    assert all("內部除錯訊息" not in m["content"] for m in messages)


def test_summary_survives_wrap_up_turn() -> None:
    """收尾輪改用極簡 prompt，但既有臨床脈絡不得因此消失。"""
    history = [
        {"role": "system", "content": f"{HISTORY_SUMMARY_PREFIX} 病患有攝護腺癌家族史"},
        {"role": "patient", "content": "好的"},
    ]
    messages = _engine().format_messages(
        history, "WRAP_UP", language="zh-TW", conclude=True
    )
    assert any("攝護腺癌家族史" in m["content"] for m in messages)
