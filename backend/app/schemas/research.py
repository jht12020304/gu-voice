"""研究分析（Research Analytics）Pydantic Schema

供 `/api/v1/research/analytics` 使用。指標選擇對齊國際期刊常用評估框架：
- DECIDE-AI（AI 決策支援早期臨床評估報告指引，Nature Medicine 2022）
- AMIE 對話式診斷 AI 評估軸（病史採集完整度等，Nature 2025）
- 症狀檢查器 triage 安全文獻（sensitivity / under-triage，JMIR 2022 等）
- PDQI-9 文件品質工具（醫師審閱結果為 pragmatic proxy）

命名一律 snake_case；前端 axios interceptor 會自動轉 camelCase。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DistributionBucket(BaseModel):
    """單一分佈桶（named key + 計數）。"""

    key: str
    count: int = 0


class Proportion(BaseModel):
    """比例 + Wilson score 95% CI（SAMPL 指引：比例須附分子/分母與 CI）。

    value / ci_low / ci_high 為 0~1；denominator 為 0 時全為 None（缺值）。
    前端以 value 畫點、[ci_low, ci_high] 畫誤差線。
    """

    numerator: int = 0
    denominator: int = 0
    value: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None


class NumericSummary(BaseModel):
    """連續變數描述統計（發表慣例：中位數 + IQR 為主，均數輔助）。

    median / p25 / p75 / min / max 直接支援箱形圖繪製（不用長條圖呈現連續資料，
    見 Weissgerber 2015「Beyond Bar and Line Graphs」）。
    """

    n: int = 0
    mean: Optional[float] = None
    sd: Optional[float] = None
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    # 箱形圖 whisker（Tukey 1.5×IQR 內的最極端觀測值）與離群點
    whisker_low: Optional[float] = None
    whisker_high: Optional[float] = None
    outliers: list[float] = []


class HistogramBucket(BaseModel):
    """直方圖桶：[start, end) 區間與計數。"""

    start: float
    end: float
    count: int = 0


class WeeklyTrendItem(BaseModel):
    """週趨勢（ISO 週一為起點）。"""

    week_start: str  # YYYY-MM-DD
    sessions: int = 0
    completed: int = 0
    red_flag_sessions: int = 0


class CohortSection(BaseModel):
    """收案流（CONSORT-style flow）。"""

    total_sessions: int = 0
    completed: int = 0
    aborted_red_flag: int = 0
    cancelled: int = 0
    in_progress_or_waiting: int = 0
    completion_rate: Optional[float] = None  # 舊欄位，前端改用 completion.value
    completion: Proportion = Proportion()
    weekly_trend: list[WeeklyTrendItem] = []


class DemographicsSection(BaseModel):
    """病患人口學（Table 1 —— 臨床論文必備的基線特徵）。"""

    total_patients: int = 0
    age_years: NumericSummary = NumericSummary()
    age_band_distribution: list[DistributionBucket] = []  # <40 / 40-59 / 60-74 / 75+
    gender_distribution: list[DistributionBucket] = []  # male / female / other
    chief_complaint_distribution: list[DistributionBucket] = []  # case mix（canonical slug）


class EfficiencySection(BaseModel):
    """問診效率（終態場次）。"""

    duration_seconds: NumericSummary = NumericSummary()
    patient_turns: NumericSummary = NumericSummary()
    patient_turn_chars: NumericSummary = NumericSummary()
    duration_histogram: list[HistogramBucket] = []
    turns_histogram: list[HistogramBucket] = []


class HpiFieldFillRate(BaseModel):
    """HPI 單一欄位填答率。"""

    field: str
    filled: int = 0
    total: int = 0
    rate: Optional[float] = None


class HistoryTakingSection(BaseModel):
    """病史採集完整度（AMIE 評估軸：structure & completeness of history）。"""

    reports_analyzed: int = 0
    mean_hpi_completeness: Optional[float] = None  # 0~1，10 欄平均填答比例
    hpi_completeness_summary: NumericSummary = NumericSummary()
    hpi_field_fill_rates: list[HpiFieldFillRate] = []


class SafetySection(BaseModel):
    """Triage 安全（症狀檢查器文獻慣例指標）。"""

    sessions_with_alerts: int = 0
    alert_session_rate: Optional[float] = None  # 舊欄位，前端改用 alert_session.value
    alert_session: Proportion = Proportion()
    total_alerts: int = 0
    severity_distribution: list[DistributionBucket] = []
    layer_distribution: list[DistributionBucket] = []  # rule_hit / semantic_only / uncovered_locale
    alert_type_distribution: list[DistributionBucket] = []  # rule_based / semantic / combined
    urgency_distribution: list[DistributionBucket] = []  # SOAP plan.urgency
    time_to_first_alert_seconds: NumericSummary = NumericSummary()
    acknowledged_rate: Optional[float] = None  # 舊欄位，前端改用 acknowledged.value
    acknowledged: Proportion = Proportion()
    ack_latency_seconds: NumericSummary = NumericSummary()


class SttLanguageQuality(BaseModel):
    """各語言 STT 品質。"""

    language: str
    turns: int = 0
    mean_confidence: Optional[float] = None
    median_confidence: Optional[float] = None
    low_confidence_rate: Optional[float] = None  # confidence < 0.5


class SttQualitySection(BaseModel):
    """語音辨識品質（exp(avg_logprob) 信心分數 proxy）。"""

    turns_with_confidence: int = 0
    confidence_summary: NumericSummary = NumericSummary()
    low_confidence_rate: Optional[float] = None  # 舊欄位
    low_confidence: Proportion = Proportion()
    histogram: list[HistogramBucket] = []
    by_language: list[SttLanguageQuality] = []
    voice_turn_share: Optional[float] = None  # 語音輸入輪 / 全部病患輪


class DocumentationSection(BaseModel):
    """AI 文件品質（PDQI-9 精神：以醫師審閱結果為 pragmatic proxy）。"""

    reports_generated: int = 0
    ai_confidence_summary: NumericSummary = NumericSummary()
    icd10_verified_rate: Optional[float] = None  # 舊欄位
    icd10_verified: Proportion = Proportion()
    review_outcomes: list[DistributionBucket] = []  # pending / approved / revision_needed
    physician_agreement_rate: Optional[float] = None  # 舊欄位
    physician_agreement: Proportion = Proportion()
    revision_reason_distribution: list[DistributionBucket] = []


class LanguageBreakdownItem(BaseModel):
    """各語言子群摘要（table view + 森林圖）。"""

    language: str
    sessions: int = 0
    completed: int = 0
    median_duration_seconds: Optional[float] = None
    mean_patient_turns: Optional[float] = None
    mean_stt_confidence: Optional[float] = None
    red_flag_session_rate: Optional[float] = None  # 舊欄位
    # 森林圖用：終態場次為分母的紅旗率 + Wilson 95% CI
    red_flag_rate: Proportion = Proportion()


class ResearchAnalyticsResponse(BaseModel):
    """研究分析總回應。"""

    generated_at: datetime
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    cohort: CohortSection = CohortSection()
    demographics: DemographicsSection = DemographicsSection()
    efficiency: EfficiencySection = EfficiencySection()
    history_taking: HistoryTakingSection = HistoryTakingSection()
    safety: SafetySection = SafetySection()
    stt_quality: SttQualitySection = SttQualitySection()
    documentation: DocumentationSection = DocumentationSection()
    by_language: list[LanguageBreakdownItem] = []
