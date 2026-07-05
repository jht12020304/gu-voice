"""
守護研究分析聚合（ResearchService）：

- 純統計 helper（percentile / summarize / histogram / hpi_completeness）正確性
- _assemble 以 stub rows 走完整組裝：cohort 流、HPI 完整度、triage 安全、
  STT 品質、文件品質、各語言 table view
- 分母為 0 時比例回 None（缺值），不是 0%
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.research_service import (
    HPI_FIELDS,
    ResearchService,
    age_band,
    age_from_dob,
    histogram,
    hpi_completeness,
    percentile,
    rate,
    summarize,
    week_start_of,
    wilson_proportion,
)

T0 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)  # 週三


# ── helper 單元 ──────────────────────────────────────────


def test_percentile_linear_interpolation():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert percentile(vals, 0.5) == 2.5
    assert percentile(vals, 0.25) == 1.75
    assert percentile([7.0], 0.5) == 7.0


def test_summarize_empty_and_basic():
    empty = summarize([])
    assert empty.n == 0 and empty.median is None
    s = summarize([10, 20, 30])
    assert s.n == 3
    assert s.mean == 20
    assert s.median == 20
    assert s.min == 10 and s.max == 30


def test_histogram_buckets_and_bounds():
    buckets = histogram([0.05, 0.15, 0.95, 1.0, -0.1, 1.1], [i / 10 for i in range(11)])
    assert buckets[0].count == 1  # 0.05
    assert buckets[1].count == 1  # 0.15
    # 0.95 與右邊界 1.0 都落最後一桶；界外值（-0.1 / 1.1）丟棄
    assert buckets[9].count == 2
    assert sum(b.count for b in buckets) == 4


def test_hpi_completeness_counts_nonempty_strings():
    subj = {"hpi": {f: None for f in HPI_FIELDS}}
    subj["hpi"]["onset"] = "三天前"
    subj["hpi"]["severity"] = "  "  # 純空白不算
    assert hpi_completeness(subj) == 1 / len(HPI_FIELDS)
    assert hpi_completeness({"hpi": "not a dict"}) == 0.0
    assert hpi_completeness(None) is None


def test_rate_zero_denominator_is_none():
    assert rate(1, 0) is None
    assert rate(1, 4) == 0.25


def test_week_start_is_monday():
    assert week_start_of(T0) == "2026-06-29"  # 2026-07-01 為週三


def test_wilson_proportion_known_value():
    # 教科書驗證：Wilson 95% CI for 陽性 8/10
    # Wilson score 95% CI for 8/10 ≈ (0.490, 0.943)（教科書值）
    p = wilson_proportion(8, 10)
    assert p.value == 0.8
    assert p.numerator == 8 and p.denominator == 10
    assert abs(p.ci_low - 0.4902) < 0.005
    assert abs(p.ci_high - 0.9433) < 0.005
    # CI 不可越界 [0,1]
    edge = wilson_proportion(10, 10)
    assert 0.0 <= edge.ci_low <= 1.0 and edge.ci_high <= 1.0


def test_wilson_zero_denominator_is_none():
    p = wilson_proportion(0, 0)
    assert p.value is None and p.ci_low is None and p.ci_high is None
    assert p.denominator == 0


def test_wilson_clamps_numerator_over_denominator_no_crash():
    # 防禦：分子 > 分母（呼叫端母體不一致）不可 sqrt domain error → clamp p=1
    p = wilson_proportion(5, 3)
    assert p.value == 1.0
    assert p.ci_low is not None and p.ci_high is not None


def test_assemble_alert_on_non_terminal_session_no_500():
    """回歸：紅旗落在非終態場次（in_progress / cancelled）時，紅旗率分子
    不可超過終態場次分母而讓 Wilson CI sqrt 負數 500（生產 request 742f698d）。"""
    from datetime import date as _date
    s_done, s_cancel = uuid4(), uuid4()
    sessions = [
        _session(s_done, "completed", "zh-TW", 8),
        _session(s_cancel, "cancelled", "zh-TW", 1),
    ]
    # 兩場都有紅旗，但只有 1 場是終態 → 分子(2) 若不夾 > 分母(1)
    alerts = [
        SimpleNamespace(session_id=s_done, severity="high", alert_type="rule_based",
                        confidence="rule_hit", created_at=T0 + timedelta(minutes=2),
                        acknowledged_at=None),
        SimpleNamespace(session_id=s_cancel, severity="critical", alert_type="combined",
                        confidence="rule_hit", created_at=T0 + timedelta(minutes=1),
                        acknowledged_at=None),
    ]
    demo = [
        SimpleNamespace(session_id=s_done, patient_id=uuid4(),
                        date_of_birth=_date(1970, 1, 1), gender="male", complaint="Hematuria"),
        SimpleNamespace(session_id=s_cancel, patient_id=uuid4(),
                        date_of_birth=_date(1980, 1, 1), gender="female", complaint="Frequency"),
    ]
    out = ResearchService()._assemble(
        session_rows=sessions, sess_by_id={s.id: s for s in sessions},
        conv_rows=[], alert_rows=alerts, report_rows=[], revision_pairs=[],
        demo_rows=demo, date_from=None, date_to=None,
    )
    # 終態=1（completed），其中有紅旗=1 → rate 1.0，CI 有效不 crash
    assert out.safety.alert_session.denominator == 1
    assert out.safety.alert_session.value == 1.0
    assert out.safety.alert_session.ci_low is not None
    zh = next(b for b in out.by_language if b.language == "zh-TW")
    assert zh.red_flag_rate.denominator == 1
    assert zh.red_flag_rate.value == 1.0


def test_summarize_has_sd_and_boxplot_whiskers():
    s = summarize([1, 2, 3, 4, 5, 100])  # 100 為離群
    assert s.sd is not None and s.sd > 0
    # Tukey 1.5×IQR：100 應被列為 outlier，whisker_high 落在圍籬內最大值
    assert 100.0 in s.outliers
    assert s.whisker_high < 100.0
    assert s.whisker_low == 1.0


def test_age_band_cutpoints():
    assert age_band(39) == "<40"
    assert age_band(40) == "40-59"
    assert age_band(59) == "40-59"
    assert age_band(60) == "60-74"
    assert age_band(75) == "75+"


def test_age_from_dob():
    from datetime import date
    assert age_from_dob(date(1960, 6, 1), date(2026, 5, 1)) == 65  # 生日未到
    assert age_from_dob(date(1960, 6, 1), date(2026, 6, 1)) == 66  # 生日當天


# ── _assemble 全流程（stub rows） ─────────────────────────


def _session(sid, status="completed", language="zh-TW", minutes=10):
    return SimpleNamespace(
        id=sid,
        status=status,
        language=language,
        created_at=T0,
        started_at=T0,
        completed_at=T0 + timedelta(minutes=minutes),
        duration_seconds=minutes * 60,
    )


def _build():
    s1, s2, s3 = uuid4(), uuid4(), uuid4()
    sessions = [
        _session(s1, "completed", "zh-TW", 10),
        _session(s2, "aborted_red_flag", "en-US", 5),
        _session(s3, "cancelled", "zh-TW", 2),
    ]
    convs = [
        SimpleNamespace(session_id=s1, chars=20, stt_confidence=0.9, input_source="voice"),
        SimpleNamespace(session_id=s1, chars=30, stt_confidence=0.3, input_source="voice"),
        SimpleNamespace(session_id=s2, chars=10, stt_confidence=None, input_source="text"),
    ]
    alerts = [
        SimpleNamespace(
            session_id=s2,
            severity="critical",
            alert_type="combined",
            confidence="rule_hit",
            created_at=T0 + timedelta(minutes=3),
            acknowledged_at=T0 + timedelta(minutes=33),
        ),
    ]
    hpi = {f: None for f in HPI_FIELDS}
    hpi.update({"onset": "3 天前", "location": "下腹", "duration": "持續",
                "characteristics": "灼熱", "severity": "中度"})
    reports = [
        SimpleNamespace(
            id=uuid4(),
            session_id=s1,
            status="generated",
            review_status="approved",
            ai_confidence_score=0.8,
            icd10_verified=True,
            subjective={"hpi": hpi},
            urgency="this_week",
        ),
        SimpleNamespace(
            id=uuid4(),
            session_id=s2,
            status="generated",
            review_status="revision_needed",
            ai_confidence_score=0.6,
            icd10_verified=False,
            subjective={"hpi": {f: None for f in HPI_FIELDS}},
            urgency="er_now",
        ),
    ]
    from datetime import date as _date
    p1, p2 = uuid4(), uuid4()
    demo = [
        SimpleNamespace(session_id=s1, patient_id=p1,
                        date_of_birth=_date(1955, 1, 1), gender="male", complaint="Hematuria"),
        SimpleNamespace(session_id=s2, patient_id=p2,
                        date_of_birth=_date(1990, 1, 1), gender="female", complaint="Frequency"),
        SimpleNamespace(session_id=s3, patient_id=p1,
                        date_of_birth=_date(1955, 1, 1), gender="male", complaint="Hematuria"),
    ]
    svc = ResearchService()
    return svc._assemble(
        session_rows=sessions,
        sess_by_id={s.id: s for s in sessions},
        conv_rows=convs,
        alert_rows=alerts,
        report_rows=reports,
        revision_pairs=[("initial", 2), ("review_override", 1)],
        demo_rows=demo,
        date_from=None,
        date_to=None,
    )


def test_assemble_cohort_flow():
    out = _build()
    assert out.cohort.total_sessions == 3
    assert out.cohort.completed == 1
    assert out.cohort.aborted_red_flag == 1
    assert out.cohort.cancelled == 1
    assert out.cohort.completion_rate == round(1 / 3, 4)
    assert out.cohort.weekly_trend[0].week_start == "2026-06-29"
    assert out.cohort.weekly_trend[0].red_flag_sessions == 1


def test_assemble_history_taking():
    out = _build()
    assert out.history_taking.reports_analyzed == 2
    # 一份 5/10、一份 0/10 → 平均 0.25
    assert out.history_taking.mean_hpi_completeness == 0.25
    onset = next(
        f for f in out.history_taking.hpi_field_fill_rates if f.field == "onset"
    )
    assert onset.filled == 1 and onset.total == 2 and onset.rate == 0.5


def test_assemble_safety_metrics():
    out = _build()
    # terminal = completed(1) + aborted(1) = 2；有紅旗場次 1 → rate 0.5
    assert out.safety.sessions_with_alerts == 1
    assert out.safety.alert_session_rate == 0.5
    assert out.safety.time_to_first_alert_seconds.median == 180.0
    assert out.safety.acknowledged_rate == 1.0
    assert out.safety.ack_latency_seconds.median == 1800.0
    sev = {b.key: b.count for b in out.safety.severity_distribution}
    assert sev == {"critical": 1, "high": 0, "medium": 0}
    urg = {b.key: b.count for b in out.safety.urgency_distribution}
    assert urg["er_now"] == 1 and urg["this_week"] == 1


def test_assemble_stt_quality():
    out = _build()
    assert out.stt_quality.turns_with_confidence == 2
    assert out.stt_quality.low_confidence_rate == 0.5  # 0.3 < 0.5
    assert out.stt_quality.voice_turn_share == round(2 / 3, 4)
    zh = next(b for b in out.stt_quality.by_language if b.language == "zh-TW")
    assert zh.turns == 2 and zh.mean_confidence == 0.6


def test_assemble_documentation_agreement():
    out = _build()
    assert out.documentation.reports_generated == 2
    assert out.documentation.icd10_verified_rate == 0.5
    # approved=1 / (approved+revision_needed)=2 → 0.5
    assert out.documentation.physician_agreement_rate == 0.5
    reasons = {b.key: b.count for b in out.documentation.revision_reason_distribution}
    assert reasons == {"initial": 2, "regenerate": 0, "review_override": 1}


def test_assemble_by_language_table():
    out = _build()
    langs = {b.language: b for b in out.by_language}
    assert set(langs) == {"zh-TW", "en-US"}
    assert langs["zh-TW"].sessions == 2
    assert langs["zh-TW"].completed == 1
    assert langs["zh-TW"].median_duration_seconds == 600.0
    # en-US 唯一終態場次即紅旗場次 → rate 1.0
    assert langs["en-US"].red_flag_session_rate == 1.0
    # 森林圖：紅旗率帶 Wilson CI（en-US 1/1）
    assert langs["en-US"].red_flag_rate.value == 1.0
    assert langs["en-US"].red_flag_rate.denominator == 1


def test_assemble_demographics_table1():
    out = _build()
    d = out.demographics
    # 3 場次但只有 2 位 distinct 病患（p1 兩場）
    assert d.total_patients == 2
    assert d.age_years.n == 2  # 去重後兩位病患的年齡
    genders = {b.key: b.count for b in d.gender_distribution}
    assert genders == {"male": 1, "female": 1, "other": 0}
    # case mix 以場次計：Hematuria 2 場（s1+s3）、Frequency 1 場
    cc = {b.key: b.count for b in d.chief_complaint_distribution}
    assert cc == {"Hematuria": 2, "Frequency": 1}


def test_assemble_proportions_carry_wilson_ci():
    out = _build()
    # completion 1/3 → value + CI 存在
    assert out.cohort.completion.value == round(1 / 3, 4)
    assert out.cohort.completion.ci_low is not None
    assert out.cohort.completion.ci_high is not None
    # 分母 0 的比例（無資料語言等）不應 crash；alert_session 2 分母有值
    assert out.safety.alert_session.denominator == 2
    assert out.documentation.physician_agreement.value == 0.5
