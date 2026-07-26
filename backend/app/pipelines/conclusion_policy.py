"""問診自動結束政策（純函式）。

原本內嵌在 websocket/conversation_handler.py（2900+ 行 god file）中，全部是
`(supervisor_guidance / settings / session_context) → bool/int` 的純函式，且由
tests/unit/websocket/test_auto_conclude.py 完整覆蓋。抽到此獨立模組降低 handler
體積、便於單獨演進；行為與簽名一字不變（handler 以 re-import 保持既有引用）。

§3b 高風險主訴風險因子必問的三機制（動態硬上限 + 軟門檻下限 + 收尾閘門）中，
「動態硬上限」與「軟門檻下限」的計算住在這裡；「極簡收尾 prompt」在 prompts。
"""

from typing import Any

from app.core.config import Settings
from app.pipelines.prompts.shared import count_critical_risk_factors_for_complaint


def coerce_hpi_pct(value: Any) -> float | None:
    """把 Supervisor 的 hpi_completion_percentage 強制轉成數值。

    LLM 走 json_object 時偶爾把百分比輸出成字串（"85"）；不轉型會讓軟門檻永遠不
    觸發、只剩硬上限收尾，等於默默廢掉自動結束的核心。bool 是 int 子類，需排除。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


def effective_hard_cap(settings: Settings, risk_factor_count: int = 0) -> int:
    """§3b：本場次的病患回合硬上限。

    base = MAX_PATIENT_TURNS_HARD_CAP。無關鍵風險因子（K=0）的一般主訴維持 base
    不變；有 K>0 風險因子的高風險主訴（血尿/PSA/ED）需容納 opening(1)+HPI 十欄(10)+
    K 個必問風險因子，故 effective = base + K + BUFFER。BUFFER 吸收 opening 與少量
    margin，確保 HPI 問完後仍有回合能問到風險因子（不再被 base=10 砍掉）。
    """
    base = getattr(settings, "MAX_PATIENT_TURNS_HARD_CAP", 10)
    if risk_factor_count <= 0:
        return base
    buffer = getattr(settings, "RISK_FACTOR_HARD_CAP_BUFFER", 2)
    return base + risk_factor_count + buffer


def hard_cap_reached(
    patient_turns: int, settings: Settings, risk_factor_count: int = 0
) -> bool:
    """A2 [D1]：硬上限是否已到（獨立於軟門檻的旗標；受總開關控制）。

    §3b：cap 對高風險主訴動態抬高（見 effective_hard_cap）。"""
    if not getattr(settings, "HPI_COMPLETION_TERMINATION_ENABLED", True):
        return False
    return patient_turns >= effective_hard_cap(settings, risk_factor_count)


def should_auto_conclude(
    supervisor_guidance: Any,
    patient_turns: int,
    settings: Settings,
    risk_factor_count: int = 0,
) -> bool:
    """是否該自動結束問診（純函式，便於單元測試）。

    兩條獨立路徑、皆受 ENABLED 總開關控制：
      - 軟門檻：Supervisor HPI 完整度 >= THRESHOLD 且病患回合 >= MIN（且該指導非
        fallback 佔位 — 降級時 hpi 不可信）。§3b 的 supervisor gate 會在關鍵風險因子
        問到前壓住完整度 < THRESHOLD，故軟門檻天然等到風險因子問完才觸發。
      - 硬上限：病患回合 >= effective HARD_CAP，不依賴 Supervisor（降級時的保命線）。
        §3b：有 K>0 風險因子的高風險主訴，effective cap = base + K + BUFFER。
    紅旗/drain/compare-and-set 等 turn-state 守衛留在呼叫端，不在此函式。
    """
    if not getattr(settings, "HPI_COMPLETION_TERMINATION_ENABLED", True):
        return False
    hpi_pct: float | None = None
    if isinstance(supervisor_guidance, dict) and not supervisor_guidance.get("fallback"):
        hpi_pct = coerce_hpi_pct(supervisor_guidance.get("hpi_completion_percentage"))
    # §3b：高風險主訴(K>0)的軟門檻回合下限抬高——確保對話跑夠久，讓 conversation LLM
    # 問到全部 K 個風險因子。這是 supervisor gate 的**確定性 backstop**：supervisor 是
    # LLM，偶發會在只問到 1/K 個風險因子時就早放行 hpi>=80（實測 ED 場），純語意 gate
    # 不足以保證。下限 = base + K - 1（< effective hard cap = base+K+buffer，仍留 backstop
    # 空間），與 don't-know 無關（病患表示不知道仍算問到、由 supervisor gate 處理）。
    soft_min_turns = getattr(settings, "MIN_PATIENT_TURNS_BEFORE_AUTO_END", 5)
    if risk_factor_count > 0:
        base_cap = getattr(settings, "MAX_PATIENT_TURNS_HARD_CAP", 10)
        soft_min_turns = max(soft_min_turns, base_cap + risk_factor_count - 1)
    soft_ready = (
        hpi_pct is not None
        and hpi_pct >= getattr(settings, "HPI_COMPLETION_TERMINATION_THRESHOLD", 80)
        and patient_turns >= soft_min_turns
    )
    hard_ready = hard_cap_reached(patient_turns, settings, risk_factor_count)
    return bool(soft_ready or hard_ready)


def session_risk_factor_count(session_context: dict[str, Any]) -> int:
    """§3b：本場次「與 HPI 十欄同級必問」的關鍵風險因子題數（K）。

    **必須用 raw `chief_complaint`**（非顯示名稱）——build_system_prompt 與
    supervisor.analyze_next_step 注入 §3b 風險因子清單時都用 raw
    `session_context["chief_complaint"]`。cap 加成 / 軟門檻下限的 gating 必須基於「與
    這兩處注入相同的主訴字串」，否則會漂移：實測 ED 場 chief_complaint_display 不含
    「勃起」→ 用 display 算成 K=0、軟門檻下限沒抬高，但 conversation/supervisor 用 raw
    「勃起功能障礙」→ K=3 確實把風險因子列為必問，兩者矛盾導致收尾邏輯漏問。
    """
    return count_critical_risk_factors_for_complaint(
        session_context.get("chief_complaint", "")
    )


def should_conclude_now(
    should_conclude: bool,
    hard_cap_reached: bool,
    soft_defer: bool,
    drain_unresolved: bool,
) -> bool:
    """A2 [D1+D5]：收尾閘門（純函式，便於矩陣測試）。

    - should_conclude 為 False → 一律不收尾。
    - drain_unresolved（遲到紅旗仍未解析）→ 一律延後；硬上限時呼叫端須先做
      有界 inline 解析 + MAX_HARD_CAP_DRAIN_DEFERS 絕對保命線後才傳入。
    - 軟門檻路徑（未達硬上限）被 soft_defer（本輪 critical/high 紅旗或空回應
      fallback）否決；**硬上限不被 soft_defer 否決**（D1 修復核心）。
    """
    if not should_conclude:
        return False
    if drain_unresolved:
        return False
    if hard_cap_reached:
        return True
    return not soft_defer
