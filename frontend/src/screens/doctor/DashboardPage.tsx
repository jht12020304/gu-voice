import { addMonths, endOfMonth, format, startOfMonth } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as dashboardApi from '../../services/api/dashboard';
import type {
  MonthlySummaryResponse,
  SummaryBucketItem,
} from '../../types/api';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const chartPalette = ['#8F3A6F', '#F2A83B', '#16181D', '#4A7AF7', '#46A168', '#D0D5DD'];

// 用 key 對應 i18n 翻譯；後端 label 若無對應則 fallback 用後端回傳 label
const STATUS_LABEL_KEYS: Record<string, string> = {
  completed: 'doctor.dashboard.statusCompleted',
  in_progress: 'doctor.dashboard.statusInProgress',
  waiting: 'doctor.dashboard.statusWaiting',
  aborted_red_flag: 'doctor.dashboard.statusAbortedRedFlag',
  cancelled: 'doctor.dashboard.statusCancelled',
};

const COMPLAINT_LABEL_KEYS: Record<string, string> = {
  hematuria: 'doctor.dashboard.complaintHematuria',
  frequency: 'doctor.dashboard.complaintFrequency',
  voiding: 'doctor.dashboard.complaintVoiding',
  pain: 'doctor.dashboard.complaintPain',
  other: 'doctor.dashboard.complaintOther',
};

const SEVERITY_LABEL_KEYS: Record<string, string> = {
  critical: 'doctor.dashboard.severityCritical',
  high: 'doctor.dashboard.severityHigh',
  medium: 'doctor.dashboard.severityMedium',
};

function createMockMonthlySummary(monthDate: Date, monthLabel: string): MonthlySummaryResponse {
  const month = format(monthDate, 'yyyy-MM');

  return {
    month,
    monthLabel,
    totalSessions: 48,
    completedSessions: 29,
    abortedRedFlagSessions: 4,
    pendingReviews: 9,
    totalRedFlagAlerts: 12,
    completionRate: 60.4,
    statusDistribution: [
      { key: 'completed', label: 'completed', count: 29 },
      { key: 'in_progress', label: 'in_progress', count: 8 },
      { key: 'waiting', label: 'waiting', count: 7 },
      { key: 'aborted_red_flag', label: 'aborted_red_flag', count: 4 },
      { key: 'cancelled', label: 'cancelled', count: 0 },
    ],
    chiefComplaintDistribution: [
      { key: 'hematuria', label: 'hematuria', count: 18 },
      { key: 'frequency', label: 'frequency', count: 11 },
      { key: 'voiding', label: 'voiding', count: 8 },
      { key: 'pain', label: 'pain', count: 6 },
      { key: 'other', label: 'other', count: 5 },
    ],
    alertSeverityDistribution: [
      { key: 'critical', label: 'critical', count: 2 },
      { key: 'high', label: 'high', count: 7 },
      { key: 'medium', label: 'medium', count: 3 },
    ],
    dailyTrend: Array.from({ length: 30 }, (_, index) => {
      const day = index + 1;
      const sessions = [1, 2, 3, 2, 0, 4, 3, 1, 0, 2, 4, 3, 1, 2, 3, 2, 1, 5, 2, 1, 0, 3, 4, 2, 3, 1, 2, 1, 2, 1][index];
      const completed = Math.max(0, sessions - (index % 3 === 0 ? 1 : 0));
      const redFlags = index % 9 === 0 ? 1 : 0;
      return {
        date: `${month}-${String(day).padStart(2, '0')}`,
        label: `${String(monthDate.getMonth() + 1).padStart(2, '0')}/${String(day).padStart(2, '0')}`,
        sessions,
        completed,
        redFlags,
      };
    }),
    generatedAt: new Date().toISOString(),
  };
}

function formatMonthRange(monthDate: Date): string {
  return `${format(startOfMonth(monthDate), 'yyyy/MM/dd')} - ${format(endOfMonth(monthDate), 'yyyy/MM/dd')}`;
}

function SummaryMetricCard({
  title,
  value,
  helper,
  accentClass,
  numberLocale,
}: {
  title: string;
  value: number;
  helper: string;
  accentClass: string;
  numberLocale: string;
}) {
  return (
    <div className={`rounded-panel border border-edge bg-white p-5 shadow-card dark:border-dark-border dark:bg-dark-card ${accentClass}`}>
      <p className="text-small font-semibold text-ink-secondary">{title}</p>
      <p className="mt-4 text-display font-bold text-ink-heading dark:text-white font-tnum">
        {value.toLocaleString(numberLocale)}
      </p>
      <p className="mt-2 text-caption text-ink-muted">{helper}</p>
    </div>
  );
}

function DonutDistributionCard({
  title,
  subtitle,
  totalLabel,
  items,
  categoryCountLabel,
  emptyLabel,
  numberLocale,
}: {
  title: string;
  subtitle: string;
  totalLabel: string;
  items: SummaryBucketItem[];
  categoryCountLabel: string;
  emptyLabel: string;
  numberLocale: string;
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  const radius = 56;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">{title}</h2>
          <p className="mt-1 text-small text-ink-muted">{subtitle}</p>
        </div>
        <span className="rounded-pill bg-surface-tertiary px-3 py-1 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
          {categoryCountLabel}
        </span>
      </div>

      <div className="mt-6 flex flex-col gap-6 lg:flex-row lg:items-center">
        <div className="relative mx-auto h-36 w-36 shrink-0">
          <svg viewBox="0 0 144 144" className="h-36 w-36">
            <circle
              cx="72"
              cy="72"
              r={radius}
              fill="none"
              stroke="#E8ECF3"
              strokeWidth="18"
            />
            {total > 0
              ? items.map((item, index) => {
                  const length = (item.count / total) * circumference;
                  const circle = (
                    <circle
                      key={item.key}
                      cx="72"
                      cy="72"
                      r={radius}
                      fill="none"
                      stroke={chartPalette[index % chartPalette.length]}
                      strokeWidth="18"
                      strokeDasharray={`${length} ${circumference - length}`}
                      strokeDashoffset={-offset}
                      transform="rotate(-90 72 72)"
                    />
                  );
                  offset += length;
                  return circle;
                })
              : null}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <p className="text-display font-bold text-ink-heading dark:text-white font-tnum">
              {total.toLocaleString(numberLocale)}
            </p>
            <p className="text-small text-ink-muted">{totalLabel}</p>
          </div>
        </div>

        <div className="grid flex-1 gap-3">
          {items.length > 0 ? (
            items.map((item, index) => (
              <div key={item.key} className="flex items-center justify-between rounded-card border border-edge px-3.5 py-3 dark:border-dark-border">
                <div className="flex items-center gap-3">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: chartPalette[index % chartPalette.length] }}
                  />
                  <span className="text-body text-ink-heading dark:text-white">{item.label}</span>
                </div>
                <div className="text-right">
                  <p className="text-body font-semibold text-ink-heading dark:text-white font-tnum">{item.count}</p>
                  <p className="text-tiny text-ink-muted">
                    {total > 0 ? `${Math.round((item.count / total) * 100)}%` : '0%'}
                  </p>
                </div>
              </div>
            ))
          ) : (
            <p className="rounded-card border border-dashed border-edge px-4 py-10 text-center text-small text-ink-muted dark:border-dark-border">
              {emptyLabel}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function DailyTrendCard({
  items,
  title,
  subtitle,
  totalLabel,
  peakLabel,
  numberLocale,
}: {
  items: MonthlySummaryResponse['dailyTrend'];
  title: string;
  subtitle: string;
  totalLabel: string;
  peakLabel: string;
  numberLocale: string;
}) {
  const maxSessions = Math.max(...items.map((item) => item.sessions), 1);
  const totalSessions = items.reduce((sum, item) => sum + item.sessions, 0);
  const busiestDay = items.reduce(
    (best, item) => (item.sessions > best.sessions ? item : best),
    items[0] ?? { label: '-', sessions: 0, redFlags: 0 },
  );

  return (
    <div className="card">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">{title}</h2>
          <p className="mt-1 text-small text-ink-muted">{subtitle}</p>
        </div>
        <div className="grid grid-cols-2 gap-3 text-right lg:min-w-[220px]">
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{totalLabel}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">
              {totalSessions.toLocaleString(numberLocale)}
            </p>
          </div>
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">{peakLabel}</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">
              {busiestDay.sessions}
            </p>
            <p className="text-tiny text-ink-muted">{busiestDay.label}</p>
          </div>
        </div>
      </div>

      <div className="mt-6 overflow-x-auto pb-2">
        <div className="flex h-56 min-w-[720px] items-end gap-2 px-1">
          {items.map((item, index) => {
            const barHeight = item.sessions > 0 ? Math.max((item.sessions / maxSessions) * 100, 8) : 0;
            const showLabel = index === 0 || index === items.length - 1 || item.label.endsWith('/01') || item.label.endsWith('/15');
            return (
              <div key={item.date} className="flex flex-1 flex-col items-center gap-2">
                <div className="relative flex h-44 w-full items-end justify-center">
                  {item.redFlags > 0 ? (
                    <span className="absolute -top-5 rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                      {item.redFlags}
                    </span>
                  ) : null}
                  <div className="h-full w-3 rounded-full bg-surface-tertiary dark:bg-dark-surface" />
                  {barHeight > 0 ? (
                    <div
                      className="absolute bottom-0 w-3 rounded-full bg-primary-600"
                      style={{ height: `${barHeight}%` }}
                    />
                  ) : null}
                </div>
                <span className="text-[10px] text-ink-muted">{showLabel ? item.label : item.label.split('/')[1]}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { t, i18n } = useTranslation('common');
  const numberLocale = i18n.language || 'zh-TW';
  const [selectedMonth, setSelectedMonth] = useState(() => new Date());

  const formatMonthLabel = useMemo(
    () => (d: Date) =>
      t('doctor.dashboard.monthFormat', {
        year: d.getFullYear(),
        month: d.getMonth() + 1,
      }),
    [t],
  );

  const [monthlySummary, setMonthlySummary] = useState<MonthlySummaryResponse | null>(
    IS_MOCK ? createMockMonthlySummary(new Date(), formatMonthLabel(new Date())) : null,
  );
  const [isLoading, setIsLoading] = useState(!IS_MOCK);

  useEffect(() => {
    if (IS_MOCK) {
      setMonthlySummary(createMockMonthlySummary(selectedMonth, formatMonthLabel(selectedMonth)));
      setIsLoading(false);
      return;
    }

    async function loadDashboard() {
      setIsLoading(true);
      try {
        const month = format(selectedMonth, 'yyyy-MM');
        const summary = await dashboardApi.getMonthlySummary(month);
        setMonthlySummary(summary);
      } finally {
        setIsLoading(false);
      }
    }

    loadDashboard();
  }, [selectedMonth, formatMonthLabel]);

  const selectedMonthLabel = monthlySummary?.monthLabel ?? formatMonthLabel(selectedMonth);
  const monthRangeLabel = formatMonthRange(selectedMonth);
  const totalSessions = monthlySummary?.totalSessions ?? 0;
  const redFlagAlerts = monthlySummary?.totalRedFlagAlerts ?? 0;

  // 將後端 key 映射到翻譯 label（若無映射則保留原 label）
  const translateItems = (items: SummaryBucketItem[], keyMap: Record<string, string>): SummaryBucketItem[] =>
    items.map((item) => ({
      ...item,
      label: keyMap[item.key] ? t(keyMap[item.key]) : item.label,
    }));

  const complaintItems = translateItems(
    monthlySummary?.chiefComplaintDistribution ?? [],
    COMPLAINT_LABEL_KEYS,
  );

  // statusDistribution / alertSeverityDistribution 目前未直接呈現於畫面，
  // 但保留翻譯映射供未來使用
  void STATUS_LABEL_KEYS;
  void SEVERITY_LABEL_KEYS;

  return (
    <div className="space-y-8 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">{t('doctor.dashboard.eyebrow')}</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">{t('doctor.dashboard.title')}</h1>
            <p className="mt-2 text-body text-ink-secondary">
              {t('doctor.dashboard.subtitle')}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-pill bg-surface-tertiary px-3 py-1.5 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
                {t('doctor.dashboard.dateRange', { range: monthRangeLabel })}
              </span>
              <span className="rounded-pill bg-primary-50 px-3 py-1.5 text-tiny font-semibold text-primary-700 dark:bg-primary-950/40 dark:text-primary-300">
                {t('doctor.dashboard.complaintCategories', { count: monthlySummary?.chiefComplaintDistribution.length ?? 0 })}
              </span>
              <span className="rounded-pill bg-alert-critical-bg px-3 py-1.5 text-tiny font-semibold text-alert-critical">
                {t('doctor.dashboard.redFlagAlerts', { count: redFlagAlerts })}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-panel border border-edge bg-white p-1.5 shadow-card dark:border-dark-border dark:bg-dark-card">
            <button
              type="button"
              className="rounded-card p-2 text-ink-secondary transition-colors hover:bg-surface-tertiary hover:text-ink-heading dark:hover:bg-dark-surface dark:hover:text-white"
              onClick={() => setSelectedMonth((current) => addMonths(current, -1))}
              aria-label={t('doctor.dashboard.prevMonth')}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <div className="min-w-[148px] px-3 text-center text-body font-semibold text-ink-heading dark:text-white">
              {selectedMonthLabel}
            </div>
            <button
              type="button"
              className="rounded-card p-2 text-ink-secondary transition-colors hover:bg-surface-tertiary hover:text-ink-heading dark:hover:bg-dark-surface dark:hover:text-white"
              onClick={() => setSelectedMonth((current) => addMonths(current, 1))}
              aria-label={t('doctor.dashboard.nextMonth')}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5L15.75 12l-7.5 7.5" />
              </svg>
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-2">
          <SummaryMetricCard
            title={t('doctor.dashboard.monthlyTotal', { month: selectedMonthLabel })}
            value={totalSessions}
            helper={t('doctor.dashboard.monthlyTotalHint')}
            accentClass="border-t-4 border-t-[#8F3A6F]"
            numberLocale={numberLocale}
          />
          <SummaryMetricCard
            title={t('doctor.dashboard.redFlagMetric')}
            value={redFlagAlerts}
            helper={t('doctor.dashboard.redFlagMetricHint')}
            accentClass="border-t-4 border-t-amber-500"
            numberLocale={numberLocale}
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="xl:col-span-4">
          <DonutDistributionCard
            title={t('doctor.dashboard.chiefComplaintDistribution')}
            subtitle={t('doctor.dashboard.donutSubtitle')}
            totalLabel={t('doctor.dashboard.sessions')}
            items={complaintItems}
            categoryCountLabel={t('doctor.dashboard.categoryCount', { count: complaintItems.length })}
            emptyLabel={t('doctor.dashboard.noCategoryData')}
            numberLocale={numberLocale}
          />
        </div>
        <div className="xl:col-span-8">
          <DailyTrendCard
            items={monthlySummary?.dailyTrend ?? []}
            title={t('doctor.dashboard.dailyTrend')}
            subtitle={t('doctor.dashboard.dailyTrendHint')}
            totalLabel={t('doctor.dashboard.totalSessions')}
            peakLabel={t('doctor.dashboard.peakDay')}
            numberLocale={numberLocale}
          />
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-panel border border-dashed border-edge px-4 py-3 text-center text-small text-ink-muted dark:border-dark-border">
          {t('doctor.dashboard.syncing')}
        </div>
      ) : null}
    </div>
  );
}
