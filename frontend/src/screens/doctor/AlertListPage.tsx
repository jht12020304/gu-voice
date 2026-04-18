// =============================================================================
// 紅旗警示列表頁
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useAlertStore } from '../../stores/alertStore';
import AlertItem from '../../components/dashboard/AlertItem';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import * as sessionsApi from '../../services/api/sessions';
import type { Session } from '../../types';
import { formatDate } from '../../utils/format';

const FILTER_TABS = [
  { key: 'all' as const, label: '全部' },
  { key: 'unacknowledged' as const, label: '未處理' },
  { key: 'acknowledged' as const, label: '已處理' },
];

interface AlertSessionMeta {
  patientName: string;
  chiefComplaint: string;
  sessionStatus: string;
}

function sessionStatusLabel(status?: Session['status']): string {
  switch (status) {
    case 'waiting':
      return '等待中';
    case 'in_progress':
      return '問診中';
    case 'completed':
      return '已完成';
    case 'aborted_red_flag':
      return '紅旗中止';
    case 'cancelled':
      return '已取消';
    default:
      return '未取得場次狀態';
  }
}

function getDateKey(dateStr: string): string {
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return 'unknown';
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getDateLabel(dateStr: string): string {
  return formatDate(dateStr, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
}

function AlertSummaryCard({
  title,
  value,
  helper,
  toneClass,
}: {
  title: string;
  value: number;
  helper: string;
  toneClass: string;
}) {
  return (
    <div className={`rounded-panel border bg-white p-5 shadow-card dark:bg-dark-card dark:border-dark-border ${toneClass}`}>
      <p className="text-small font-semibold uppercase tracking-[0.16em] text-ink-muted">{title}</p>
      <p className="mt-3 text-display text-ink-heading dark:text-white">{value}</p>
      <p className="mt-2 text-small text-ink-muted">{helper}</p>
    </div>
  );
}

function AlertListSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="alert-card border-l-0">
          <div className="flex items-start gap-4">
            <div className="skeleton h-5 w-5 rounded-full" />
            <div className="min-w-0 flex-1 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <div className="skeleton h-5 w-40" />
                <div className="skeleton h-5 w-16" />
                <div className="skeleton h-5 w-16" />
              </div>
              <div className="flex flex-wrap gap-2">
                <div className="skeleton h-6 w-24" />
                <div className="skeleton h-6 w-40" />
              </div>
              <div className="skeleton h-4 w-full" />
              <div className="skeleton h-4 w-5/6" />
              <div className="flex flex-wrap items-center gap-3">
                <div className="skeleton h-5 w-28" />
                <div className="skeleton h-5 w-24" />
                <div className="skeleton h-4 w-20" />
              </div>
            </div>
            <div className="space-y-2">
              <div className="skeleton h-4 w-20" />
              <div className="skeleton h-4 w-14" />
              <div className="skeleton h-8 w-20" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AlertListPage() {
  const navigate = useLocalizedNavigate();
  const {
    alerts,
    isLoading,
    error,
    filter,
    fetchAlerts,
    setFilter,
    acknowledgeAlert,
    fetchUnacknowledgedCount,
    unacknowledgedCount,
    allTotalCount,
  } = useAlertStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [sessionMeta, setSessionMeta] = useState<Record<string, AlertSessionMeta>>({});

  useEffect(() => {
    fetchAlerts(true);
    fetchUnacknowledgedCount();
  }, [fetchAlerts, fetchUnacknowledgedCount]);

  useEffect(() => {
    if (alerts.length === 0) return;

    let cancelled = false;

    async function loadSessionMeta() {
      const missingSessionIds = alerts
        .map((alert) => alert.sessionId)
        .filter((sessionId, index, list) => list.indexOf(sessionId) === index)
        .filter((sessionId) => !sessionMeta[sessionId]);

      if (missingSessionIds.length === 0) return;

      const entries = await Promise.all(
        missingSessionIds.map(async (sessionId) => {
          try {
            const session = await sessionsApi.getSession(sessionId);
            return [
              sessionId,
              {
                patientName: session.patient?.name ?? session.patientName ?? '未知病患',
                chiefComplaint:
                  session.chiefComplaintText ?? session.chiefComplaint?.name ?? '未填寫主訴',
                sessionStatus: sessionStatusLabel(session.status),
              },
            ] as const;
          } catch {
            return [
              sessionId,
              {
                patientName: '未知病患',
                chiefComplaint: '未取得主訴',
                sessionStatus: '未取得場次狀態',
              },
            ] as const;
          }
        }),
      );

      if (!cancelled) {
        setSessionMeta((prev) => ({
          ...prev,
          ...Object.fromEntries(entries),
        }));
      }
    }

    loadSessionMeta();

    return () => {
      cancelled = true;
    };
  }, [alerts, sessionMeta]);

  const visibleAlerts = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return alerts;

    return alerts.filter((alert) => {
      const meta = sessionMeta[alert.sessionId];
      const haystacks = [
        alert.title,
        alert.description,
        alert.triggerReason,
        meta?.patientName,
        meta?.chiefComplaint,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      return haystacks.includes(query);
    });
  }, [alerts, searchQuery, sessionMeta]);

  const groupedAlerts = useMemo(() => {
    const sorted = [...visibleAlerts].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );

    return sorted.reduce<Array<{ key: string; label: string; items: typeof visibleAlerts }>>(
      (groups, alert) => {
        const key = getDateKey(alert.createdAt);
        const existing = groups.find((group) => group.key === key);
        if (existing) {
          existing.items.push(alert);
          return groups;
        }

        groups.push({
          key,
          label: getDateLabel(alert.createdAt),
          items: [alert],
        });
        return groups;
      },
      [],
    );
  }, [visibleAlerts]);

  const totalAlerts = allTotalCount || alerts.length;
  const acknowledgedCount = Math.max(totalAlerts - unacknowledgedCount, 0);

  return (
    <div className="space-y-6 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">Triage Workspace</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">紅旗警示</h1>
            <p className="mt-2 max-w-3xl text-body text-ink-secondary">
              先處理未處理警示，再進一步查看場次與逐字稿。這一頁應該先幫你找出需要優先處理的人，而不是把所有警示平鋪成同一層。
            </p>
          </div>
          <div className="rounded-card border border-red-200 bg-red-50/70 px-4 py-3 text-body font-medium text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-300">
            目前未處理 {unacknowledgedCount} 筆
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <AlertSummaryCard
            title="全部警示"
            value={totalAlerts}
            helper="目前系統中的警示總量"
            toneClass="border-edge"
          />
          <AlertSummaryCard
            title="未處理"
            value={unacknowledgedCount}
            helper="仍待醫師確認或註記"
            toneClass="border-red-200 bg-red-50/70 dark:border-red-900/50 dark:bg-red-950/20"
          />
          <AlertSummaryCard
            title="已處理"
            value={acknowledgedCount}
            helper="已被醫師確認處理"
            toneClass="border-green-200 bg-green-50/70 dark:border-green-900/50 dark:bg-green-950/20"
          />
          <AlertSummaryCard
            title="當前結果"
            value={visibleAlerts.length}
            helper={searchQuery ? '已套用搜尋條件' : '目前篩選條件下的清單數量'}
            toneClass="border-primary-200 bg-primary-50/70 dark:border-primary-900/50 dark:bg-primary-950/20"
          />
        </div>
      </section>

      <section className="card">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap gap-2">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.key}
                className={`rounded-pill px-4 py-2 text-body font-medium transition-colors ${
                  filter === tab.key
                    ? 'bg-primary-600 text-white shadow-sm'
                    : 'btn-secondary'
                }`}
                onClick={() => setFilter(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="w-full xl:max-w-sm">
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜尋病患、主訴或警示標題"
              className="input-base h-11"
            />
          </div>
        </div>
      </section>

      {error ? <ErrorState message={error} onRetry={() => fetchAlerts(true)} /> : null}

      {!error && isLoading && alerts.length === 0 ? (
        <AlertListSkeleton />
      ) : !error && visibleAlerts.length === 0 ? (
        <EmptyState title="無警示" message="目前沒有符合條件的紅旗警示" />
      ) : (
        <div className="space-y-6">
          {isLoading ? (
            <div className="rounded-card border border-edge bg-white px-4 py-3 text-small text-ink-muted shadow-card dark:border-dark-border dark:bg-dark-card">
              警示資料更新中...
            </div>
          ) : null}

          {groupedAlerts.map((group) => (
            <section key={group.key} className="space-y-3">
              <div>
                <h2 className="text-h3 text-ink-heading dark:text-white">{group.label}</h2>
                <p className="mt-1 text-small text-ink-muted">{group.items.length} 筆警示</p>
              </div>

              <div className="space-y-3">
                {group.items.map((alert) => {
                  const meta = sessionMeta[alert.sessionId];
                  return (
                    <AlertItem
                      key={alert.id}
                      id={alert.id}
                      title={alert.title}
                      description={alert.description}
                      severity={alert.severity}
                      patientName={meta?.patientName}
                      chiefComplaint={meta?.chiefComplaint}
                      sessionStatus={meta?.sessionStatus}
                      triggerReason={alert.triggerReason}
                      suggestedActionCount={alert.suggestedActions?.length}
                      createdAt={alert.createdAt}
                      isAcknowledged={!!alert.acknowledgedAt}
                      onAcknowledge={() => acknowledgeAlert(alert.id)}
                      onViewDetail={() => navigate(`/alerts/${alert.id}`)}
                      onClick={() => navigate(`/alerts/${alert.id}`)}
                    />
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
