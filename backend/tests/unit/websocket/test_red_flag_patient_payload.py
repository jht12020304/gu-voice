"""病患端紅旗 payload 的兩條鐵律：不給醫師向臨床指令、不對病患說謊。

BLOCKER #3（結構性過濾）
------------------------
送往病患 WS 的 `red_flag_alert` payload **不可含** `description` /
`suggestedActions`。這兩欄是 LLM 自由生成的醫師向內容——真跑 `torsion_critical_zh`
實測 `suggestedActions[4]` ＝「立即安排急診評估」，`hematuria_3b_en` 的
`description` ＝「肉眼可見血尿,需進一步檢查排除惡性腫瘤」——對已在候診區的病患
既看不懂又製造恐慌，且違反 kiosk 措辭鐵律。

修在後端出口而不是前端 render 層：前端有兩份實作（React + Flutter），render 層
過濾漏一份就破功，而且 payload 仍會落進 store / model。也不用禁字黑名單——LLM
換個講法就繞過去了。**結構性地不送**才是可靠的防線。醫師端（dashboard 廣播）
與 DB（`red_flag_alerts.description` / `.suggested_actions`）保留完整內容。

BLOCKER #2（不說謊）
--------------------
病患端提示宣稱「已通知現場醫護人員」，但 high/medium 紅旗在 `doctor_id` 為 NULL
的 kiosk 場次以前**一則通知都不建**（真跑 `hematuria_3b_en` 發了 high 紅旗，
notifications 表 0 筆）。修法採 (a)＋(b) 兩段：

  (a) 讓它變成真的：每一則持久化成功的紅旗都建 RED_FLAG 通知；場次未指派醫師
      （kiosk 常態）就 fan-out 給所有在職醫師，沿用 critical 中止路徑已採用的
      「未指派 → 全體在職醫師」模型。
  (b) 文案由 ground truth 決定：`_notify_doctors_red_flag` 實際建立的筆數 > 0
      才用「已通知」版本；建了 0 筆（查無在職醫師 / 寫入失敗）就退到只陳述
      「已為您標記」的版本。這樣「已通知」在結構上不可能在沒有通知時出現。

`_finalize_red_flag_abort` 的 CAS
---------------------------------
覆核指出它忽略 `_update_session_status` 的回傳值，與同批的 `_finalize_idle_timeout`
不一致 → 三條 abort 路徑競態時 dashboard 重複廣播。這裡一併釘住。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.websocket.conversation_handler as ch
from app.models.enums import NotificationType
from app.utils.i18n_messages import MESSAGES, get_message
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    StubDB,
    StubDetector,
    make_alert,
    make_settings,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID
DOC_A = uuid.UUID("22222222-2222-4222-8222-222222222222")
DOC_B = uuid.UUID("33333333-3333-4333-8333-333333333333")

# 真跑實測會出現在 LLM 產出的醫師向字串（不可外洩到病患端）
LEAKY_DESCRIPTION = "可能為睪丸扭轉,需要在 6 小時內處理以避免壞死"
LEAKY_ACTIONS = [
    "進行睪丸超音波檢查",
    "立即通知泌尿科醫師",
    "立即安排急診評估",
]


def _ctx(language: str = "zh-TW", doctor_id: Any = None) -> dict[str, Any]:
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "頻尿",
        "chief_complaint_display": "頻尿",
        "patient_info": {"name": "測試病患"},
        "language": language,
        "doctor_id": doctor_id,
    }


def _leaky_alert(severity: str = "high") -> dict[str, Any]:
    alert = make_alert(severity=severity, description=LEAKY_DESCRIPTION)
    alert["suggested_actions"] = list(LEAKY_ACTIONS)
    return alert


def _patient_alerts(cap) -> list[dict[str, Any]]:
    return [m["payload"] for m in cap.messages_of_type("red_flag_alert")]


def _dashboard_alerts(cap) -> list[dict[str, Any]]:
    return [
        m["payload"] for m in cap.dashboard_messages if m.get("type") == "new_red_flag"
    ]


# ══ BLOCKER #3：病患端 payload 結構性過濾 ═════════════════════
@pytest.mark.parametrize("severity", ["critical", "high", "medium"])
def test_patient_payload_omits_doctor_facing_fields(monkeypatch, severity):
    """任一嚴重度：病患 payload 都不可帶 description / suggestedActions。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert(severity)]),
    )
    payloads = _patient_alerts(res.cap)
    assert payloads, f"severity={severity} 沒送出 red_flag_alert"
    for payload in payloads:
        assert "description" not in payload, f"病患 payload 仍帶 description：{payload}"
        assert "suggestedActions" not in payload, (
            f"病患 payload 仍帶 suggestedActions：{payload}"
        )
        # 欄位名換掉也不算修好——檢查真正的字串內容有沒有外洩到任何欄位。
        blob = repr(payload)
        assert LEAKY_DESCRIPTION not in blob, f"description 原文外洩：{payload}"
        for action in LEAKY_ACTIONS:
            assert action not in blob, f"suggestedActions 原文外洩（{action}）：{payload}"


def test_patient_payload_keeps_exactly_the_patient_facing_fields(monkeypatch):
    """契約鎖定：日後有人補欄位進來時這條會失敗，逼他先想清楚病患該不該看到。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
    )
    payload = _patient_alerts(res.cap)[0]
    assert set(payload) == {"alertId", "severity", "title", "patientNotice"}
    assert payload["title"] == "肉眼血尿"
    assert payload["severity"] == "high"


def test_doctor_facing_channels_keep_full_content(monkeypatch):
    """collateral 檢查：醫師端與 DB 拿到的資訊不可因此變少。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
    )
    # dashboard 紅旗卡片仍有 description
    dash = _dashboard_alerts(res.cap)
    assert dash, "dashboard 沒收到 new_red_flag"
    assert dash[0]["description"] == LEAKY_DESCRIPTION
    assert dash[0]["severity"] == "high"
    assert dash[0]["sessionId"] == SID
    # DB 仍寫入完整 description / suggested_actions
    alert_payload = res.alert_create.call_args.args[1]
    assert alert_payload["description"] == LEAKY_DESCRIPTION
    assert alert_payload["suggested_actions"] == LEAKY_ACTIONS


def test_patient_notice_has_no_urgent_care_wording(monkeypatch):
    """kiosk 措辭鐵律：病患已在現場，提示不可含「立即急診 / 盡速就醫」類指引。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("critical")]),
        doctor_ids=[DOC_A],
    )
    notice = _patient_alerts(res.cap)[0]["patientNotice"]
    for banned in ("盡速就醫", "儘速就醫", "立即就醫", "立即安排急診", "前往急診", "趕快去醫院"):
        assert banned not in notice, f"病患提示含催就醫措辭「{banned}」：{notice}"
    assert "稍候" in notice and "現場" in notice


NEW_PATIENT_KEYS = [
    "ws.red_flag_patient_notice_notified",
    "ws.red_flag_patient_notice_flagged",
    "ws.session_terminated_aborted_notice_unnotified",
]

# 與 scripts/e2e_realopenai/driver.py 的 BANNED_PATIENT_FACING_PHRASES 對齊：
# 真跑會掃 red_flag_alert payload 的每一個字串葉節點，patientNotice 也在內。
# 在 unit test 就擋掉，不要等到跑真 OpenAI 才發現。
E2E_BANNED_PATIENT_FACING_PHRASES = [
    "立即急診", "立刻急診", "馬上急診", "儘快急診", "盡快急診",
    "急診評估", "掛急診", "前往急診", "去急診", "送急診", "急診室",
    "盡速就醫", "儘速就醫", "盡快就醫", "儘快就醫", "立即就醫", "立刻就醫",
    "馬上就醫", "趕快就醫", "趕緊就醫", "趕快去醫院", "立即前往醫院", "盡速前往",
    "go to the emergency", "emergency room", "emergency department",
    "seek immediate medical", "seek urgent medical", "seek emergency",
    "immediate medical attention", "urgent care", "call 911", "go to the er",
]


@pytest.mark.parametrize("locale", ["zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"])
@pytest.mark.parametrize("key", NEW_PATIENT_KEYS)
def test_new_patient_keys_obey_kiosk_wording(key, locale):
    """5 語全掃：新加的病患面字串不可含催就醫／急診措辭。"""
    value = MESSAGES[key][locale].lower()
    for phrase in E2E_BANNED_PATIENT_FACING_PHRASES:
        assert phrase.lower() not in value, (
            f"{key} 的 {locale} 含催就醫措辭「{phrase}」：{MESSAGES[key][locale]}"
        )


@pytest.mark.parametrize("locale", ["zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"])
@pytest.mark.parametrize("key", NEW_PATIENT_KEYS)
def test_new_patient_keys_have_all_five_locales(key, locale):
    """缺譯不會 raise，只會靜靜退回中文寫給日/韓/越病患看——5 語都要有。"""
    assert MESSAGES[key].get(locale), f"{key} 缺 {locale} 翻譯"
    if locale != "zh-TW":
        assert MESSAGES[key][locale] != MESSAGES[key]["zh-TW"], (
            f"{key} 的 {locale} 直接複製了中文"
        )


def test_patient_notice_follows_session_language(monkeypatch):
    res = run_text_turn(
        monkeypatch,
        language="en-US",
        session_context=_ctx(language="en-US"),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[DOC_A],
    )
    notice = _patient_alerts(res.cap)[0]["patientNotice"]
    assert notice == get_message("ws.red_flag_patient_notice_notified", "en-US")


# ══ BLOCKER #2：文案與「有沒有真的建通知」一致 ═══════════════
def _red_flag_notifications(spy) -> list[Any]:
    return [
        c for c in spy.call_args_list if c.kwargs.get("type") is NotificationType.RED_FLAG
    ]


def test_unassigned_session_fans_out_and_claims_notified(monkeypatch):
    """kiosk 場次 doctor_id=NULL：high 紅旗也要建通知，然後才可以說「已通知」。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[DOC_A, DOC_B],
    )
    calls = _red_flag_notifications(res.notif_create)
    assert [c.kwargs["user_id"] for c in calls] == [DOC_A, DOC_B], (
        "high 紅旗在未指派場次沒有 fan-out 給在職醫師"
    )
    assert all(c.kwargs["data"]["unassigned_fanout"] is True for c in calls)
    assert all(c.kwargs["data"]["session_id"] == SID for c in calls)
    notice = _patient_alerts(res.cap)[0]["patientNotice"]
    assert notice == get_message("ws.red_flag_patient_notice_notified", "zh-TW")


def test_no_active_doctor_means_no_notified_claim(monkeypatch):
    """一個在職醫師都沒有 → 0 筆通知 → 絕不可對病患說「已通知現場醫護人員」。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[],
    )
    assert _red_flag_notifications(res.notif_create) == []
    notice = _patient_alerts(res.cap)[0]["patientNotice"]
    assert notice == get_message("ws.red_flag_patient_notice_flagged", "zh-TW")
    assert "通知現場醫護人員" not in notice


def test_notification_write_failure_downgrades_the_claim(monkeypatch):
    """通知寫入炸掉時同樣不可宣稱已通知（而且不可害警示本身送不出去）。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[DOC_A],
        notification_create=AsyncMock(side_effect=RuntimeError("notifications down")),
    )
    payloads = _patient_alerts(res.cap)
    assert payloads, "通知失敗不可讓紅旗警示本身消失（病安優先）"
    assert payloads[0]["patientNotice"] == get_message(
        "ws.red_flag_patient_notice_flagged", "zh-TW"
    )


def test_notification_suppressed_by_preference_downgrades_the_claim(monkeypatch):
    """NotificationService.create 回 None（被抑制）＝沒建 → 不可宣稱已通知。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("medium")]),
        doctor_ids=[DOC_A],
        notification_create=AsyncMock(return_value=None),
    )
    assert _patient_alerts(res.cap)[0]["patientNotice"] == get_message(
        "ws.red_flag_patient_notice_flagged", "zh-TW"
    )


def test_assigned_session_does_not_double_notify(monkeypatch):
    """已指派醫師的場次：AlertService.create 已建過，這裡不可再建第二則。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(doctor_id=str(DOC_A)),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[DOC_A, DOC_B],
    )
    assert _red_flag_notifications(res.notif_create) == []
    assert _patient_alerts(res.cap)[0]["patientNotice"] == get_message(
        "ws.red_flag_patient_notice_notified", "zh-TW"
    )


def test_alert_persist_failure_sends_no_alert_and_no_notification(monkeypatch):
    """警示存不進 DB 時：不偽造 alertId、也不可對病患宣稱通知了什麼。"""
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(alerts=[_leaky_alert("high")]),
        doctor_ids=[DOC_A],
        alert_create_side_effect=RuntimeError("db down"),
    )
    assert _patient_alerts(res.cap) == []
    assert _red_flag_notifications(res.notif_create) == []


def test_terminated_notice_claims_notified_only_after_real_notification(monkeypatch):
    """critical abort 後的「已通知」版本，只在真的建過通知的場次出現。"""
    ctx = _ctx()
    history: list[dict[str, Any]] = []
    redis = FakeRedis()
    run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=ctx,
        conversation_history=history,
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
                )
            ]
        ),
        doctor_ids=[DOC_A],
    )
    assert ctx["_terminated"] == "aborted_red_flag"
    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=ctx,
        conversation_history=history,
        detector=StubDetector(alerts=[]),
        doctor_ids=[DOC_A],
    )
    assert res2.cap.chunk_texts() == [
        get_message("ws.session_terminated_aborted_notice", "zh-TW")
    ]


def test_critical_abort_does_not_notify_the_same_flag_twice(monkeypatch):
    """critical 走兩條會通知的路徑（警示 fan-out + 中止收尾），不可各發一次。"""
    update_status = AsyncMock(return_value=True)
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
                )
            ]
        ),
        doctor_ids=[DOC_A],
        update_status=update_status,
    )
    # 警示路徑已 fan-out 一次
    assert len(_red_flag_notifications(res.notif_create)) == 1
    # 中止收尾那次帶 notify_doctors=False（同一則紅旗、同一批醫師）
    abort = [c for c in update_status.call_args_list if c.args[3] == "aborted_red_flag"]
    assert abort, "critical 沒有走 abort 收尾"
    assert abort[0].kwargs["notify_doctors"] is False


# ══ `_finalize_red_flag_abort` 的 CAS 回傳值 ═══════════════════
def _run_abort(monkeypatch, *, transitioned: bool, terminated: str | None = None):
    """驅動 `_finalize_red_flag_abort`（走 run_text_turn 的 critical 情境，
    用 update_status 替身控制 CAS 回傳值）。"""
    ctx = _ctx()
    if terminated:
        ctx["_terminated"] = terminated
    return run_text_turn(
        monkeypatch,
        session_context=ctx,
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
                )
            ]
        ),
        doctor_ids=[DOC_A],
        update_status=AsyncMock(return_value=transitioned),
    )


def test_cas_miss_skips_dashboard_broadcast(monkeypatch):
    """CAS 回 False（別條路徑已把場次轉成終態）→ 不重複廣播 dashboard。"""
    res = _run_abort(monkeypatch, transitioned=False)
    status_changed = [
        c
        for c in res.cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert status_changed == [], "CAS 未命中仍重複廣播 session_status_changed"


def test_cas_miss_still_tells_the_patient_and_still_queues_soap(monkeypatch):
    """CAS 回 False 也可能是 DB 例外（場次仍 in_progress）：
    病患不可被留在對話頁，SOAP 也不可漏派（派送本身冪等）。"""
    res = _run_abort(monkeypatch, transitioned=False)
    abort_events = [
        c for c in res.cap.localized_calls if c["code"] == "events.session.aborted_red_flag"
    ]
    assert len(abort_events) == 1
    assert abort_events[0]["extra"].get("status") == "aborted_red_flag"
    assert res.soap_spy.called


def test_cas_hit_still_broadcasts_everything(monkeypatch):
    """對照組：CAS 命中時原本的五件事一件都不能少。"""
    res = _run_abort(monkeypatch, transitioned=True)
    assert [
        c
        for c in res.cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert res.soap_spy.called
    assert res.session_context["_terminated"] == "aborted_red_flag"


def test_two_abort_paths_racing_finalize_only_once(monkeypatch):
    """真正會撞在一起的兩條路徑：硬上限 inline drain 與背景 `_drain_late_red_flags`
    都在 await **同一個** `red_flag_task`，遲到的 critical 一解析出來兩邊都會呼叫
    `_finalize_red_flag_abort`。修復前病患端會收到兩次 abort session_status、
    dashboard 兩次 session_status_changed、SOAP 兩次派送。"""
    from tests.unit.websocket.test_red_flag_abort_finalization import run_turn_draining

    res = run_turn_draining(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            HARD_CAP_DRAIN_AWAIT_SECONDS=0.5,
            MAX_HARD_CAP_DRAIN_DEFERS=2,
        ),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
                )
            ],
            delay=0.05,
        ),
    )
    abort_events = [
        c for c in res.cap.localized_calls if c["code"] == "events.session.aborted_red_flag"
    ]
    assert len(abort_events) == 1, (
        f"病患端收到 {len(abort_events)} 次 abort session_status（應為 1）"
    )
    dash = [
        c
        for c in res.cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert len(dash) == 1, f"dashboard 收到 {len(dash)} 次 session_status_changed（應為 1）"
    assert res.soap_spy.call_count == 1, (
        f"SOAP 派送了 {res.soap_spy.call_count} 次（應為 1）"
    )
    # 收尾本身仍要成立（不是靠「兩條都不做」達成單次）
    assert res.session_context["_terminated"] == "aborted_red_flag"


# ══ 不回歸：`_update_session_status` 的 notify_doctors 開關 ══════
def test_notify_doctors_false_skips_abort_notification(monkeypatch):
    from app.services.notification_service import NotificationService

    spy = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(NotificationService, "create", spy)
    db = StubDB(
        rowcount=1,
        returning_row=SimpleNamespace(language="zh-TW", doctor_id=DOC_A, patient_id=None),
    )
    ok = asyncio.run(
        ch._update_session_status(
            db,
            FakeRedis(),
            SID,
            "aborted_red_flag",
            "in_progress",
            red_flag_reason="睪丸扭轉",
            notify_doctors=False,
        )
    )
    assert ok is True
    assert _red_flag_notifications(spy) == []


def test_notify_doctors_defaults_to_true(monkeypatch):
    """預設值不可變——其他呼叫端（REST/舊測試）沒傳這個參數。"""
    from app.services.notification_service import NotificationService

    spy = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(NotificationService, "create", spy)
    db = StubDB(
        rowcount=1,
        returning_row=SimpleNamespace(language="zh-TW", doctor_id=DOC_A, patient_id=None),
    )
    asyncio.run(
        ch._update_session_status(
            db, FakeRedis(), SID, "aborted_red_flag", "in_progress", red_flag_reason="x"
        )
    )
    assert len(_red_flag_notifications(spy)) == 1


def test_settings_import_is_used_to_silence_linters():
    """make_settings 供其他測試共用，這裡只確保 import 不是死的。"""
    assert make_settings().MAX_PATIENT_TURNS_HARD_CAP == 10
