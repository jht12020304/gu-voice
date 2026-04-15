import { addMonths, endOfMonth, format, startOfMonth } from 'date-fns';
import { useEffect, useState } from 'react';
import * as dashboardApi from '../../services/api/dashboard';
import type {
  MonthlySummaryResponse,
  SummaryBucketItem,
} from '../../types/api';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const chartPalette = ['#8F3A6F', '#F2A83B', '#16181D', '#4A7AF7', '#46A168', '#D0D5DD'];

function createMockMonthlySummary(monthDate: Date): MonthlySummaryResponse {
  const month = format(monthDate, 'yyyy-MM');
  const monthLabel = format(monthDate, 'yyyy 年 M 月');

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
      { key: 'completed', label: '已完成', count: 29 },
      { key: 'in_progress', label: '對話中', count: 8 },
      { key: 'waiting', label: '等待中', count: 7 },
      { key: 'aborted_red_flag', label: '紅旗中止', count: 4 },
      { key: 'cancelled', label: '已取消', count: 0 },
    ],
    chiefComplaintDistribution: [
      { key: 'hematuria', label: '血尿', count: 18 },
      { key: 'frequency', label: '頻尿', count: 11 },
      { key: 'voiding', label: '排尿困難', count: 8 },
      { key: 'pain', label: '腰痛 / 下腹痛', count: 6 },
      { key: 'other', label: '其他', count: 5 },
    ],
    alertSeverityDistribution: [
      { key: 'critical', label: '危急', count: 2 },
      { key: 'high', label: '高度', count: 7 },
      { key: 'medium', label: '中度', count: 3 },
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
}: {
  title: string;
  value: number;
  helper: string;
  accentClass: string;
}) {
  return (
    <div className={`rounded-panel border border-edge bg-white p-5 shadow-card dark:border-dark-border dark:bg-dark-card ${accentClass}`}>
      <p className="text-small font-semibold text-ink-secondary">{title}</p>
      <p className="mt-4 text-display font-bold text-ink-heading dark:text-white font-tnum">
        {value.toLocaleString('zh-TW')}
      </p>
      <p className="mt-2 text-caption text-ink-muted">{helper}</p>
    </div>
  );
}

function DonutDistributionCard({
  title,
  totalLabel,
  items,
}: {
  title: string;
  totalLabel: string;
  items: SummaryBucketItem[];
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
          <p className="mt-1 text-small text-ink-muted">以本月場次占比呈現主要主訴分類</p>
        </div>
        <span className="rounded-pill bg-surface-tertiary px-3 py-1 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
          {items.length} 類
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
              {total.toLocaleString('zh-TW')}
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
              本月尚無可視化分類資料
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function DailyTrendCard({ items }: { items: MonthlySummaryResponse['dailyTrend'] }) {
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
          <h2 className="text-h3 text-ink-heading dark:text-white">日期趨勢</h2>
          <p className="mt-1 text-small text-ink-muted">藍色長條代表每日建立場次數，橘色數字代表當日紅旗筆數</p>
        </div>
        <div className="grid grid-cols-2 gap-3 text-right lg:min-w-[220px]">
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">本月總場次</p>
            <p className="mt-1 text-h3 font-semibold text-ink-heading dark:text-white font-tnum">
              {totalSessions.toLocaleString('zh-TW')}
            </p>
          </div>
          <div className="rounded-card border border-edge px-3 py-2 dark:border-dark-border">
            <p className="text-tiny text-ink-muted">單日高峰</p>
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
  const [selectedMonth, setSelectedMonth] = useState(() => new Date());
  const [monthlySummary, setMonthlySummary] = useState<MonthlySummaryResponse | null>(
    IS_MOCK ? createMockMonthlySummary(new Date()) : null,
  );
  const [isLoading, setIsLoading] = useState(!IS_MOCK);

  useEffect(() => {
    if (IS_MOCK) {
      setMonthlySummary(createMockMonthlySummary(selectedMonth));
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
  }, [selectedMonth]);

  const selectedMonthLabel = monthlySummary?.monthLabel ?? format(selectedMonth, 'yyyy 年 M 月');
  const monthRangeLabel = formatMonthRange(selectedMonth);
  const totalSessions = monthlySummary?.totalSessions ?? 0;
  const redFlagAlerts = monthlySummary?.totalRedFlagAlerts ?? 0;

  return (
    <div className="space-y-8 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">Dashboard</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">問診月統計</h1>
            <p className="mt-2 text-body text-ink-secondary">
              以月份為單位整理場次、主訴與紅旗概況，視覺風格參考你提供的統計儀表板。
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-pill bg-surface-tertiary px-3 py-1.5 text-tiny font-semibold text-ink-secondary dark:bg-dark-surface dark:text-dark-text-muted">
                資料區間 {monthRangeLabel}
              </span>
              <span className="rounded-pill bg-primary-50 px-3 py-1.5 text-tiny font-semibold text-primary-700 dark:bg-primary-950/40 dark:text-primary-300">
                主訴分類 {monthlySummary?.chiefComplaintDistribution.length ?? 0} 類
              </span>
              <span className="rounded-pill bg-alert-critical-bg px-3 py-1.5 text-tiny font-semibold text-alert-critical">
                紅旗警示 {redFlagAlerts} 筆
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-panel border border-edge bg-white p-1.5 shadow-card dark:border-dark-border dark:bg-dark-card">
            <button
              type="button"
              className="rounded-card p-2 text-ink-secondary transition-colors hover:bg-surface-tertiary hover:text-ink-heading dark:hover:bg-dark-surface dark:hover:text-white"
              onClick={() => setSelectedMonth((current) => addMonths(current, -1))}
              aria-label="上一個月"
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
              aria-label="下一個月"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5L15.75 12l-7.5 7.5" />
              </svg>
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-2">
          <SummaryMetricCard
            title={`${selectedMonthLabel} 總場次`}
            value={totalSessions}
            helper="本月建立的問診場次數量"
            accentClass="border-t-4 border-t-[#8F3A6F]"
          />
          <SummaryMetricCard
            title="紅旗警示"
            value={redFlagAlerts}
            helper="本月觸發的紅旗告警總數"
            accentClass="border-t-4 border-t-amber-500"
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="xl:col-span-4">
          <DonutDistributionCard
            title="主訴分類分佈"
            totalLabel="場次"
            items={monthlySummary?.chiefComplaintDistribution ?? []}
          />
        </div>
        <div className="xl:col-span-8">
          <DailyTrendCard items={monthlySummary?.dailyTrend ?? []} />
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-panel border border-dashed border-edge px-4 py-3 text-center text-small text-ink-muted dark:border-dark-border">
          正在同步月份摘要...
        </div>
      ) : null}
    </div>
  );
}
