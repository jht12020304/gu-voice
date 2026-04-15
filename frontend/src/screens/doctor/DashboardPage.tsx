import { addMonths, endOfMonth, format, startOfMonth } from 'date-fns';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AlertItem from '../../components/dashboard/AlertItem';
import QueueCard from '../../components/dashboard/QueueCard';
import StatusBadge from '../../components/medical/StatusBadge';
import * as dashboardApi from '../../services/api/dashboard';
import type {
  MonthlySummaryResponse,
  QueueItem,
  RecentAlertItem,
  RecentSessionItem,
  SummaryBucketItem,
} from '../../types/api';
import type { AlertSeverity, SessionStatus } from '../../types/enums';
import { formatDate } from '../../utils/format';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const chartPalette = ['#8F3A6F', '#F2A83B', '#16181D', '#4A7AF7', '#46A168', '#D0D5DD'];

const mockQueue: QueueItem[] = [
  { sessionId: 's1', patientId: 'p1', patientName: '陳小明', chiefComplaint: '血尿持續三天', status: 'in_progress', waitingSeconds: 0, hasRedFlag: true, createdAt: '2026-04-15T09:00:00Z' },
  { sessionId: 's2', patientId: 'p2', patientName: '林美玲', chiefComplaint: '頻尿、夜尿增加', status: 'waiting', waitingSeconds: 720, hasRedFlag: false, createdAt: '2026-04-15T08:40:00Z' },
  { sessionId: 's3', patientId: 'p3', patientName: '張大偉', chiefComplaint: '排尿困難', status: 'waiting', waitingSeconds: 1500, hasRedFlag: false, createdAt: '2026-04-15T08:20:00Z' },
  { sessionId: 's4', patientId: 'p4', patientName: '王志明', chiefComplaint: '左側腰痛伴噁心', status: 'in_progress', waitingSeconds: 0, hasRedFlag: true, createdAt: '2026-04-15T08:10:00Z' },
  { sessionId: 's5', patientId: 'p5', patientName: '李淑華', chiefComplaint: '尿失禁', status: 'waiting', waitingSeconds: 3120, hasRedFlag: false, createdAt: '2026-04-15T07:30:00Z' },
];

const mockAlerts: RecentAlertItem[] = [
  { alertId: 'a1', sessionId: 's1', patientName: '陳小明', severity: 'critical', title: '疑似睪丸扭轉', acknowledged: false, createdAt: '2026-04-15T10:12:00Z' },
  { alertId: 'a2', sessionId: 's4', patientName: '王志明', severity: 'high', title: '疑似腎絞痛合併發燒', acknowledged: false, createdAt: '2026-04-14T13:30:00Z' },
  { alertId: 'a3', sessionId: 's3', patientName: '張大偉', severity: 'medium', title: '肉眼血尿持續', acknowledged: false, createdAt: '2026-04-13T13:15:00Z' },
];

const mockRecentSessions: RecentSessionItem[] = [
  { sessionId: 'rs1', patientName: '黃美芳', chiefComplaint: '攝護腺症狀', status: 'completed', redFlag: false, createdAt: '2026-04-15T11:30:00Z', completedAt: '2026-04-15T11:52:00Z' },
  { sessionId: 'rs2', patientName: '吳建宏', chiefComplaint: '泌尿道感染', status: 'completed', redFlag: false, createdAt: '2026-04-15T10:45:00Z', completedAt: '2026-04-15T11:05:00Z' },
  { sessionId: 'rs3', patientName: '趙淑芬', chiefComplaint: '尿失禁', status: 'completed', redFlag: false, createdAt: '2026-04-15T10:00:00Z', completedAt: '2026-04-15T10:28:00Z' },
  { sessionId: 'rs4', patientName: '周志豪', chiefComplaint: '陰囊疼痛', status: 'aborted_red_flag', redFlag: true, createdAt: '2026-04-15T09:15:00Z', completedAt: '2026-04-15T09:20:00Z' },
];

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

function getBucketCount(items: SummaryBucketItem[], key: string): number {
  return items.find((item) => item.key === key)?.count ?? 0;
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

function CompletionOverviewCard({ summary }: { summary: MonthlySummaryResponse | null }) {
  const statusItems = summary?.statusDistribution ?? [];
  const completionRate = summary?.completionRate ?? 0;
  const radius = 56;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(Math.max(completionRate, 0), 100);
  const dashOffset = circumference - (progress / 100) * circumference;

  const quickStats = [
    { key: 'completed', label: '已完成', value: getBucketCount(statusItems, 'completed'), tone: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300' },
    { key: 'aborted_red_flag', label: '紅旗中止', value: getBucketCount(statusItems, 'aborted_red_flag'), tone: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300' },
    { key: 'in_progress', label: '對話中', value: getBucketCount(statusItems, 'in_progress'), tone: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-300' },
    { key: 'waiting', label: '等待中', value: getBucketCount(statusItems, 'waiting'), tone: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300' },
  ];

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">場次完成統計</h2>
          <p className="mt-1 text-small text-ink-muted">以完成率快速檢視本月處理進度</p>
        </div>
        <span className="rounded-pill bg-emerald-50 px-3 py-1 text-tiny font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
          更新於 {summary ? formatDate(summary.generatedAt, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}
        </span>
      </div>

      <div className="mt-6 flex flex-col items-center gap-6">
        <div className="relative h-40 w-40">
          <svg viewBox="0 0 160 160" className="h-40 w-40">
            <circle cx="80" cy="80" r={radius} fill="none" stroke="#E8ECF3" strokeWidth="14" />
            <circle
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke="#46A168"
              strokeWidth="14"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              transform="rotate(-90 80 80)"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <p className="text-display font-bold text-emerald-600 dark:text-emerald-300 font-tnum">
              {progress.toFixed(progress % 1 === 0 ? 0 : 1)}%
            </p>
            <p className="text-small text-ink-muted">完成率</p>
          </div>
        </div>

        <div className="grid w-full grid-cols-2 gap-3">
          {quickStats.map((item) => (
            <div key={item.key} className={`rounded-card border px-4 py-3 ${item.tone}`}>
              <p className="text-small font-medium">{item.label}</p>
              <p className="mt-2 text-h2 font-bold font-tnum">{item.value.toLocaleString('zh-TW')}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SeverityDistributionCard({ items }: { items: SummaryBucketItem[] }) {
  const maxCount = Math.max(...items.map((item) => item.count), 1);
  const tones: Record<string, string> = {
    critical: 'bg-rose-700',
    high: 'bg-amber-500',
    medium: 'bg-sky-500',
  };

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-h3 text-ink-heading dark:text-white">紅旗等級分佈</h2>
          <p className="mt-1 text-small text-ink-muted">查看本月警示主要落在哪個嚴重度區間</p>
        </div>
        <span className="rounded-pill bg-alert-critical-bg px-3 py-1 text-tiny font-semibold text-alert-critical">
          {items.reduce((sum, item) => sum + item.count, 0)} 筆
        </span>
      </div>

      <div className="mt-6 space-y-5">
        {items.map((item) => (
          <div key={item.key}>
            <div className="mb-2 flex items-center justify-between text-small">
              <span className="font-medium text-ink-heading dark:text-white">{item.label}</span>
              <span className="text-ink-muted font-tnum">
                {item.count}/{Math.max(...items.map((entry) => entry.count), 1)}
              </span>
            </div>
            <div className="h-3 rounded-full bg-surface-tertiary dark:bg-dark-surface">
              <div
                className={`h-3 rounded-full ${tones[item.key] || 'bg-slate-400'}`}
                style={{ width: `${(item.count / maxCount) * 100}%` }}
              />
            </div>
            <div className="mt-1 text-right text-tiny font-semibold text-ink-secondary">
              {maxCount > 0 ? `${Math.round((item.count / maxCount) * 100)}%` : '0%'}
            </div>
          </div>
        ))}
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

function EmptyListState({ message }: { message: string }) {
  return (
    <div className="rounded-card border border-dashed border-edge px-4 py-8 text-center text-small text-ink-muted dark:border-dark-border">
      {message}
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [selectedMonth, setSelectedMonth] = useState(() => new Date());
  const [monthlySummary, setMonthlySummary] = useState<MonthlySummaryResponse | null>(
    IS_MOCK ? createMockMonthlySummary(new Date()) : null,
  );
  const [queue, setQueue] = useState<QueueItem[]>(IS_MOCK ? mockQueue : []);
  const [alerts, setAlerts] = useState<RecentAlertItem[]>(IS_MOCK ? mockAlerts : []);
  const [recentSessions, setRecentSessions] = useState<RecentSessionItem[]>(IS_MOCK ? mockRecentSessions : []);
  const [isLoading, setIsLoading] = useState(!IS_MOCK);

  useEffect(() => {
    if (IS_MOCK) {
      setMonthlySummary(createMockMonthlySummary(selectedMonth));
      setQueue(mockQueue);
      setAlerts(mockAlerts);
      setRecentSessions(mockRecentSessions);
      setIsLoading(false);
      return;
    }

    async function loadDashboard() {
      setIsLoading(true);
      try {
        const month = format(selectedMonth, 'yyyy-MM');
        const [summaryRes, queueRes, alertsRes, sessionsRes] = await Promise.allSettled([
          dashboardApi.getMonthlySummary(month),
          dashboardApi.getDashboardQueue(),
          dashboardApi.getRecentAlerts(),
          dashboardApi.getRecentSessions(),
        ]);

        if (summaryRes.status === 'fulfilled') {
          setMonthlySummary(summaryRes.value);
        }
        if (queueRes.status === 'fulfilled') {
          setQueue(queueRes.value.queue ?? []);
        }
        if (alertsRes.status === 'fulfilled') {
          setAlerts(alertsRes.value.data ?? []);
        }
        if (sessionsRes.status === 'fulfilled') {
          setRecentSessions(sessionsRes.value.data ?? []);
        }
      } finally {
        setIsLoading(false);
      }
    }

    loadDashboard();
  }, [selectedMonth]);

  const selectedMonthLabel = monthlySummary?.monthLabel ?? format(selectedMonth, 'yyyy 年 M 月');
  const monthRangeLabel = formatMonthRange(selectedMonth);
  const queuePreview = queue.slice(0, 8);
  const alertPreview = alerts.slice(0, 4);
  const recentCompletedSessions = recentSessions
    .filter((session) => session.status === 'completed' || session.status === 'aborted_red_flag')
    .slice(0, 6);

  const totalSessions = monthlySummary?.totalSessions ?? 0;
  const completedSessions = monthlySummary?.completedSessions ?? 0;
  const redFlagAlerts = monthlySummary?.totalRedFlagAlerts ?? 0;
  const abortedSessions = monthlySummary?.abortedRedFlagSessions ?? 0;
  const pendingReviews = monthlySummary?.pendingReviews ?? 0;

  return (
    <div className="space-y-8 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">Dashboard</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">問診月統計</h1>
            <p className="mt-2 text-body text-ink-secondary">
              以月份為單位整理場次、紅旗與報告審閱概況，視覺風格參考你提供的統計儀表板。
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

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
          <SummaryMetricCard
            title={`${selectedMonthLabel} 總場次`}
            value={totalSessions}
            helper="本月建立的問診場次數量"
            accentClass="border-t-4 border-t-[#8F3A6F]"
          />
          <SummaryMetricCard
            title="已完成"
            value={completedSessions}
            helper={`${monthlySummary?.completionRate ?? 0}% 完成率`}
            accentClass="border-t-4 border-t-emerald-500"
          />
          <SummaryMetricCard
            title="紅旗警示"
            value={redFlagAlerts}
            helper="本月觸發的紅旗告警總數"
            accentClass="border-t-4 border-t-amber-500"
          />
          <SummaryMetricCard
            title="紅旗中止"
            value={abortedSessions}
            helper="因危急情況提前中止的場次"
            accentClass="border-t-4 border-t-[#16181D]"
          />
          <SummaryMetricCard
            title="待審閱"
            value={pendingReviews}
            helper="本月產生後尚待醫師審閱的報告"
            accentClass="border-t-4 border-t-[#4A7AF7]"
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
        <div className="xl:col-span-4">
          <CompletionOverviewCard summary={monthlySummary} />
        </div>
        <div className="xl:col-span-4">
          <SeverityDistributionCard items={monthlySummary?.alertSeverityDistribution ?? []} />
        </div>
        <div className="xl:col-span-12">
          <DailyTrendCard items={monthlySummary?.dailyTrend ?? []} />
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-1 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-h2 text-ink-heading dark:text-white">即時看診概況</h2>
            <p className="mt-1 text-body text-ink-secondary">下方仍保留即時營運資訊，方便快速切回場次與告警處理。</p>
          </div>
          <div className="text-small text-ink-muted">
            {isLoading ? '正在同步最新資料...' : '即時資料已更新'}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
          <div className="card xl:col-span-7">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-h3 text-ink-heading dark:text-white">等候佇列</h3>
                <p className="mt-1 text-small text-ink-muted">預覽前 8 筆即時場次，點擊可進入場次明細</p>
              </div>
              <div className="flex items-center gap-3">
                <span className="badge badge-in-progress">
                  {queue.filter((item) => item.status === 'in_progress').length} 進行中 · {queue.filter((item) => item.status === 'waiting').length} 等待中
                </span>
                <button
                  type="button"
                  className="text-caption font-medium text-primary-600 hover:text-primary-700"
                  onClick={() => navigate('/sessions')}
                >
                  查看全部 →
                </button>
              </div>
            </div>

            <div className="space-y-2">
              {queuePreview.length > 0 ? (
                queuePreview.map((item) => (
                  <QueueCard
                    key={item.sessionId}
                    patientName={item.patientName}
                    chiefComplaint={item.chiefComplaint}
                    status={item.status}
                    waitingSeconds={item.waitingSeconds ?? 0}
                    hasRedFlag={item.hasRedFlag}
                    onClick={() => navigate(`/sessions/${item.sessionId}`)}
                  />
                ))
              ) : (
                <EmptyListState message="目前沒有等待中或進行中的場次" />
              )}
            </div>
          </div>

          <div className="space-y-6 xl:col-span-5">
            <div className="card">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-h3 text-ink-heading dark:text-white">紅旗警示</h3>
                  <p className="mt-1 text-small text-ink-muted">最近觸發的高優先處理事件</p>
                </div>
                <button
                  type="button"
                  className="text-caption font-medium text-primary-600 hover:text-primary-700"
                  onClick={() => navigate('/alerts')}
                >
                  查看全部 →
                </button>
              </div>

              <div className="space-y-2">
                {alertPreview.length > 0 ? (
                  alertPreview.map((alert) => (
                    <AlertItem
                      key={alert.alertId}
                      id={alert.alertId}
                      title={alert.title}
                      severity={alert.severity as AlertSeverity}
                      patientName={alert.patientName}
                      createdAt={alert.createdAt}
                      isAcknowledged={alert.acknowledged}
                      onClick={() => navigate(`/alerts/${alert.alertId}`)}
                    />
                  ))
                ) : (
                  <EmptyListState message="近期沒有新的紅旗警示" />
                )}
              </div>
            </div>

            <div className="card">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-h3 text-ink-heading dark:text-white">最近完成 / 中止</h3>
                  <p className="mt-1 text-small text-ink-muted">只顯示已完成與紅旗中止的近期場次</p>
                </div>
                <button
                  type="button"
                  className="text-caption font-medium text-primary-600 hover:text-primary-700"
                  onClick={() => navigate('/reports')}
                >
                  前往報告 →
                </button>
              </div>

              <div className="space-y-3">
                {recentCompletedSessions.length > 0 ? (
                  recentCompletedSessions.map((session) => (
                    <div key={session.sessionId} className="flex items-center justify-between border-b border-edge py-2 last:border-0 dark:border-dark-border">
                      <div className="min-w-0 flex-1 pr-3">
                        <p className="truncate text-body font-medium text-ink-heading dark:text-white">{session.patientName}</p>
                        <p className="truncate text-small text-ink-muted">{session.chiefComplaint}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <StatusBadge status={session.status as SessionStatus} size="sm" />
                        <span className="text-tiny text-ink-muted font-tnum">
                          {formatDate(session.completedAt ?? session.createdAt, { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <EmptyListState message="近期尚無已完成或中止的場次" />
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-panel border border-dashed border-edge px-4 py-3 text-center text-small text-ink-muted dark:border-dark-border">
          正在同步月份摘要與即時資料...
        </div>
      ) : null}
    </div>
  );
}
