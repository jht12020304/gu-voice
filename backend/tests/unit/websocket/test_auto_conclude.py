"""問診自動結束決策（_should_auto_conclude / _coerce_hpi_pct）單元測試。

鎖定醫療安全不變式（對抗驗證指出的關鍵情境）：
- 軟門檻：HPI 完整度達標 + 病患回合達最低 → 收尾。
- 硬上限 backstop：回合數達上限即收尾，且「不依賴」Supervisor（降級 fallback 仍會結束）。
- fallback 佔位指導（Supervisor 逾時）不可被當成 HPI 達標。
- hpi_completion_percentage 為字串（"85"）仍能正確觸發軟門檻（否則核心功能默默失效）。
- 總開關關閉時，軟/硬兩條路徑都不結束。

A2/A3 [D1]（e2e_realopenai_audit_2026-06-28 §三）追加：
- `_should_conclude_now` 純函式閘門矩陣：硬上限不被 soft_defer（本輪 critical/high
  紅旗或空回應 fallback）否決；drain_unresolved 一律延後。
- `_hard_cap_reached`：獨立於軟門檻的硬上限旗標，受總開關控制。
- 硬上限 + 遲到紅旗的有界 inline 解析（late-critical 先 abort、benign 照收尾、
  偵測器真卡死 MAX_HARD_CAP_DRAIN_DEFERS 輪後強制收尾 — 絕對保命線）。
"""

import pytest

from app.core.config import Settings
from app.websocket.conversation_handler import (
    _coerce_hpi_pct,
    _hard_cap_reached,
    _should_auto_conclude,
    _should_conclude_now,
)
from tests.unit.websocket.conftest import (
    StubDetector,
    make_alert,
    make_settings,
    run_text_turn,
)


def _settings(**overrides) -> Settings:
    base = dict(
        HPI_COMPLETION_TERMINATION_ENABLED=True,
        HPI_COMPLETION_TERMINATION_THRESHOLD=85,
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=4,
        MAX_PATIENT_TURNS_HARD_CAP=15,
    )
    base.update(overrides)
    s = Settings.model_construct()
    for k, v in base.items():
        object.__setattr__(s, k, v)
    return s


# ── _coerce_hpi_pct ──────────────────────────────────────────
def test_coerce_int_and_float():
    assert _coerce_hpi_pct(85) == 85.0
    assert _coerce_hpi_pct(85.5) == 85.5


def test_coerce_numeric_string():
    assert _coerce_hpi_pct("85") == 85.0
    assert _coerce_hpi_pct(" 90 ") == 90.0


def test_coerce_rejects_bool_and_garbage():
    # bool 是 int 子類，必須排除，否則 True→1 會誤觸
    assert _coerce_hpi_pct(True) is None
    assert _coerce_hpi_pct(False) is None
    assert _coerce_hpi_pct("high") is None
    assert _coerce_hpi_pct(None) is None
    assert _coerce_hpi_pct({"x": 1}) is None


# ── 軟門檻 ────────────────────────────────────────────────────
def test_soft_trigger_fires_at_threshold_and_min_turns():
    g = {"hpi_completion_percentage": 85}
    assert _should_auto_conclude(g, patient_turns=4, settings=_settings()) is True


def test_soft_trigger_blocked_below_min_turns():
    g = {"hpi_completion_percentage": 95}
    assert _should_auto_conclude(g, patient_turns=3, settings=_settings()) is False


def test_soft_trigger_blocked_below_threshold():
    g = {"hpi_completion_percentage": 84}
    assert _should_auto_conclude(g, patient_turns=10, settings=_settings()) is False


def test_soft_trigger_with_string_percentage():
    # 對抗驗證 finding #5：字串百分比也要能觸發軟門檻
    g = {"hpi_completion_percentage": "85"}
    assert _should_auto_conclude(g, patient_turns=6, settings=_settings()) is True


# ── 硬上限 backstop（不依賴 Supervisor）──────────────────────
def test_hard_cap_fires_even_without_guidance():
    assert _should_auto_conclude(None, patient_turns=15, settings=_settings()) is True


def test_hard_cap_fires_even_when_supervisor_degraded_fallback():
    # 「15 題等不到結果」的真正修補：Supervisor 逾時寫 fallback、hpi=0，
    # 軟門檻永不觸發，但硬上限仍保證結束。
    g = {"hpi_completion_percentage": 0, "fallback": True}
    assert _should_auto_conclude(g, patient_turns=15, settings=_settings()) is True


def test_below_hard_cap_with_fallback_does_not_end():
    g = {"hpi_completion_percentage": 99, "fallback": True}
    # fallback 指導的 hpi 不可信 → 軟門檻不採計；回合未達硬上限 → 不結束
    assert _should_auto_conclude(g, patient_turns=10, settings=_settings()) is False


# ── 總開關 ────────────────────────────────────────────────────
def test_kill_switch_disables_both_paths():
    s = _settings(HPI_COMPLETION_TERMINATION_ENABLED=False)
    assert _should_auto_conclude({"hpi_completion_percentage": 99}, 20, s) is False
    assert _should_auto_conclude(None, 99, s) is False


# ── 生產預設值（鎖定「平衡 8-10 題」，防意外 revert 回舊的 85/4/15）──────
def test_production_defaults_are_balanced_8_to_10():
    """上方測試都用 _settings() 覆寫值，不會抓到 config.py 預設被改回舊值。
    這裡直接讀 Settings 宣告的預設，鎖定 2026-06-29 調整後的 80/5/10。"""
    fields = Settings.model_fields
    assert fields["HPI_COMPLETION_TERMINATION_THRESHOLD"].default == 80
    assert fields["MIN_PATIENT_TURNS_BEFORE_AUTO_END"].default == 5
    assert fields["MAX_PATIENT_TURNS_HARD_CAP"].default == 10
    assert fields["HPI_COMPLETION_TERMINATION_ENABLED"].default is True


def test_a_group_kill_switch_defaults():
    """A 群新 kill-switch 預設值（audit doc §三，無 migration）。"""
    fields = Settings.model_fields
    assert fields["LLM_EMPTY_RESPONSE_RETRY"].default is True
    assert fields["HARD_CAP_DRAIN_AWAIT_SECONDS"].default == 5.0
    assert fields["MAX_HARD_CAP_DRAIN_DEFERS"].default == 2


# ── A2 [D1]：_hard_cap_reached（獨立硬上限旗標） ─────────────────
def test_hard_cap_reached_true_at_cap():
    assert _hard_cap_reached(15, _settings()) is True
    assert _hard_cap_reached(16, _settings()) is True


def test_hard_cap_reached_false_below_cap():
    assert _hard_cap_reached(14, _settings()) is False


def test_hard_cap_reached_respects_kill_switch():
    s = _settings(HPI_COMPLETION_TERMINATION_ENABLED=False)
    assert _hard_cap_reached(99, s) is False


# ── A2 [D1+D5]：_should_conclude_now 閘門矩陣（純函式） ──────────
@pytest.mark.parametrize(
    "should_conclude, hard_cap, soft_defer, drain_unresolved, expected",
    [
        # should_conclude=False → 一律不收尾（含 hard_cap=True：總開關語意由呼叫端保證）
        (False, False, False, False, False),
        (False, True, False, False, False),
        (False, True, True, True, False),
        # 軟門檻乾淨收尾
        (True, False, False, False, True),
        # 軟門檻被 soft_defer 否決（現行行為保留）
        (True, False, True, False, False),
        # drain 否決軟門檻
        (True, False, False, True, False),
        # D1 修復核心：硬上限不被 soft_defer 否決
        (True, True, True, False, True),
        (True, True, False, False, True),
        # backstop 前 drain 仍否決硬上限一輪（呼叫端先做有界解析）
        (True, True, False, True, False),
        (True, True, True, True, False),
    ],
)
def test_should_conclude_now_matrix(
    should_conclude, hard_cap, soft_defer, drain_unresolved, expected
):
    assert (
        _should_conclude_now(should_conclude, hard_cap, soft_defer, drain_unresolved)
        is expected
    )


# ── A3 [D1]：硬上限 + 遲到紅旗的有界 inline 解析（harness） ──────
def _drain_settings():
    """單輪即達硬上限、inline 解析上限 0.2s（配 harness 的 gate 等待 0.01s）。"""
    return make_settings(
        MAX_PATIENT_TURNS_HARD_CAP=1,
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
        HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
        MAX_HARD_CAP_DRAIN_DEFERS=2,
    )


def test_hard_cap_late_critical_inline_abort(monkeypatch):
    """偵測 0.05s 後回 critical（> gate 0.01s、< inline 0.2s）→ inline 解析
    先 aborted_red_flag（帶 red_flag_reason）再結束；絕不 completed。"""
    res = run_text_turn(
        monkeypatch,
        settings=_drain_settings(),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical",
                    canonical_id="testicular_torsion",
                    title="睪丸扭轉",
                )
            ],
            delay=0.05,
        ),
    )
    assert res.result is True  # 呼叫端應結束主迴圈
    statuses = [c.args[3] for c in res.update_status.call_args_list]
    assert "aborted_red_flag" in statuses
    assert "completed" not in statuses
    abort_calls = [
        c for c in res.update_status.call_args_list if c.args[3] == "aborted_red_flag"
    ]
    assert any(c.kwargs.get("red_flag_reason") == "睪丸扭轉" for c in abort_calls)
    # 紅旗中止場次仍要出 SOAP（供醫師審閱；冪等由 generator 內部保護）
    assert res.soap_spy.called
    # 病患端收到 aborted_red_flag 通知
    assert any(
        c["code"] == "events.session.aborted_red_flag" for c in res.cap.localized_calls
    )


def test_hard_cap_late_benign_resolves_then_concludes(monkeypatch):
    """偵測 0.05s 後回 medium（非 critical）→ inline 解析後照常硬上限收尾 completed。"""
    res = run_text_turn(
        monkeypatch,
        settings=_drain_settings(),
        detector=StubDetector(
            alerts=[make_alert(severity="medium", canonical_id="mild_lut_symptom")],
            delay=0.05,
        ),
    )
    assert res.result is True
    statuses = [c.args[3] for c in res.update_status.call_args_list]
    assert "completed" in statuses
    assert res.soap_spy.called


def test_hard_cap_drain_stuck_defers_then_forces_conclude(monkeypatch):
    """偵測器真卡死（永久 pending）：第 1、2 輪延後（defers=1、2），
    第 3 輪（defers=3 > MAX=2）走絕對保命線強制收尾 completed（E7 決策 2）。"""
    settings = _drain_settings()
    session_context = {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }
    history: list = []

    for expected_defers in (1, 2):
        res = run_text_turn(
            monkeypatch,
            settings=settings,
            session_context=session_context,
            conversation_history=history,
            detector=StubDetector(hang=True),
        )
        assert res.result is False
        statuses = [c.args[3] for c in res.update_status.call_args_list]
        assert "completed" not in statuses
        assert session_context["_hard_cap_drain_defers"] == expected_defers

    res = run_text_turn(
        monkeypatch,
        settings=settings,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(hang=True),
    )
    assert res.result is True
    statuses = [c.args[3] for c in res.update_status.call_args_list]
    assert "completed" in statuses
    assert res.soap_spy.called
