"""
研究分析服務 — 把問診數據聚合成「可發表」的研究指標。

設計原則
--------
- DB 只做單純取數（5 個查詢），統計一律在純 Python helper 計算，
  讓 helper 可以無 DB 單元測試（kiosk 規模下資料量小，Python 端計算便宜）。
- 指標選擇對齊文獻（見 schemas/research.py docstring）：
  收案流（CONSORT-style）、病史採集完整度（AMIE 軸）、triage 安全
  （症狀檢查器文獻：alert rate / time-to-detection / ack latency）、
  效率（時長 / 輪次）、STT 品質、AI 文件品質（醫師審閱 agreement）。
- 描述統計以中位數 + IQR 為主（期刊慣例，時長/輪次多為右偏分佈）。
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chief_complaint import ChiefComplaint
from app.models.conversation import Conversation
from app.models.patient import Patient
from app.models.red_flag_alert import RedFlagAlert
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.models.soap_report_revision import SOAPReportRevision
from app.schemas.research import (
    CohortSection,
    DemographicsSection,
    DistributionBucket,
    DocumentationSection,
    EfficiencySection,
    HistogramBucket,
    HistoryTakingSection,
    HpiFieldFillRate,
    LanguageBreakdownItem,
    NumericSummary,
    Proportion,
    ResearchAnalyticsResponse,
    SafetySection,
    SttLanguageQuality,
    SttQualitySection,
    WeeklyTrendItem,
)
from app.utils.datetime_utils import utc_now

# Wilson score interval 的 z（95% 雙尾）。小樣本下 Wilson 比 Wald 準確且不會
# 越界 [0,1]，是比例 CI 的發表推薦作法。
_Z_95 = 1.959963984540054

logger = logging.getLogger(__name__)

# SOAP subjective.hpi 的 10 個結構化欄位（與 soap_generator prompt schema 同步）
HPI_FIELDS: tuple[str, ...] = (
    "onset",
    "location",
    "duration",
    "characteristics",
    "severity",
    "aggravating_factors",
    "relieving_factors",
    "associated_symptoms",
    "timing",
    "context",
)

# STT 低信心門檻：exp(avg_logprob) proxy；Whisper 視 avg_logprob < -1.0
# （exp ≈ 0.37）為解碼失敗，0.5 為保守的「需人工留意」線（與前端一致）。
LOW_CONFIDENCE_THRESHOLD = 0.5

_TERMINAL_STATUSES = ("completed", "aborted_red_flag")


# ── 純 Python 統計 helper（無 DB，可直接單元測試） ─────────────


def summarize(values: Sequence[float]) -> NumericSummary:
    """描述統計：n / mean / SD / median / IQR / min / max + 箱形圖 whisker/離群。

    百分位用線性內插（同 PG percentile_cont）。whisker 取 Tukey 1.5×IQR 圍籬內
    最極端的真實觀測值，圍籬外者列為 outliers —— 讓前端直接畫標準箱形圖。
    """
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return NumericSummary()
    n = len(vals)
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    q1 = percentile(vals, 0.25)
    q3 = percentile(vals, 0.75)
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = [v for v in vals if lo_fence <= v <= hi_fence]
    outliers = [round(v, 2) for v in vals if v < lo_fence or v > hi_fence]
    return NumericSummary(
        n=n,
        mean=round(mean, 2),
        sd=round(sd, 2),
        median=round(percentile(vals, 0.5), 2),
        p25=round(q1, 2),
        p75=round(q3, 2),
        min=round(vals[0], 2),
        max=round(vals[-1], 2),
        whisker_low=round(inside[0], 2) if inside else round(vals[0], 2),
        whisker_high=round(inside[-1], 2) if inside else round(vals[-1], 2),
        outliers=outliers,
    )


def wilson_proportion(numerator: int, denominator: int) -> Proportion:
    """比例 + Wilson score 95% CI。denominator 0 → 全 None（缺值，非 0）。

    防禦性 clamp：p 夾在 [0,1]。理論上 numerator ≤ denominator，但若呼叫端
    分子/分母來自不同母體（如「所有有紅旗場次」對「終態場次」），numerator 可能
    超過 denominator → p>1 → sqrt 負數 domain error。夾住避免 500，呼叫端仍應
    確保分子是分母的子集（見下方 terminal_ids 交集）。
    """
    if denominator <= 0:
        return Proportion(numerator=numerator, denominator=denominator)
    p = min(1.0, max(0.0, numerator / denominator))
    z = _Z_95
    denom = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / denom
    half = (
        z
        * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator * denominator))
        / denom
    )
    return Proportion(
        numerator=numerator,
        denominator=denominator,
        value=round(p, 4),
        ci_low=round(max(0.0, center - half), 4),
        ci_high=round(min(1.0, center + half), 4),
    )


def percentile(sorted_vals: Sequence[float], q: float) -> float:
    """線性內插百分位（輸入必須已排序、非空）。等同 PG percentile_cont。"""
    if not sorted_vals:
        raise ValueError("percentile of empty sequence")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo]) * (1 - frac) + float(sorted_vals[hi]) * frac


def histogram(
    values: Sequence[float], edges: Sequence[float]
) -> list[HistogramBucket]:
    """固定桶邊界直方圖：[edges[i], edges[i+1])，最後一桶右閉。"""
    buckets = [
        HistogramBucket(start=float(edges[i]), end=float(edges[i + 1]), count=0)
        for i in range(len(edges) - 1)
    ]
    if not buckets:
        return []
    last = len(buckets) - 1
    for v in values:
        if v is None:
            continue
        fv = float(v)
        if fv < edges[0] or fv > edges[-1]:
            continue
        for i, b in enumerate(buckets):
            if fv < b.end or (i == last and fv <= b.end):
                b.count += 1
                break
    return buckets


def distribution(
    pairs: Iterable[tuple[str, int]], order: Sequence[str] | None = None
) -> list[DistributionBucket]:
    """計數對 → DistributionBucket list；order 給定時按其排序並補 0 桶。"""
    counts: dict[str, int] = {}
    for key, cnt in pairs:
        counts[key] = counts.get(key, 0) + int(cnt)
    if order:
        return [DistributionBucket(key=k, count=counts.get(k, 0)) for k in order]
    return [
        DistributionBucket(key=k, count=c)
        for k, c in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def hpi_completeness(subjective: Any) -> Optional[float]:
    """單份 SOAP 的 HPI 完整度：10 欄中「非空」比例；無 hpi 結構 → 0.0。

    「空」＝ None / 空字串 / 純空白。LLM prompt 規定未提及要填 null，
    故此比例可直接當「對話有採集到該欄」的 proxy（AMIE 病史完整度軸）。
    """
    if not isinstance(subjective, dict):
        return None
    hpi = subjective.get("hpi")
    if not isinstance(hpi, dict):
        return 0.0
    filled = sum(
        1
        for f in HPI_FIELDS
        if isinstance(hpi.get(f), str) and hpi.get(f).strip()
    )
    return filled / len(HPI_FIELDS)


def week_start_of(dt: datetime) -> str:
    """ISO 週（週一起）之起始日 YYYY-MM-DD。"""
    d = dt.date()
    return (d - timedelta(days=d.weekday())).isoformat()


def rate(numerator: int, denominator: int) -> Optional[float]:
    """安全比例：分母 0 → None（缺值，不是 0%）。"""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def age_band(age: int) -> str:
    """年齡分帶（泌尿科常用切點；攝護腺相關集中在 60+）。"""
    if age < 40:
        return "<40"
    if age < 60:
        return "40-59"
    if age < 75:
        return "60-74"
    return "75+"


def age_from_dob(dob: date, ref: date) -> int:
    """以參考日計算實歲。"""
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


# ── 主服務 ──────────────────────────────────────────────


class ResearchService:
    """研究分析聚合。所有指標為去識別化 aggregate，不含任何病患個資。"""

    async def get_analytics(
        self,
        db: AsyncSession,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> ResearchAnalyticsResponse:
        # ── Q1：sessions ────────────────────────────────
        stmt = select(
            Session.id,
            Session.status,
            Session.language,
            Session.created_at,
            Session.started_at,
            Session.completed_at,
            Session.duration_seconds,
        )
        if date_from is not None:
            stmt = stmt.where(Session.created_at >= date_from)
        if date_to is not None:
            # 含當日：< date_to + 1 day
            stmt = stmt.where(
                Session.created_at < date_to + timedelta(days=1)
            )
        session_rows = (await db.execute(stmt)).all()
        session_ids = [r.id for r in session_rows]
        sess_by_id = {r.id: r for r in session_rows}

        if not session_ids:
            return ResearchAnalyticsResponse(
                generated_at=utc_now(),
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
            )

        # ── Q2：病患對話輪 ───────────────────────────────
        conv_rows = (
            await db.execute(
                select(
                    Conversation.session_id,
                    func.length(Conversation.content_text).label("chars"),
                    Conversation.stt_confidence,
                    Conversation.metadata_["input_source"].astext.label(
                        "input_source"
                    ),
                )
                .where(Conversation.session_id.in_(session_ids))
                .where(Conversation.role == "patient")
            )
        ).all()

        # ── Q3：紅旗警示 ────────────────────────────────
        alert_rows = (
            await db.execute(
                select(
                    RedFlagAlert.session_id,
                    RedFlagAlert.severity,
                    RedFlagAlert.alert_type,
                    RedFlagAlert.confidence,
                    RedFlagAlert.created_at,
                    RedFlagAlert.acknowledged_at,
                ).where(RedFlagAlert.session_id.in_(session_ids))
            )
        ).all()

        # ── Q4：SOAP 報告 ───────────────────────────────
        report_rows = (
            await db.execute(
                select(
                    SOAPReport.id,
                    SOAPReport.session_id,
                    SOAPReport.status,
                    SOAPReport.review_status,
                    SOAPReport.ai_confidence_score,
                    SOAPReport.icd10_verified,
                    SOAPReport.subjective,
                    SOAPReport.plan["urgency"].astext.label("urgency"),
                ).where(SOAPReport.session_id.in_(session_ids))
            )
        ).all()

        # ── Q5：revision reason 分佈 ─────────────────────
        report_ids = [r.id for r in report_rows]
        revision_pairs: list[tuple[str, int]] = []
        if report_ids:
            rev_rows = (
                await db.execute(
                    select(
                        SOAPReportRevision.reason,
                        func.count().label("cnt"),
                    )
                    .where(SOAPReportRevision.report_id.in_(report_ids))
                    .group_by(SOAPReportRevision.reason)
                )
            ).all()
            revision_pairs = [
                (
                    r.reason.value if hasattr(r.reason, "value") else str(r.reason),
                    r.cnt,
                )
                for r in rev_rows
            ]

        # ── Q6：病患人口學（Table 1）+ 主訴 case mix ─────
        # 以 session 為單位取每場的病患 DOB/性別與主訴 canonical 名，
        # demographics 以「distinct 病患」計、case mix 以「場次」計。
        demo_rows = (
            await db.execute(
                select(
                    Session.id.label("session_id"),
                    Session.patient_id,
                    Patient.date_of_birth,
                    Patient.gender,
                    func.coalesce(ChiefComplaint.name_en, ChiefComplaint.name).label(
                        "complaint"
                    ),
                )
                .join(Patient, Patient.id == Session.patient_id, isouter=True)
                .join(
                    ChiefComplaint,
                    ChiefComplaint.id == Session.chief_complaint_id,
                    isouter=True,
                )
                .where(Session.id.in_(session_ids))
            )
        ).all()

        return self._assemble(
            session_rows=session_rows,
            sess_by_id=sess_by_id,
            conv_rows=conv_rows,
            alert_rows=alert_rows,
            report_rows=report_rows,
            revision_pairs=revision_pairs,
            demo_rows=demo_rows,
            date_from=date_from,
            date_to=date_to,
        )

    # ── 組裝（純計算，rows 可用 stub 餵，方便單元測試） ─────────

    def _assemble(
        self,
        *,
        session_rows: Sequence[Any],
        sess_by_id: dict[Any, Any],
        conv_rows: Sequence[Any],
        alert_rows: Sequence[Any],
        report_rows: Sequence[Any],
        revision_pairs: list[tuple[str, int]],
        date_from: Optional[date],
        date_to: Optional[date],
        demo_rows: Sequence[Any] = (),
    ) -> ResearchAnalyticsResponse:
        def status_of(row: Any) -> str:
            s = row.status
            return s.value if hasattr(s, "value") else str(s)

        sessions_with_alert = {a.session_id for a in alert_rows}
        # 終態場次 id（completed / aborted_red_flag）。紅旗率的分母是終態場次，
        # 故分子必須是「終態且有紅旗」——紅旗可能落在 in_progress/cancelled 場次，
        # 若直接用 sessions_with_alert 當分子會 > 分母（見 wilson_proportion clamp）。
        terminal_ids = {
            r.id for r in session_rows if status_of(r) in _TERMINAL_STATUSES
        }
        terminal_with_alert = sessions_with_alert & terminal_ids

        # ── Cohort ─────────────────────────────────────
        status_counts: dict[str, int] = {}
        weekly: dict[str, dict[str, int]] = {}
        for r in session_rows:
            st = status_of(r)
            status_counts[st] = status_counts.get(st, 0) + 1
            wk = week_start_of(r.created_at)
            bucket = weekly.setdefault(
                wk, {"sessions": 0, "completed": 0, "red_flag_sessions": 0}
            )
            bucket["sessions"] += 1
            if st == "completed":
                bucket["completed"] += 1
            if r.id in sessions_with_alert:
                bucket["red_flag_sessions"] += 1

        completed = status_counts.get("completed", 0)
        aborted = status_counts.get("aborted_red_flag", 0)
        cancelled = status_counts.get("cancelled", 0)
        total = len(session_rows)
        terminal = completed + aborted
        cohort = CohortSection(
            total_sessions=total,
            completed=completed,
            aborted_red_flag=aborted,
            cancelled=cancelled,
            in_progress_or_waiting=total - completed - aborted - cancelled,
            completion_rate=rate(completed, total),
            completion=wilson_proportion(completed, total),
            weekly_trend=[
                WeeklyTrendItem(week_start=wk, **counts)
                for wk, counts in sorted(weekly.items())
            ],
        )

        # ── Demographics（Table 1）──────────────────────
        # 病患層級去重（同病患多場次只計一次年齡/性別）；主訴以場次計 case mix。
        ref_day = (
            max((r.created_at.date() for r in session_rows), default=None)
            or utc_now().date()
        )
        patient_age: dict[Any, int] = {}
        patient_gender: dict[Any, str] = {}
        complaint_counts: dict[str, int] = {}
        for r in demo_rows:
            comp = (r.complaint or "unknown").strip() or "unknown"
            complaint_counts[comp] = complaint_counts.get(comp, 0) + 1
            pid = getattr(r, "patient_id", None)
            if pid is None:
                continue
            if r.date_of_birth is not None and pid not in patient_age:
                patient_age[pid] = age_from_dob(r.date_of_birth, ref_day)
            if pid not in patient_gender and r.gender is not None:
                g = r.gender
                patient_gender[pid] = g.value if hasattr(g, "value") else str(g)
        ages = list(patient_age.values())
        demographics = DemographicsSection(
            total_patients=len({r.patient_id for r in demo_rows if r.patient_id}),
            age_years=summarize([float(a) for a in ages]),
            age_band_distribution=distribution(
                ((age_band(a), 1) for a in ages),
                order=["<40", "40-59", "60-74", "75+"],
            ),
            gender_distribution=distribution(
                ((g, 1) for g in patient_gender.values()),
                order=["male", "female", "other"],
            ),
            chief_complaint_distribution=distribution(complaint_counts.items()),
        )

        # ── Efficiency ─────────────────────────────────
        durations: list[float] = []
        for r in session_rows:
            if status_of(r) not in _TERMINAL_STATUSES:
                continue
            if r.completed_at and r.started_at:
                durations.append((r.completed_at - r.started_at).total_seconds())
            elif r.duration_seconds is not None:
                durations.append(float(r.duration_seconds))

        turns_by_session: dict[Any, int] = {}
        turn_chars: list[float] = []
        for c in conv_rows:
            turns_by_session[c.session_id] = turns_by_session.get(c.session_id, 0) + 1
            if c.chars is not None:
                turn_chars.append(float(c.chars))
        turns_values = [float(v) for v in turns_by_session.values()]

        max_dur = max(durations) if durations else 0
        dur_edge_max = max(600.0, (int(max_dur // 300) + 1) * 300.0)
        efficiency = EfficiencySection(
            duration_seconds=summarize(durations),
            patient_turns=summarize(turns_values),
            patient_turn_chars=summarize(turn_chars),
            duration_histogram=histogram(
                durations,
                [i * 300.0 for i in range(int(dur_edge_max // 300) + 1)],
            ),
            turns_histogram=histogram(
                turns_values, [0, 2, 4, 6, 8, 10, 12, 15, 20, 30]
            ),
        )

        # ── History taking（HPI 完整度） ─────────────────
        completeness_vals: list[float] = []
        field_filled: dict[str, int] = {f: 0 for f in HPI_FIELDS}
        analyzed = 0
        for rep in report_rows:
            status_val = (
                rep.status.value if hasattr(rep.status, "value") else str(rep.status)
            )
            if status_val != "generated":
                continue
            comp = hpi_completeness(rep.subjective)
            if comp is None:
                continue
            analyzed += 1
            completeness_vals.append(comp)
            hpi = (rep.subjective or {}).get("hpi") or {}
            for f in HPI_FIELDS:
                v = hpi.get(f) if isinstance(hpi, dict) else None
                if isinstance(v, str) and v.strip():
                    field_filled[f] += 1
        history = HistoryTakingSection(
            reports_analyzed=analyzed,
            mean_hpi_completeness=(
                round(sum(completeness_vals) / analyzed, 4) if analyzed else None
            ),
            hpi_completeness_summary=summarize(completeness_vals),
            hpi_field_fill_rates=[
                HpiFieldFillRate(
                    field=f,
                    filled=field_filled[f],
                    total=analyzed,
                    rate=rate(field_filled[f], analyzed),
                )
                for f in HPI_FIELDS
            ],
        )

        # ── Safety ─────────────────────────────────────
        first_alert_by_session: dict[Any, datetime] = {}
        ack_latencies: list[float] = []
        acked = 0
        for a in alert_rows:
            prev = first_alert_by_session.get(a.session_id)
            if prev is None or a.created_at < prev:
                first_alert_by_session[a.session_id] = a.created_at
            if a.acknowledged_at is not None:
                acked += 1
                ack_latencies.append(
                    (a.acknowledged_at - a.created_at).total_seconds()
                )
        time_to_first: list[float] = []
        for sid, first_at in first_alert_by_session.items():
            sess = sess_by_id.get(sid)
            if sess is not None and sess.started_at:
                delta = (first_at - sess.started_at).total_seconds()
                if delta >= 0:
                    time_to_first.append(delta)

        def enum_val(v: Any) -> str:
            return v.value if hasattr(v, "value") else str(v)

        safety = SafetySection(
            sessions_with_alerts=len(sessions_with_alert),
            alert_session_rate=rate(len(terminal_with_alert), terminal),
            total_alerts=len(alert_rows),
            severity_distribution=distribution(
                ((enum_val(a.severity), 1) for a in alert_rows),
                order=["critical", "high", "medium"],
            ),
            layer_distribution=distribution(
                ((enum_val(a.confidence), 1) for a in alert_rows),
                order=["rule_hit", "semantic_only", "uncovered_locale"],
            ),
            alert_type_distribution=distribution(
                ((enum_val(a.alert_type), 1) for a in alert_rows),
                order=["rule_based", "semantic", "combined"],
            ),
            urgency_distribution=distribution(
                (
                    (rep.urgency, 1)
                    for rep in report_rows
                    if rep.urgency
                ),
                order=["er_now", "24h", "this_week", "routine"],
            ),
            time_to_first_alert_seconds=summarize(time_to_first),
            acknowledged_rate=rate(acked, len(alert_rows)),
            acknowledged=wilson_proportion(acked, len(alert_rows)),
            ack_latency_seconds=summarize(ack_latencies),
        )
        safety.alert_session = wilson_proportion(len(terminal_with_alert), terminal)

        # ── STT quality ────────────────────────────────
        confidences = [
            float(c.stt_confidence)
            for c in conv_rows
            if c.stt_confidence is not None
        ]
        low_count = sum(1 for v in confidences if v < LOW_CONFIDENCE_THRESHOLD)
        by_lang_conf: dict[str, list[float]] = {}
        for c in conv_rows:
            if c.stt_confidence is None:
                continue
            sess = sess_by_id.get(c.session_id)
            lang = getattr(sess, "language", None) or "unknown"
            by_lang_conf.setdefault(lang, []).append(float(c.stt_confidence))
        voice_turns = sum(1 for c in conv_rows if c.input_source == "voice")
        source_known = sum(1 for c in conv_rows if c.input_source)
        stt = SttQualitySection(
            turns_with_confidence=len(confidences),
            confidence_summary=summarize(confidences),
            low_confidence_rate=rate(low_count, len(confidences)),
            low_confidence=wilson_proportion(low_count, len(confidences)),
            histogram=histogram(confidences, [i / 10 for i in range(11)]),
            by_language=[
                SttLanguageQuality(
                    language=lang,
                    turns=len(vals),
                    mean_confidence=round(sum(vals) / len(vals), 4),
                    median_confidence=round(percentile(sorted(vals), 0.5), 4),
                    low_confidence_rate=rate(
                        sum(1 for v in vals if v < LOW_CONFIDENCE_THRESHOLD),
                        len(vals),
                    ),
                )
                for lang, vals in sorted(by_lang_conf.items())
            ],
            voice_turn_share=rate(voice_turns, source_known),
        )

        # ── Documentation ──────────────────────────────
        generated_reports = [
            rep
            for rep in report_rows
            if enum_val(rep.status) == "generated"
        ]
        ai_conf = [
            float(rep.ai_confidence_score)
            for rep in generated_reports
            if rep.ai_confidence_score is not None
        ]
        review_counts: dict[str, int] = {}
        for rep in generated_reports:
            rv = enum_val(rep.review_status)
            review_counts[rv] = review_counts.get(rv, 0) + 1
        approved = review_counts.get("approved", 0)
        revision_needed = review_counts.get("revision_needed", 0)
        icd_verified = sum(1 for rep in generated_reports if rep.icd10_verified)
        documentation = DocumentationSection(
            reports_generated=len(generated_reports),
            ai_confidence_summary=summarize(ai_conf),
            icd10_verified_rate=rate(icd_verified, len(generated_reports)),
            icd10_verified=wilson_proportion(icd_verified, len(generated_reports)),
            review_outcomes=distribution(
                review_counts.items(),
                order=["approved", "revision_needed", "pending"],
            ),
            physician_agreement_rate=rate(approved, approved + revision_needed),
            physician_agreement=wilson_proportion(approved, approved + revision_needed),
            revision_reason_distribution=distribution(
                revision_pairs,
                order=["initial", "regenerate", "review_override"],
            ),
        )

        # ── By language（table view） ───────────────────
        by_language: list[LanguageBreakdownItem] = []
        langs = sorted({(r.language or "unknown") for r in session_rows})
        for lang in langs:
            lang_sessions = [
                r for r in session_rows if (r.language or "unknown") == lang
            ]
            lang_ids = {r.id for r in lang_sessions}
            lang_durations = sorted(
                (r.completed_at - r.started_at).total_seconds()
                for r in lang_sessions
                if status_of(r) in _TERMINAL_STATUSES
                and r.completed_at
                and r.started_at
            )
            lang_turns = [
                float(turns_by_session[sid])
                for sid in lang_ids
                if sid in turns_by_session
            ]
            lang_conf = by_lang_conf.get(lang, [])
            lang_terminal_ids = {
                r.id for r in lang_sessions if status_of(r) in _TERMINAL_STATUSES
            }
            lang_terminal = len(lang_terminal_ids)
            # 分子須是分母（終態場次）的子集 → 與 terminal_with_alert 一致
            lang_alert_sessions = len(lang_terminal_ids & sessions_with_alert)
            by_language.append(
                LanguageBreakdownItem(
                    language=lang,
                    sessions=len(lang_sessions),
                    completed=sum(
                        1 for r in lang_sessions if status_of(r) == "completed"
                    ),
                    median_duration_seconds=(
                        round(percentile(lang_durations, 0.5), 1)
                        if lang_durations
                        else None
                    ),
                    mean_patient_turns=(
                        round(sum(lang_turns) / len(lang_turns), 2)
                        if lang_turns
                        else None
                    ),
                    mean_stt_confidence=(
                        round(sum(lang_conf) / len(lang_conf), 4)
                        if lang_conf
                        else None
                    ),
                    red_flag_session_rate=rate(lang_alert_sessions, lang_terminal),
                    red_flag_rate=wilson_proportion(lang_alert_sessions, lang_terminal),
                )
            )

        return ResearchAnalyticsResponse(
            generated_at=utc_now(),
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            cohort=cohort,
            demographics=demographics,
            efficiency=efficiency,
            history_taking=history,
            safety=safety,
            stt_quality=stt,
            documentation=documentation,
            by_language=by_language,
        )
