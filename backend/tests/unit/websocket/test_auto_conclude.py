"""問診自動結束決策（_should_auto_conclude / _coerce_hpi_pct）單元測試。

鎖定醫療安全不變式（對抗驗證指出的關鍵情境）：
- 軟門檻：HPI 完整度達標 + 病患回合達最低 → 收尾。
- 硬上限 backstop：回合數達上限即收尾，且「不依賴」Supervisor（降級 fallback 仍會結束）。
- fallback 佔位指導（Supervisor 逾時）不可被當成 HPI 達標。
- hpi_completion_percentage 為字串（"85"）仍能正確觸發軟門檻（否則核心功能默默失效）。
- 總開關關閉時，軟/硬兩條路徑都不結束。
"""

from app.core.config import Settings
from app.websocket.conversation_handler import (
    _coerce_hpi_pct,
    _should_auto_conclude,
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
