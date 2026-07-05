// =============================================================================
// 研究分析頁 — 發表級聚合指標儀表板
//
// 指標框架對齊國際期刊常用評估標準（見頁尾 Methods 卡）：
//   DECIDE-AI（早期臨床評估報告指引）、AMIE 病史採集評估軸、
//   症狀檢查器 triage 安全文獻、PDQI-9 文件品質（醫師審閱 proxy）。
//
// 即時性：訂閱 dashboard WS 的 report_generated / session_status_changed，
// 每場問診結束（或報告生成）後 debounce 重新抓取 → 圖表自動更新。
//
// 圖表規格（dataviz 方法）：bar ≤24px、資料端 4px 圓角、2px surface gap、
// 2 系列折線配 legend + ≥8px 端點（2px surface ring）、hover tooltip、
// 文字一律 ink tokens、調色盤已跑 validate_palette（light + dark 雙面）。
// =============================================================================

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getResearchAnalytics } from '../../services/api/research';
import { useDashboardWebSocket } from '../../hooks/useWebSocket';
import type {
  DistributionBucket,
  HistogramBucket,
  NumericSummary,
  ResearchAnalyticsResponse,
} from '../../types/api';

// 已驗證調色盤（validate_palette PASS：light #ffffff / dark #1e2330）
const SERIES = { blue: '#2563eb', green: '#16a34a' };
// urgency ordinal ramp（單色 monotone，validate --ordinal PASS）
const URGENCY_RAMP: Record<string, string> = {
  er_now: '#1e40af',
  '24h': '#2563eb',
  this_week: '#3b82f6',
  routine: '#60a5fa',
};
// 嚴重度沿用產品 status 色（reserved meaning，恆帶文字標籤）
const SEVERITY_COLOR: Record<string, string> = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#d97706',
};
const REVIEW_COLOR: Record<string, string> = {
  approved: '#16a34a',
  revision_needed: '#d97706',
  pending: '#64748b',
};

const REFETCH_DEBOUNCE_MS = 1500;

// ── 格式 helpers ─────────────────────────────────────────

function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

function fixed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—';
  return v.toFixed(digits);
}

function minutes(seconds: number | null | undefined, digits = 1): string {
  if (seconds === null || seconds === undefined) return '—';
  return (seconds / 60).toFixed(digits);
}

function iqrText(s: NumericSummary, fmt: (v: number | null) => string): string {
  if (!s || s.n === 0) return '—';
  return `${fmt(s.median)} (${fmt(s.p25)}–${fmt(s.p75)})`;
}

// ── 共用小元件 ───────────────────────────────────────────

function SectionCard({
  title,
  subtitle,
  children,
  badge,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  badge?: string;
}) {
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">{title}</h2>
          {subtitle ? <p className="mt-1 text-small text-ink-muted">{subtitle}</p> : null}
        </div>
        {badge ? (
          <span className="shrink-0 rounded-pill bg-surface-tertiary px-3 py-1 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
            {badge}
          </span>
        ) : null}
      </div>
      <div className="mt-5">{children}</div>
    </div>
  );
}

function StatTile({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper?: string;
}) {
  return (
    <div className="rounded-panel border border-edge bg-white p-4 shadow-card dark:border-dark-border dark:bg-dark-card">
      <p className="text-small font-semibold text-ink-secondary">{label}</p>
      <p className="mt-2 text-h1 font-bold text-ink-heading dark:text-white">{value}</p>
      {helper ? <p className="mt-1 text-caption text-ink-muted">{helper}</p> : null}
    </div>
  );
}

/** hover tooltip 容器：由各圖表把 hovered 資訊丟進來 */
function HoverTip({ tip }: { tip: { x: number; y: number; lines: string[] } | null }) {
  if (!tip) return null;
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-card border border-edge bg-white px-3 py-2 text-tiny text-ink-body shadow-card dark:border-dark-border dark:bg-dark-card dark:text-dark-text-muted"
      style={{ left: tip.x, top: tip.y - 8 }}
    >
      {tip.lines.map((l) => (
        <p key={l} className="whitespace-nowrap font-tnum">
          {l}
        </p>
      ))}
    </div>
  );
}

type Tip = { x: number; y: number; lines: string[] } | null;

function useTip(): [Tip, (e: React.MouseEvent, lines: string[]) => void, () => void] {
  const [tip, setTip] = useState<Tip>(null);
  const show = useCallback((e: React.MouseEvent, lines: string[]) => {
    const host = (e.currentTarget as HTMLElement).closest('[data-tip-host]');
    if (!host) return;
    const rect = host.getBoundingClientRect();
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, lines });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  return [tip, show, hide];
}

/** 橫向長條圖（單系列 → 單色，資料端 4px 圓角；值標在條尾） */
function HBarChart({
  rows,
  color,
  colorByKey,
  valueText,
}: {
  rows: { key: string; label: string; value: number; max: number; display: string }[];
  color?: string;
  colorByKey?: Record<string, string>;
  valueText?: string;
}) {
  const [tip, show, hide] = useTip();
  return (
    <div className="relative" data-tip-host>
      <HoverTip tip={tip} />
      <div className="grid gap-2.5">
        {rows.map((r) => {
          const w = r.max > 0 ? Math.max((r.value / r.max) * 100, r.value > 0 ? 2 : 0) : 0;
          const fill = colorByKey?.[r.key] ?? color ?? SERIES.blue;
          return (
            <div key={r.key} className="flex items-center gap-3">
              <span className="w-32 shrink-0 truncate text-small text-ink-body dark:text-dark-text-muted">
                {r.label}
              </span>
              <div
                className="relative h-5 flex-1 cursor-default rounded-r-[4px] bg-surface-tertiary dark:bg-dark-surface"
                onMouseMove={(e) => show(e, [`${r.label}: ${r.display}${valueText ? ` ${valueText}` : ''}`])}
                onMouseLeave={hide}
              >
                <div
                  className="absolute inset-y-0 left-0 rounded-r-[4px]"
                  style={{ width: `${w}%`, backgroundColor: fill }}
                />
              </div>
              <span className="w-16 shrink-0 text-right text-small font-semibold text-ink-heading dark:text-white font-tnum">
                {r.display}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 直方圖（單色柱；資料端 4px 圓角、柱間留 gap） */
function HistogramChart({
  buckets,
  bucketLabel,
  countLabel,
}: {
  buckets: HistogramBucket[];
  bucketLabel: (b: HistogramBucket) => string;
  countLabel: string;
}) {
  const [tip, show, hide] = useTip();
  const max = Math.max(...buckets.map((b) => b.count), 1);
  return (
    <div className="relative" data-tip-host>
      <HoverTip tip={tip} />
      <div className="flex h-40 items-end gap-[2px]">
        {buckets.map((b, i) => {
          const h = b.count > 0 ? Math.max((b.count / max) * 100, 4) : 0;
          return (
            <div
              key={i}
              className="flex h-full flex-1 cursor-default flex-col items-center justify-end"
              onMouseMove={(e) => show(e, [bucketLabel(b), `${countLabel}: ${b.count}`])}
              onMouseLeave={hide}
            >
              {b.count > 0 ? (
                <span className="mb-1 text-[10px] text-ink-muted font-tnum">{b.count}</span>
              ) : null}
              <div
                className="w-full max-w-[24px] rounded-t-[4px]"
                style={{ height: `${h}%`, backgroundColor: SERIES.blue }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-ink-muted font-tnum">
        <span>{buckets.length ? bucketLabel(buckets[0]).split('–')[0] : ''}</span>
        <span>{buckets.length ? bucketLabel(buckets[buckets.length - 1]) : ''}</span>
      </div>
    </div>
  );
}

/** 週趨勢折線（2 系列 + legend；端點 8px、2px surface ring） */
function WeeklyTrendChart({
  items,
  seriesLabels,
  redFlagLabel,
}: {
  items: ResearchAnalyticsResponse['cohort']['weeklyTrend'];
  seriesLabels: { sessions: string; completed: string };
  redFlagLabel: string;
}) {
  const [tip, show, hide] = useTip();
  const W = 720;
  const H = 200;
  const PAD = { l: 30, r: 12, t: 12, b: 24 };
  const max = Math.max(...items.map((i) => i.sessions), 1);
  const x = (i: number) =>
    PAD.l + (items.length <= 1 ? 0 : (i / (items.length - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => H - PAD.b - (v / max) * (H - PAD.t - PAD.b);
  const path = (get: (it: (typeof items)[number]) => number) =>
    items.map((it, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(get(it)).toFixed(1)}`).join(' ');
  const gridVals = [0, Math.ceil(max / 2), max];

  return (
    <div className="relative" data-tip-host>
      <HoverTip tip={tip} />
      <div className="flex items-center gap-4 text-tiny text-ink-secondary">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: SERIES.blue }} />
          {seriesLabels.sessions}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: SERIES.green }} />
          {seriesLabels.completed}
        </span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[560px]" role="img">
          {gridVals.map((g) => (
            <g key={g}>
              <line
                x1={PAD.l}
                x2={W - PAD.r}
                y1={y(g)}
                y2={y(g)}
                className="stroke-edge dark:stroke-dark-border"
                strokeWidth="1"
              />
              <text
                x={PAD.l - 6}
                y={y(g) + 3}
                textAnchor="end"
                className="fill-ink-muted text-[10px] font-tnum"
              >
                {g}
              </text>
            </g>
          ))}
          <path d={path((it) => it.sessions)} fill="none" stroke={SERIES.blue} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          <path d={path((it) => it.completed)} fill="none" stroke={SERIES.green} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {items.map((it, i) => (
            <g key={it.weekStart}>
              {/* 8px 端點 + 2px surface ring */}
              <circle cx={x(i)} cy={y(it.sessions)} r="4" fill={SERIES.blue} className="stroke-white dark:stroke-dark-card" strokeWidth="2" />
              <circle cx={x(i)} cy={y(it.completed)} r="4" fill={SERIES.green} className="stroke-white dark:stroke-dark-card" strokeWidth="2" />
              {/* hover 命中區（比 mark 大） */}
              <rect
                x={x(i) - (items.length > 1 ? (W - PAD.l - PAD.r) / (items.length - 1) / 2 : W / 2)}
                y={PAD.t}
                width={items.length > 1 ? (W - PAD.l - PAD.r) / (items.length - 1) : W}
                height={H - PAD.t - PAD.b}
                fill="transparent"
                onMouseMove={(e) =>
                  show(e, [
                    it.weekStart,
                    `${seriesLabels.sessions}: ${it.sessions}`,
                    `${seriesLabels.completed}: ${it.completed}`,
                    `${redFlagLabel}: ${it.redFlagSessions}`,
                  ])
                }
                onMouseLeave={hide}
              />
              <text x={x(i)} y={H - 8} textAnchor="middle" className="fill-ink-muted text-[10px] font-tnum">
                {it.weekStart.slice(5)}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

/** 部分-整體橫向堆疊條（2px surface gap；legend + 計數） */
function StackedShareBar({
  buckets,
  labels,
  colors,
}: {
  buckets: DistributionBucket[];
  labels: Record<string, string>;
  colors: Record<string, string>;
}) {
  const total = buckets.reduce((s, b) => s + b.count, 0);
  return (
    <div>
      <div className="flex h-5 w-full gap-[2px] overflow-hidden rounded-[4px]">
        {total > 0 ? (
          buckets
            .filter((b) => b.count > 0)
            .map((b) => (
              <div
                key={b.key}
                style={{ width: `${(b.count / total) * 100}%`, backgroundColor: colors[b.key] ?? '#64748b' }}
              />
            ))
        ) : (
          <div className="w-full bg-surface-tertiary dark:bg-dark-surface" />
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {buckets.map((b) => (
          <span key={b.key} className="flex items-center gap-1.5 text-tiny text-ink-secondary">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[b.key] ?? '#64748b' }} />
            {labels[b.key] ?? b.key}
            <span className="font-semibold text-ink-heading dark:text-white font-tnum">
              {b.count}
            </span>
            <span className="text-ink-muted font-tnum">
              ({total > 0 ? `${Math.round((b.count / total) * 100)}%` : '—'})
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── 主頁面 ──────────────────────────────────────────────

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

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 每場問診結束 / 報告生成 → debounce 重新聚合（多事件叢發只抓一次）
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

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-small text-ink-muted">
        {t('page.loading')}
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-small text-ink-muted">
        {t('page.error')}
      </div>
    );
  }

  const { cohort, efficiency, historyTaking, safety, sttQuality, documentation, byLanguage } = data;
  const terminal = cohort.completed + cohort.abortedRedFlag;

  const severityLabels: Record<string, string> = {
    critical: t('safety.severity.critical'),
    high: t('safety.severity.high'),
    medium: t('safety.severity.medium'),
  };
  const layerLabels: Record<string, string> = {
    rule_hit: t('safety.layer.rule_hit'),
    semantic_only: t('safety.layer.semantic_only'),
    uncovered_locale: t('safety.layer.uncovered_locale'),
  };
  const urgencyLabels: Record<string, string> = {
    er_now: t('safety.urgency.er_now'),
    '24h': t('safety.urgency.24h'),
    this_week: t('safety.urgency.this_week'),
    routine: t('safety.urgency.routine'),
  };
  const reviewLabels: Record<string, string> = {
    approved: t('documentation.outcomes.approved'),
    revision_needed: t('documentation.outcomes.revision_needed'),
    pending: t('documentation.outcomes.pending'),
  };

  const hpiMax = Math.max(...historyTaking.hpiFieldFillRates.map((f) => f.rate ?? 0), 0.0001);

  return (
    <div className="space-y-6">
      {/* 頁首 */}
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-tiny font-semibold uppercase tracking-wide text-primary-600">
            {t('page.eyebrow')}
          </p>
          <h1 className="mt-1 text-h1 font-bold text-ink-heading dark:text-white">
            {t('page.title')}
          </h1>
          <p className="mt-1 text-small text-ink-muted">{t('page.subtitle')}</p>
        </div>
        <div className="text-right">
          <p className="text-tiny text-ink-muted">
            {t('page.autoUpdate')}
          </p>
          {lastUpdated ? (
            <p className="mt-0.5 text-tiny text-ink-secondary font-tnum">
              {t('page.updatedAt')} {lastUpdated.toLocaleTimeString(i18n.language)}
            </p>
          ) : null}
        </div>
      </div>

      {/* KPI 列（headline numbers → stat tiles，非圖表） */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatTile label={t('kpi.sessions')} value={nf(cohort.totalSessions)} helper={t('kpi.sessionsHelper')} />
        <StatTile label={t('kpi.completionRate')} value={pct(cohort.completionRate)} helper={`${nf(cohort.completed)}/${nf(cohort.totalSessions)}`} />
        <StatTile label={t('kpi.redFlagRate')} value={pct(safety.alertSessionRate)} helper={t('kpi.redFlagRateHelper', { count: safety.sessionsWithAlerts, terminal })} />
        <StatTile label={t('kpi.medianDuration')} value={`${minutes(efficiency.durationSeconds.median)} ${t('page.minutesShort')}`} helper={`IQR ${minutes(efficiency.durationSeconds.p25)}–${minutes(efficiency.durationSeconds.p75)}`} />
        <StatTile label={t('kpi.hpiCompleteness')} value={pct(historyTaking.meanHpiCompleteness)} helper={t('kpi.hpiCompletenessHelper', { count: historyTaking.reportsAnalyzed })} />
        <StatTile label={t('kpi.agreementRate')} value={pct(documentation.physicianAgreementRate)} helper={t('kpi.agreementRateHelper')} />
      </div>

      {/* 收案流 + 週趨勢 */}
      <SectionCard
        title={t('cohort.title')}
        subtitle={t('cohort.subtitle')}
        badge={t('cohort.badge', { total: nf(cohort.totalSessions) })}
      >
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{t('cohort.completed')}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">{nf(cohort.completed)}</p>
          </div>
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{t('cohort.abortedRedFlag')}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">{nf(cohort.abortedRedFlag)}</p>
          </div>
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{t('cohort.cancelled')}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">{nf(cohort.cancelled)}</p>
          </div>
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{t('cohort.active')}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">{nf(cohort.inProgressOrWaiting)}</p>
          </div>
        </div>
        {cohort.weeklyTrend.length > 0 ? (
          <WeeklyTrendChart
            items={cohort.weeklyTrend}
            seriesLabels={{ sessions: t('cohort.seriesSessions'), completed: t('cohort.seriesCompleted') }}
            redFlagLabel={t('cohort.redFlagWeek')}
          />
        ) : (
          <p className="rounded-card border border-dashed border-edge px-4 py-8 text-center text-small text-ink-muted dark:border-dark-border">
            {t('page.empty')}
          </p>
        )}
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* HPI 完整度（AMIE 病史採集軸） */}
        <SectionCard
          title={t('hpi.title')}
          subtitle={t('hpi.subtitle')}
          badge={t('hpi.badge', { count: historyTaking.reportsAnalyzed })}
        >
          {historyTaking.reportsAnalyzed > 0 ? (
            <HBarChart
              rows={historyTaking.hpiFieldFillRates.map((f) => ({
                key: f.field,
                label: t(`hpi.fields.${f.field}`),
                value: f.rate ?? 0,
                max: hpiMax,
                display: pct(f.rate, 0),
              }))}
              color={SERIES.blue}
            />
          ) : (
            <p className="rounded-card border border-dashed border-edge px-4 py-8 text-center text-small text-ink-muted dark:border-dark-border">
              {t('page.empty')}
            </p>
          )}
        </SectionCard>

        {/* Triage 安全 */}
        <SectionCard title={t('safety.title')} subtitle={t('safety.subtitle')}>
          <div className="grid gap-5">
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.severityTitle')}</p>
              <HBarChart
                rows={safety.severityDistribution.map((b) => ({
                  key: b.key,
                  label: severityLabels[b.key] ?? b.key,
                  value: b.count,
                  max: Math.max(...safety.severityDistribution.map((x) => x.count), 1),
                  display: String(b.count),
                }))}
                colorByKey={SEVERITY_COLOR}
              />
            </div>
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('safety.layerTitle')}</p>
              <HBarChart
                rows={safety.layerDistribution.map((b) => ({
                  key: b.key,
                  label: layerLabels[b.key] ?? b.key,
                  value: b.count,
                  max: Math.max(...safety.layerDistribution.map((x) => x.count), 1),
                  display: String(b.count),
                }))}
                color={SERIES.blue}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('safety.timeToFirstAlert')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {iqrText(safety.timeToFirstAlertSeconds, (v) => (v === null ? '—' : `${Math.round(v)}s`))}
                </p>
              </div>
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('safety.ackRate')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {pct(safety.acknowledgedRate)}
                </p>
              </div>
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('safety.ackLatency')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {iqrText(safety.ackLatencySeconds, (v) => (v === null ? '—' : `${minutes(v)}m`))}
                </p>
              </div>
            </div>
          </div>
        </SectionCard>

        {/* SOAP 建議緊急度（ordinal ramp） */}
        <SectionCard title={t('safety.urgencyTitle')} subtitle={t('safety.urgencySubtitle')}>
          <HBarChart
            rows={safety.urgencyDistribution.map((b) => ({
              key: b.key,
              label: urgencyLabels[b.key] ?? b.key,
              value: b.count,
              max: Math.max(...safety.urgencyDistribution.map((x) => x.count), 1),
              display: String(b.count),
            }))}
            colorByKey={URGENCY_RAMP}
          />
        </SectionCard>

        {/* STT 品質 */}
        <SectionCard
          title={t('stt.title')}
          subtitle={t('stt.subtitle')}
          badge={t('stt.badge', { count: sttQuality.turnsWithConfidence })}
        >
          {sttQuality.turnsWithConfidence > 0 ? (
            <>
              <HistogramChart
                buckets={sttQuality.histogram}
                bucketLabel={(b) => `${b.start.toFixed(1)}–${b.end.toFixed(1)}`}
                countLabel={t('stt.turns')}
              />
              <div className="mt-4 grid grid-cols-3 gap-3">
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.medianConfidence')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                    {iqrText(sttQuality.confidenceSummary, (v) => fixed(v))}
                  </p>
                </div>
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.lowConfidence')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                    {pct(sttQuality.lowConfidenceRate)}
                  </p>
                </div>
                <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                  <p className="text-tiny text-ink-muted">{t('stt.voiceShare')}</p>
                  <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                    {pct(sttQuality.voiceTurnShare)}
                  </p>
                </div>
              </div>
            </>
          ) : (
            <p className="rounded-card border border-dashed border-edge px-4 py-8 text-center text-small text-ink-muted dark:border-dark-border">
              {t('page.empty')}
            </p>
          )}
        </SectionCard>

        {/* 問診效率 */}
        <SectionCard title={t('efficiency.title')} subtitle={t('efficiency.subtitle')}>
          <HistogramChart
            buckets={efficiency.durationHistogram}
            bucketLabel={(b) => `${Math.round(b.start / 60)}–${Math.round(b.end / 60)} ${t('page.minutesShort')}`}
            countLabel={t('efficiency.sessions')}
          />
          <div className="mt-4 grid grid-cols-3 gap-3">
            <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
              <p className="text-tiny text-ink-muted">{t('efficiency.medianDuration')}</p>
              <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                {iqrText(efficiency.durationSeconds, (v) => (v === null ? '—' : `${minutes(v)}m`))}
              </p>
            </div>
            <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
              <p className="text-tiny text-ink-muted">{t('efficiency.medianTurns')}</p>
              <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                {iqrText(efficiency.patientTurns, (v) => (v === null ? '—' : v.toFixed(0)))}
              </p>
            </div>
            <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
              <p className="text-tiny text-ink-muted">{t('efficiency.medianChars')}</p>
              <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                {iqrText(efficiency.patientTurnChars, (v) => (v === null ? '—' : v.toFixed(0)))}
              </p>
            </div>
          </div>
        </SectionCard>

        {/* AI 文件品質 */}
        <SectionCard
          title={t('documentation.title')}
          subtitle={t('documentation.subtitle')}
          badge={t('documentation.badge', { count: documentation.reportsGenerated })}
        >
          <div className="grid gap-5">
            <div>
              <p className="mb-2 text-small font-semibold text-ink-secondary">{t('documentation.outcomesTitle')}</p>
              <StackedShareBar
                buckets={documentation.reviewOutcomes}
                labels={reviewLabels}
                colors={REVIEW_COLOR}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('documentation.aiConfidence')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {iqrText(documentation.aiConfidenceSummary, (v) => fixed(v))}
                </p>
              </div>
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('documentation.icdVerified')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {pct(documentation.icd10VerifiedRate)}
                </p>
              </div>
              <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
                <p className="text-tiny text-ink-muted">{t('documentation.agreement')}</p>
                <p className="mt-1 text-body font-semibold text-ink-heading dark:text-white font-tnum">
                  {pct(documentation.physicianAgreementRate)}
                </p>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      {/* 各語言子群（table view — 圖表數值的無障礙後援） */}
      <SectionCard title={t('table.title')} subtitle={t('table.subtitle')}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-small">
            <thead>
              <tr className="border-b border-edge text-left text-tiny uppercase tracking-wide text-ink-muted dark:border-dark-border">
                <th className="py-2 pr-4 font-semibold">{t('table.language')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.sessions')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.completed')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.medianDuration')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.meanTurns')}</th>
                <th className="py-2 pr-4 font-semibold">{t('table.meanConfidence')}</th>
                <th className="py-2 font-semibold">{t('table.redFlagRate')}</th>
              </tr>
            </thead>
            <tbody>
              {byLanguage.map((row) => (
                <tr key={row.language} className="border-b border-edge last:border-0 dark:border-dark-border">
                  <td className="py-2.5 pr-4 font-semibold text-ink-heading dark:text-white">{row.language}</td>
                  <td className="py-2.5 pr-4 font-tnum">{nf(row.sessions)}</td>
                  <td className="py-2.5 pr-4 font-tnum">{nf(row.completed)}</td>
                  <td className="py-2.5 pr-4 font-tnum">
                    {row.medianDurationSeconds === null ? '—' : `${minutes(row.medianDurationSeconds)} ${t('page.minutesShort')}`}
                  </td>
                  <td className="py-2.5 pr-4 font-tnum">{row.meanPatientTurns ?? '—'}</td>
                  <td className="py-2.5 pr-4 font-tnum">{row.meanSttConfidence ?? '—'}</td>
                  <td className="py-2.5 font-tnum">{pct(row.redFlagSessionRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Methods — 發表對照（文獻框架） */}
      <SectionCard title={t('methods.title')} subtitle={t('methods.subtitle')}>
        <ul className="grid gap-2 text-small text-ink-body dark:text-dark-text-muted lg:grid-cols-2">
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border">
            <span className="font-semibold text-ink-heading dark:text-white">DECIDE-AI</span> — {t('methods.decideAi')}
          </li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border">
            <span className="font-semibold text-ink-heading dark:text-white">AMIE (Nature 2025)</span> — {t('methods.amie')}
          </li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border">
            <span className="font-semibold text-ink-heading dark:text-white">{t('methods.triageLabel')}</span> — {t('methods.triage')}
          </li>
          <li className="rounded-card border border-edge px-3.5 py-3 dark:border-dark-border">
            <span className="font-semibold text-ink-heading dark:text-white">PDQI-9</span> — {t('methods.pdqi')}
          </li>
        </ul>
        <p className="mt-3 text-tiny text-ink-muted">{t('methods.disclaimer')}</p>
      </SectionCard>
    </div>
  );
}
