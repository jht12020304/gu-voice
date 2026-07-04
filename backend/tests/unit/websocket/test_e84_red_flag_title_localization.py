"""E8-4 單元測試：紅旗 alert title 依場次語言在地化（持久化/廣播端防禦性把關）。

守護的不變式：
- `_persist_and_emit_alert` 對「內建 catalogue（shared.URO_RED_FLAGS）」的
  canonical_id，一律依 session.language 重新解析 title，不信任上游傳進來
  的 title 實際語言（belt-and-suspenders：即使 red_flag_detector 日後又
  漂移回未在地化的 title，這裡仍能攔下）。
- DB 管理員自訂規則（canonical_id 存在但不在內建 catalogue）不可被覆寫成
  canonical_id 原始 slug —— 那是本次修法唯一該避免的 regression。
- A5 去重身份仍以 canonical_id 為主鍵，不受 title 覆寫影響。
"""

from __future__ import annotations

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    StubDetector,
    make_alert,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID
_KEY = ch._SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=SID)


def _session_context(language: str) -> dict:
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "chief_complaint_display": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": language,
    }


def test_en_us_session_gets_english_title_even_if_detector_returned_chinese(
    monkeypatch,
):
    """en-US 場次：即使 alert dict 帶著中文 title,持久化/廣播都應該是英文。"""
    alert = make_alert(
        severity="high",
        canonical_id="gross_hematuria",
        title="肉眼血尿",  # 模擬偵測器漂移，仍沿用中文範例
        description="patient reports red urine",
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("en-US"),
        detector=StubDetector(alerts=[alert]),
    )

    assert res.alert_create.call_count == 1
    persisted_data = res.alert_create.call_args.args[1]
    assert persisted_data["title"] == "Gross Hematuria"

    ws_alerts = res.cap.messages_of_type("red_flag_alert")
    assert len(ws_alerts) == 1
    assert ws_alerts[0]["payload"]["title"] == "Gross Hematuria"

    assert len(res.cap.dashboard_messages) == 1
    assert res.cap.dashboard_messages[0]["payload"]["title"] == "Gross Hematuria"


def test_zh_tw_session_gets_chinese_title_even_if_detector_returned_english(
    monkeypatch,
):
    """zh-TW 場次：即使 alert dict 帶著英文 title,持久化/廣播都應該是中文。"""
    alert = make_alert(
        severity="high",
        canonical_id="gross_hematuria",
        title="Gross Hematuria",
        description="病患陳述尿液帶血",
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("zh-TW"),
        detector=StubDetector(alerts=[alert]),
    )

    persisted_data = res.alert_create.call_args.args[1]
    assert persisted_data["title"] == "肉眼血尿"

    ws_alerts = res.cap.messages_of_type("red_flag_alert")
    assert ws_alerts[0]["payload"]["title"] == "肉眼血尿"
    assert res.cap.dashboard_messages[0]["payload"]["title"] == "肉眼血尿"


def test_ja_jp_session_resolves_catalogue_title(monkeypatch):
    """ja-JP 場次同樣要能正確解析（5 語全覆蓋守護，避免只顧 en/zh 兩語）。"""
    alert = make_alert(
        severity="high",
        canonical_id="gross_hematuria",
        title="肉眼血尿",
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("ja-JP"),
        detector=StubDetector(alerts=[alert]),
    )

    persisted_data = res.alert_create.call_args.args[1]
    assert persisted_data["title"] == "肉眼的血尿"


def test_db_custom_rule_title_not_overwritten_to_canonical_id_slug(monkeypatch):
    """
    canonical_id 存在但不在內建 catalogue（模擬 DB 管理員自訂規則,其
    title 已由 red_flag_detector 依自身 display_title_by_lang 正確解析）
    → 這裡不可再覆寫,否則會把好端端的 title 換成醜陋的 snake_case slug。
    """
    alert = make_alert(
        severity="high",
        canonical_id="acute_epididymitis_suspected",
        title="Suspected Acute Epididymitis",  # 假設 DB 自訂規則已正確解析英文
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("en-US"),
        detector=StubDetector(alerts=[alert]),
    )

    persisted_data = res.alert_create.call_args.args[1]
    assert persisted_data["title"] == "Suspected Acute Epididymitis"
    assert persisted_data["title"] != "acute_epididymitis_suspected"


def test_new_llm_flag_without_canonical_catalogue_entry_keeps_original_title(
    monkeypatch,
):
    """canonical_id 為 None（純 title-based 舊格式/LLM 自創新型紅旗）→ 沿用原 title。"""
    alert = make_alert(
        severity="high",
        canonical_id=None,
        title="急性副睪炎可能",
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("en-US"),
        detector=StubDetector(alerts=[alert]),
    )

    persisted_data = res.alert_create.call_args.args[1]
    assert persisted_data["title"] == "急性副睪炎可能"


def test_title_localization_does_not_break_cross_language_dedup(monkeypatch):
    """A5 不變式：title 覆寫邏輯不可影響 canonical_id 去重身份。
    第 1 輪 en-US 場次的 high 紅旗持久化後，第 2 輪同 canonical_id 應被抑制。"""
    redis = FakeRedis()
    session_context = _session_context("en-US")
    history: list = []
    alert = make_alert(
        severity="high", canonical_id="gross_hematuria", title="肉眼血尿"
    )

    res1 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[dict(alert)]),
    )
    assert res1.alert_create.call_count == 1
    assert redis.hashes[_KEY]["gross_hematuria"] == "high"

    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[dict(alert)]),
    )
    assert res2.alert_create.call_count == 0  # 第 2 輪被抑制（去重不受 title 覆寫影響）
