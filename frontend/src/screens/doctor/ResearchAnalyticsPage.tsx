// =============================================================================
// 研究分析頁 — 期刊級聚合指標儀表板
//
// 依國際期刊圖表/統計規範重構：
//   - 連續資料一律箱形圖（median/IQR/whisker/離群），不用長條圖遮蔽分佈
//     （Weissgerber 2015 PLOS Biology；Nature/eLife 已要求）
//   - 比例附 Wilson 95% CI 誤差線 + 分子/分母（SAMPL 統計報告指引）
//   - 各語言子群比較用森林圖 + 整體參考線（Lancet/JAMA 慣例）
//   - Figure 編號 + caption + n= + 每圖可下載向量 SVG（投稿用）
//   - Table 1 病患基線特徵（臨床論文必備）
//
// 即時性：訂閱 dashboard WS report_generated / session_status_changed，
// 每場問診結束 debounce 1.5s 自動 refetch。
// =============================================================================

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getResearchAnalytics } from '../../services/api/research';
import { useDashboardWebSocket } from '../../hooks/useWebSocket';
import type {
  NumericSummary,
  Proportion,
  ResearchAnalyticsResponse,
} from '../../types/api';
import {
  BoxPlotGroup,
  FigureCard,
  ForestPlot,
  HistogramChart,
  ProportionRow,
  StackedShareBar,
  WeeklyTrendChart,
  type BoxRow,
} from './research/charts';

const SEVERITY_COLOR: Record<string, string> = { critical: '#dc2626', high: '#ea580c', medium: '#d97706' };
const REVIEW_COLOR: Record<string, string> = { approved: '#16a34a', revision_needed: '#d97706', pending: '#64748b' };
const REFETCH_DEBOUNCE_MS = 1500;

// ── 格式 helpers ─────────────────────────────────────────
function pct(v: number | null | undefined, d = 1): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`;
}
function propText(p: Proportion): string {
  if (p.value === null) return '—';
  const ci = p.ciLow !== null && p.ciHigh !== null ? ` (95% CI ${(p.ciLow * 100).toFixed(1)}–${(p.ciHigh * 100).toFixed(1)})` : '';
  return `${(p.value * 100).toFixed(1)}%${ci}`;
}
function iqr(s: NumericSummary, fmt: (v: number) => string): string {
  if (!s || s.n === 0 || s.median === null) return '—';
  return `${fmt(s.median)} (${fmt(s.p25 ?? 0)}–${fmt(s.p75 ?? 0)})`;
}
function meanSd(s: NumericSummary, fmt: (v: number) => string): string {
  if (!s || s.n === 0 || s.mean === null) return '—';
  return `${fmt(s.mean)} ± ${fmt(s.sd ?? 0)}`;
}

// ── 共用小元件 ───────────────────────────────────────────
function StatTile({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-panel border border-edge bg-white p-4 shadow-card dark:border-dark-border dark:bg-dark-card">
      <p className="text-small font-semibold text-ink-secondary">{label}</p>
      <p className="mt-2 text-h1 font-bold text-ink-heading dark:text-white">{value}</p>
      {helper ? <p className="mt-1 text-caption text-ink-muted">{helper}</p> : null}
    </div>
  );
}

function Card({ title, subtitle, badge, children }: { title: string; subtitle?: string; badge?: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">{title}</h2>
          {subtitle ? <p className="mt-1 text-small text-ink-muted">{subtitle}</p> : null}
        </div>
        {badge ? (
          <span className="shrink-0 rounded-pill bg-surface-tertiary px-3 py-1 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">{badge}</span>
        ) : null}
      </div>
      <div className="mt-5">{children}</div>
    </div>
  );
}

function EmptyBox({ label }: { label: string }) {
  return <p className="rounded-card border border-dashed border-edge px-4 py-8 text-center text-small text-ink-muted dark:border-dark-border">{label}</p>;
}

export default function ResearchAnalyticsPage() {
  const { t, i18n } = useTranslation('research');
  const { on, off } = useDashboardWebSocket();
  const [data, setData] = useState<ResearchAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await getResearchAnalytics();
      setData(res);
      setError(false);
      setLastUpdated(new Date());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    const scheduleRefetch = () => {
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
      refetchTimer.current = setTimeout(fetchData, REFETCH_DEBOUNCE_MS);
    };
    on('report_generated', scheduleRefetch);
    on('session_status_changed', scheduleRefetch);
    return () => {
      off('report_generated');
      off('session_status_changed');
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
    };
  }, [on, off, fetchData]);

  const nf = (v: number) => v.toLocaleString(i18n.language);
  const emptyLabel = t('page.empty');

  if (loading) return <div className="flex h-64 items-center justify-center text-small text-ink-muted">{t('page.loading')}</div>;
  if (error || !data) return <div className="flex h-64 items-center justify-center text-small text-ink-muted">{t('page.error')}</div>;

  const { cohort, demographics, efficiency, historyTaking, safety, sttQuality, documentation, byLanguage } = data;
  const terminal = cohort.completed + cohort.abortedRedFlag;

  const severityLabels: Record<string, string> = { critical: t('safety.severity.critical'), high: t('safety.severity.high'), medium: t('safety.severity.medium') };
  const layerLabels: Record<string, string> = { rule_hit: t('safety.layer.rule_hit'), semantic_only: t('safety.layer.semantic_only'), uncovered_locale: t('safety.layer.uncovered_locale') };
  const urgencyLabels: Record<string, string> = { er_now: t('safety.urgency.er_now'), '24h': t('safety.urgency.24h'), this_week: t('safety.urgency.this_week'), routine: t('safety.urgency.routine') };
  const reviewLabels: Record<string, string> = { approved: t('documentation.outcomes.approved'), revision_needed: t('documentation.outcomes.revision_needed'), pending: t('documentation.outcomes.pending') };
  const genderLabels: Record<string, string> = { male: t('demographics.gender.male'), female: t('demographics.gender.female'), other: t('demographics.gender.other') };

  // 效率箱形圖三列（分佈，非長條）
  const efficiencyRows: BoxRow[] = [
    { key: 'duration', label: t('efficiency.duration'), summary: efficiency.durationSeconds, unit: t('page.minutesShort'), transform: (v) => v / 60 },
    { key: 'turns', label: t('efficiency.turns'), summary: efficiency.patientTurns },
    { key: 'chars', label: t('efficiency.chars'), summary: efficiency.patientTurnChars },
  ];

  return (
    <div className="space-y-6">
      {/* 頁首 */}
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-tiny font-semibold uppercase tracking-wide text-primary-600">{t('page.eyebrow')}</p>
          <h1 className="mt-1 text-h1 font-bold text-ink-heading dark:text-white">{t('page.title')}</h1>
          <p className="mt-1 text-small text-ink-muted">{t('page.subtitle')}</p>
        </div>
        <div className="text-right">
          <p className="text-tiny text-ink-muted">{t('page.autoUpdate')}</p>
          {lastUpdated ? (
            <p className="mt-0.5 text-tiny text-ink-secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {t('page.updatedAt')} {lastUpdated.toLocaleTimeString(i18n.language)}
            </p>
          ) : null}
        </div>
      </div>

      {/* KPI 列 — headline numbers with CI */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatTile label={t('kpi.sessions')} value={nf(cohort.totalSessions)} helper={t('kpi.patients', { count: demographics.totalPatients })} />
        <StatTile label={t('kpi.completionRate')} value={pct(cohort.completion.value)} helper={`${nf(cohort.completed)}/${nf(cohort.totalSessions)}`} />
        <StatTile label={t('kpi.redFlagRate')} value={pct(safety.alertSession.value)} helper={t('kpi.redFlagRateHelper', { count: safety.alertSession.numerator, terminal })} />
        <StatTile label={t('kpi.medianDuration')} value={`${efficiency.durationSeconds.median !== null ? (efficiency.durationSeconds.median / 60).toFixed(1) : '—'} ${t('page.minutesShort')}`} helper={`IQR ${efficiency.durationSeconds.p25 !== null ? (efficiency.durationSeconds.p25 / 60).toFixed(1) : '—'}–${efficiency.durationSeconds.p75 !== null ? (efficiency.durationSeconds.p75 / 60).toFixed(1) : '—'}`} />
        <StatTile label={t('kpi.hpiCompleteness')} value={pct(historyTaking.meanHpiCompleteness)} helper={t('kpi.hpiCompletenessHelper', { count: historyTaking.reportsAnalyzed })} />
        <StatTile label={t('kpi.agreementRate')} value={pct(documentation.physicianAgreement.value)} helper={t('kpi.agreementRateHelper')} />
      </div>

      {/* Table 1 — 病患基線特徵 */}
      <Card title={t('demographics.title')} subtitle={t('demographics.subtitle')} badge={t('demographics.badge', { count: demographics.totalPatients })}>
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="overflow-x-auto">
            <table className="w-full text-small">
              <tbody>
                <tr className="border-b border-edge dark:border-dark-border">
                  <td className="py-2 pr-4 text-ink-secondary">{t('demographics.age')}</td>
                  <td className="py-2 text-right font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {iqr(demographics.ageYears, (v) => v.toFixed(0))} <span className="ml-1 text-tiny font-normal text-ink-muted">({t('demographics.medianIqr')})</span>
                  </td>
                </tr>
                <tr className="border-b border-edge dark:border-dark-border">
                  <td className="py-2 pr-4 text-ink-secondary">{t('demographics.ageMeanSd')}</td>
                  <td className="py-2 text-right font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {meanSd(demographics.ageYears, (v) => v.toFixed(1))}
                  </td>
                </tr>
                {demographics.genderDistribution.map((g) => (
                  <tr key={g.key} className="border-b border-edge last:border-0 dark:border-dark-border">
                    <td className="py-2 pr-4 text-ink-secondary">{genderLabels[g.key] ?? g.key}</td>
                    <td className="py-2 text-right font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {g.count} ({pct(demographics.totalPatients ? g.count / demographics.totalPatients : null, 0)})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <p className="mb-2 text-small font-semibold text-ink-secondary">{t('demographics.ageBands')}</p>
            <div className="grid gap-2">
              {demographics.ageBandDistribution.map((b) => {
                const maxBand = Math.max(...demographics.ageBandDistribution.map((x) => x.count), 1);
                return (
                  <div key={b.key} className="flex items-center gap-3">
                    <span className="w-14 shrink-0 text-small text-ink-body dark:text-dark-text-muted">{b.key}</span>
                    <div className="h-4 flex-1 rounded-r-[4px] bg-surface-tertiary dark:bg-dark-surface">
                      <div className="h-4 rounded-r-[4px] bg-primary-600" style={{ width: `${(b.count / maxBand) * 100}%` }} />
                    </div>
                    <span className="w-8 shrink-0 text-right text-small font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{b.count}</span>
                  </div>
                );
              })}
            </div>
            <p className="mb-2 mt-4 text-small font-semibold text-ink-secondary">{t('demographics.caseMix')}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {demographics.chiefComplaintDistribution.slice(0, 8).map((c) => (
                <span key={c.key} className="text-tiny text-ink-secondary">
                  {c.key} <span className="font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{c.count}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </Card>

      {/* Figure 1 — 收案流與週趨勢 */}
      <FigureCard
        figureLabel={t('fig.one')}
        title={t('cohort.title')}
        caption={t('cohort.subtitle')}
        downloadName="figure1_cohort_flow"
        footnote={t('cohort.footnote', { total: cohort.totalSessions, completed: cohort.completed, aborted: cohort.abortedRedFlag, cancelled: cohort.cancelled })}
      >
        {cohort.weeklyTrend.length > 0 ? (
          <WeeklyTrendChart items={cohort.weeklyTrend} labels={{ sessions: t('cohort.seriesSessions'), completed: t('cohort.seriesCompleted') }} />
        ) : (
          <EmptyBox label={emptyLabel} />
        )}
      </FigureCard>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* Figure 2 — 效率箱形圖 */}
        <FigureCard figureLabel={t('fig.two')} title={t('efficiency.title')} caption={t('efficiency.subtitle')} downloadName="figure2_efficiency_boxplots" footnote={t('efficiency.footnote')}>
          {efficiency.durationSeconds.n > 0 ? (
            <BoxPlotGroup rows={efficiencyRows} formatTick={(v) => v.toFixed(v < 10 ? 1 : 0)} />
          ) : (
            <EmptyBox label={emptyLabel} />
          )}
        </FigureCard>

        {/* Figure 3 — HPI 完整度（比例 + CI）*/}
        <FigureCard figureLabel={t('fig.three')} title={t('hpi.title')} caption={t('hpi.subtitle')} downloadName="figure3_hpi_completeness" footnote={t('hpi.footnote', { count: historyTaking.reportsAnalyzed })}>
          {historyTaking.reportsAnalyzed > 0 ? (
            <div className="grid gap-2">
              {historyTaking.hpiFieldFillRates.map((f) => (
                <ProportionRow
                  key={f.field}
                  label={t(`hpi.fields.${f.field}`)}
                  prop={{ numerator: f.filled, denominator: f.total, value: f.rate, ciLow: null, ciHigh: null }}
                />
              ))}
            </div>
          ) : (
            <EmptyBox label={emptyLabel} />
          )}
        </FigureCard>

        {/* Figure 4 — Triage 安全 */}
        <FigureCard figureLabel={t('fig.four')} title={t('safety.title')} caption={t('safety.subtitle')} downloadName="figure4_triage_safety" footnote={t('safety.footnote')}>
          <div className="grid gap-5">
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.keyRates')}</p>
              <div className="grid gap-2">
                <ProportionRow label={t('safety.alertRate')} prop={safety.alertSession} color="#dc2626" />
                <ProportionRow label={t('safety.ackRate')} prop={safety.acknowledged} color="#16a34a" />
              </div>
            </div>
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.severityTitle')}</p>
              <StackedShareBar buckets={safety.severityDistribution} labels={severityLabels} colors={SEVERITY_COLOR} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('safety.timeToFirstAlert')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {iqr(safety.timeToFirstAlertSeconds, (v) => `${Math.round(v)}s`)}
                </p>
              </div>
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('safety.ackLatency')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {iqr(safety.ackLatencySeconds, (v) => `${(v / 60).toFixed(1)}m`)}
                </p>
              </div>
            </div>
          </div>
        </FigureCard>

        {/* Figure 5 — SOAP 緊急度 + 偵測層 */}
        <FigureCard figureLabel={t('fig.five')} title={t('safety.urgencyTitle')} caption={t('safety.urgencySubtitle')} downloadName="figure5_urgency_layer">
          <div className="grid gap-5">
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.urgencyTitle')}</p>
              <StackedShareBar
                buckets={safety.urgencyDistribution}
                labels={urgencyLabels}
                colors={{ er_now: '#1e40af', '24h': '#2563eb', this_week: '#3b82f6', routine: '#60a5fa' }}
              />
            </div>
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.layerTitle')}</p>
              <StackedShareBar
                buckets={safety.layerDistribution}
                labels={layerLabels}
                colors={{ rule_hit: '#2563eb', semantic_only: '#f59e0b', uncovered_locale: '#dc2626' }}
              />
            </div>
          </div>
        </FigureCard>

        {/* Figure 6 — STT 品質分佈 */}
        <FigureCard figureLabel={t('fig.six')} title={t('stt.title')} caption={t('stt.subtitle')} downloadName="figure6_stt_quality" footnote={t('stt.footnote', { count: sttQuality.turnsWithConfidence })}>
          {sttQuality.turnsWithConfidence > 0 ? (
            <>
              <HistogramChart buckets={sttQuality.histogram} bucketLabel={(b) => b.start.toFixed(1)} countLabel={t('stt.turns')} />
              <div className="mt-3 grid grid-cols-3 gap-3">
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.medianConfidence')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{iqr(sttQuality.confidenceSummary, (v) => v.toFixed(2))}</p>
                </div>
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.lowConfidence')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{pct(sttQuality.lowConfidence.value)}</p>
                </div>
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.voiceShare')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{pct(sttQuality.voiceTurnShare)}</p>
                </div>
              </div>
            </>
          ) : (
            <EmptyBox label={emptyLabel} />
          )}
        </FigureCard>

        {/* Figure 7 — AI 文件品質 */}
        <FigureCard figureLabel={t('fig.seven')} title={t('documentation.title')} caption={t('documentation.subtitle')} downloadName="figure7_documentation_quality" footnote={t('documentation.footnote', { count: documentation.reportsGenerated })}>
          <div className="grid gap-5">
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('documentation.outcomesTitle')}</p>
              <StackedShareBar buckets={documentation.reviewOutcomes} labels={reviewLabels} colors={REVIEW_COLOR} />
            </div>
            <div className="grid gap-2">
              <ProportionRow label={t('documentation.agreement')} prop={documentation.physicianAgreement} color="#16a34a" />
              <ProportionRow label={t('documentation.icdVerified')} prop={documentation.icd10Verified} color="#2563eb" />
            </div>
            <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
              <p className="text-tiny text-ink-muted">{t('documentation.aiConfidence')}</p>
              <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white" style={{ fontVariantNumeric: 'tabular-nums' }}>{iqr(documentation.aiConfidenceSummary, (v) => v.toFixed(2))}</p>
            </div>
          </div>
        </FigureCard>
      </div>

      {/* Figure 8 — 各語言子群森林圖 */}
      <FigureCard
        figureLabel={t('fig.eight')}
        title={t('forest.title')}
        caption={t('forest.subtitle')}
        downloadName="figure8_language_subgroup_forest"
        footnote={t('forest.footnote')}
      >
        {byLanguage.length > 0 ? (
          <ForestPlot
            rows={byLanguage.map((b) => ({ label: `${b.language} (n=${b.sessions})`, prop: b.redFlagRate }))}
            overall={safety.alertSession.value}
            overallLabel={t('forest.overall')}
            xLabel={t('forest.xLabel')}
          />
        ) : (
          <EmptyBox label={emptyLabel} />
        )}
      </FigureCard>

      {/* 各語言子群 — 完整 table view（無障礙後援） */}
      <Card title={t('table.title')} subtitle={t('table.subtitle')}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-small">
            <thead>
              <tr className="border-b border-edge text-left text-tiny uppercase tracking-wide text-ink-muted dark:border-dark-border">
                <th className="py-2 pr-4 font-semibold">{t('table.language')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.sessions')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.completed')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.medianDuration')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.meanTurns')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.medianConfidence')}</th>
                <th className="py-2 font-semibold">{t('table.redFlagRate')}</th>
              </tr>
            </thead>
            <tbody>
              {byLanguage.map((row) => (
                <tr key={row.language} className="border-b border-edge last:border-0 dark:border-dark-border">
                  <td className="py-2.5 pr-4 font-semibold text-ink-heading dark:text-white">{row.language}</td>
                  <td className="py-2.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}>{nf(row.sessions)}</td>
                  <td className="py-2.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}>{nf(row.completed)}</td>
                  <td className="py-2.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}>{row.medianDurationSeconds === null ? '—' : `${(row.medianDurationSeconds / 60).toFixed(1)} ${t('page.minutesShort')}`}</td>
                  <td className="py-2.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}>{row.meanPatientTurns ?? '—'}</td>
                  <td className="py-2.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}>{row.meanSttConfidence ?? '—'}</td>
                  <td className="py-2.5" style={{ fontVariantNumeric: 'tabular-nums' }}>{propText(row.redFlagRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Methods — 發表對照 */}
      <Card title={t('methods.title')} subtitle={t('methods.subtitle')}>
        <ul className="grid gap-2 text-small text-ink-body dark:text-dark-text-muted lg:grid-cols-2">
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border"><span className="font-semibold text-ink-heading dark:text-white">DECIDE-AI</span> — {t('methods.decideAi')}</li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border"><span className="font-semibold text-ink-heading dark:text-white">AMIE (Nature 2025)</span> — {t('methods.amie')}</li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border"><span className="font-semibold text-ink-heading dark:text-white">{t('methods.triageLabel')}</span> — {t('methods.triage')}</li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border"><span className="font-semibold text-ink-heading dark:text-white">PDQI-9</span> — {t('methods.pdqi')}</li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border lg:col-span-2"><span className="font-semibold text-ink-heading dark:text-white">{t('methods.statsLabel')}</span> — {t('methods.stats')}</li>
        </ul>
        <p className="mt-3 text-tiny text-ink-muted">{t('methods.disclaimer')}</p>
      </Card>
    </div>
  );
}
