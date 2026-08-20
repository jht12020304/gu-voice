"""D-2：§3b 回合配額（動態硬上限 + 軟門檻下限）必須吃 **intake 過濾後**的 K。

## 缺陷

`conclusion_policy.session_risk_factor_count` 原本直接回
`shared.count_critical_risk_factors_for_complaint`（只看主訴的**未過濾** K），但
prompt 端注入的必問清單早已被 `llm_conversation` 的 intake 三態判定過濾過。結果：

    血尿場 K=3；病患在 intake 已填 warfarin（抗凝血 → 禁問）＋叔父腎盂癌
    （泌尿癌家族史 → 禁問）→ 實際只剩「吸菸史」1 題要口頭問到。
    但配額仍照 K=3 算：軟門檻下限 = 10+3-1 = 12、硬上限 = 10+3+2 = 15
    → 病患被綁滿 12～15 輪，其中 6～7 輪沒有任何 §3b 問題要問。

## 方向護欄（本檔最重要的一半）

過濾後 K **只能 ≤ 原 K**。K 變大＝配額被抬高＝病患被綁更多輪，是這個修復絕不能
引入的反方向，所以每個「下降」案例都配一個「不得上升」的對照斷言。
`K=0 → soft_min 回 base 下限」的既有語意也要原樣保住。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.pipelines.llm_conversation import INTAKE_SOURCE_KEY
from app.pipelines.prompts.shared import count_critical_risk_factors_for_complaint
from app.websocket.conversation_handler import (
    _effective_hard_cap,
    _session_risk_factor_count,
    _should_auto_conclude,
)


def _settings(**overrides) -> Settings:
    base = dict(
        HPI_COMPLETION_TERMINATION_ENABLED=True,
        HPI_COMPLETION_TERMINATION_THRESHOLD=80,
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=5,
        MAX_PATIENT_TURNS_HARD_CAP=10,
        RISK_FACTOR_HARD_CAP_BUFFER=2,
    )
    base.update(overrides)
    s = Settings.model_construct()
    for k, v in base.items():
        object.__setattr__(s, k, v)
    return s


def _ctx(chief_complaint: str, **intake: str | None) -> dict:
    """組一份帶本次 intake 來源標記的 session_context。"""
    fields = {
        "medical_history": None,
        "medications": None,
        "allergies": None,
        "family_history": None,
    }
    fields.update(intake)
    flat = {k: v for k, v in fields.items() if v}
    return {
        "chief_complaint": chief_complaint,
        "patient_info": {
            "name": "測試病患",
            "age": 68,
            "gender": "male",
            **flat,
            INTAKE_SOURCE_KEY: fields,
        },
    }


# ── K 的過濾前後對照 ────────────────────────────────────
def test_raw_k_is_three_for_hematuria_without_intake() -> None:
    """基準線：intake 全空 → 三項都必問，K 維持 3（既有行為不變）。"""
    assert count_critical_risk_factors_for_complaint("血尿") == 3
    assert _session_risk_factor_count(_ctx("血尿")) == 3


def test_k_drops_when_intake_covers_two_of_three() -> None:
    """抗凝血 + 泌尿癌家族史已由 intake 涵蓋 → 只剩吸菸史，K = 1。"""
    ctx = _ctx("血尿", medications="warfarin 3mg", family_history="叔父：腎盂癌")
    assert _session_risk_factor_count(ctx) == 1


def test_k_drops_to_zero_when_intake_covers_everything_askable() -> None:
    """ED 的三項裡，心血管與糖尿病都能由病史涵蓋；吸菸史沒有 intake 欄位。

    ⚠️ 吸菸史／血脂異常**永遠**沒有對應欄位（intake 表單沒這兩欄），所以 ED 場的
    過濾後 K 最低只會是 1，不可能歸零——這條斷言同時釘住「詞庫改動不得意外把
    吸菸史關掉」。
    """
    ctx = _ctx(
        "勃起功能障礙",
        medical_history="高血壓、冠狀動脈疾病、心肌梗塞、中風、第二型糖尿病",
    )
    assert _session_risk_factor_count(ctx) == 1


def test_explicit_none_intake_also_lowers_k() -> None:
    """病患明確填「無」＝已問到、答案為否 → 同樣移出必問清單。"""
    ctx = _ctx("血尿", medications="無", family_history="無")
    assert _session_risk_factor_count(ctx) == 1


# ── 方向護欄：只能降、不能升 ───────────────────────────────
@pytest.mark.parametrize(
    "ctx",
    [
        pytest.param(_ctx("血尿"), id="intake-empty"),
        pytest.param(_ctx("血尿", medications="amlodipine 5mg"), id="not-covering"),
        pytest.param(_ctx("血尿", medications="warfarin"), id="one-covered"),
        pytest.param(
            _ctx("血尿", medications="warfarin", family_history="叔父：腎盂癌"),
            id="two-covered",
        ),
        pytest.param(_ctx("勃起功能障礙", medical_history="糖尿病"), id="ed-partial"),
    ],
)
def test_filtered_k_never_exceeds_raw_k(ctx: dict) -> None:
    raw = count_critical_risk_factors_for_complaint(ctx["chief_complaint"])
    assert _session_risk_factor_count(ctx) <= raw


def test_non_covering_intake_keeps_full_k() -> None:
    """用藥欄只有 amlodipine → 抗凝血仍未知 → K 不下降（不變式 #23 的安全方向）。"""
    ctx = _ctx("血尿", medications="amlodipine 5mg")
    assert _session_risk_factor_count(ctx) == 3


def test_missing_patient_info_falls_back_to_raw_k() -> None:
    """session_context 沒有 patient_info（或型別壞掉）→ 退回未過濾 K（保守側）。"""
    assert _session_risk_factor_count({"chief_complaint": "血尿"}) == 3
    assert _session_risk_factor_count(
        {"chief_complaint": "血尿", "patient_info": None}
    ) == 3
    assert _session_risk_factor_count(
        {"chief_complaint": "血尿", "patient_info": "not-a-dict"}
    ) == 3


def test_non_risk_complaint_still_zero() -> None:
    """非高風險主訴 K 恆為 0，intake 有沒有填都一樣（其他主訴行為完全不變）。"""
    assert _session_risk_factor_count(_ctx("頻尿", medications="warfarin")) == 0


# ── 配額真的跟著下降（雙向） ──────────────────────────────
def test_soft_min_drops_when_only_one_factor_left() -> None:
    """K=1 時軟門檻下限降到 base+1-1 = 10；未過濾的 K=3 會是 12。

    這就是病患被「多綁 2 輪」的那一段：HPI 已達 80%、第 10 輪就該收尾。
    """
    s = _settings()
    guidance = {"hpi_completion_percentage": 90, "missing_hpi": []}
    ctx = _ctx("血尿", medications="warfarin 3mg", family_history="叔父：腎盂癌")
    k = _session_risk_factor_count(ctx)
    assert k == 1

    assert _should_auto_conclude(guidance, 10, s, k) is True, (
        "K 已過濾成 1，第 10 輪就該讓軟門檻放行"
    )
    # 對照：沿用未過濾的 K=3 → 同一輪不放行（＝修復前的行為）
    assert _should_auto_conclude(guidance, 10, s, 3) is False
    # 邊界：K=1 時第 9 輪仍不放行（下限是 base=10，不是無下限）
    assert _should_auto_conclude(guidance, 9, s, k) is False


def test_hard_cap_drops_with_filtered_k() -> None:
    """硬上限同步下降：K=3 → 15；K=1 → 13；K=0 → base 10。"""
    s = _settings()
    assert _effective_hard_cap(s, 3) == 15
    assert _effective_hard_cap(s, 1) == 13
    assert _effective_hard_cap(s, 0) == 10


def test_k_zero_keeps_base_soft_min_semantics() -> None:
    """K=0 時軟門檻下限回 MIN_PATIENT_TURNS_BEFORE_AUTO_END（既有語意不得改）。"""
    s = _settings(MIN_PATIENT_TURNS_BEFORE_AUTO_END=5)
    guidance = {"hpi_completion_percentage": 90, "missing_hpi": []}
    assert _should_auto_conclude(guidance, 5, s, 0) is True
    assert _should_auto_conclude(guidance, 4, s, 0) is False


def test_full_k_still_binds_when_intake_covers_nothing() -> None:
    """反方向護欄：intake 沒涵蓋任何一項時，配額**不得**被這個修復放鬆。"""
    s = _settings()
    guidance = {"hpi_completion_percentage": 95, "missing_hpi": []}
    ctx = _ctx("血尿", medications="amlodipine 5mg")
    k = _session_risk_factor_count(ctx)
    assert k == 3
    assert _should_auto_conclude(guidance, 11, s, k) is False, (
        "三個風險因子都還沒問到就放行 → 回歸 §3b 的漏問缺陷"
    )
    assert _should_auto_conclude(guidance, 12, s, k) is True
