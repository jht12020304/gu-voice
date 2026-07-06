// =============================================================================
// 紅旗警示列表頁
// =============================================================================

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import { useAlertStore } from '../../stores/alertStore';
import { useRedFlagAlerts } from '../../hooks/useRedFlagAlerts';
import AlertItem from '../../components/dashboard/AlertItem';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import * as sessionsApi from '../../services/api/sessions';
import type { Session } from '../../types';
import { formatDate } from '../../utils/format';

function getFilterTabs(t: TFunction) {
  return [
    { key: 'all' as const, label: t('alertList.filters.all', '全部') },
    { key: 'unacknowledged' as const, label: t('alertList.filters.unacknowledged', '未處理') },
    { key: 'acknowledged' as const, label: t('alertList.filters.acknowledged', '已處理') },
  ];
}

interface AlertSessionMeta {
  patientName: string;
  chiefComplaint: string;
  sessionStatus: string;
}

function sessionStatusLabel(status: Session['status'] | undefined, t: TFunction): string {
  switch (status) {
    case 'waiting':
      return t('alertList.sessionStatus.waiting', '等待中');
    case 'in_progress':
      return t('alertList.sessionStatus.inProgress', '問診中');
    case 'completed':
      return t('alertList.sessionStatus.completed', '已完成');
    case 'aborted_red_flag':
      return t('alertList.sessionStatus.abortedRedFlag', '紅旗中止');
    case 'cancelled':
      return t('alertList.sessionStatus.cancelled', '已取消');
    default:
      return t('common:status.unknown', '未取得場次狀態');
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
  const { t, i18n } = useTranslation('dashboard');
  const {
    alerts,
    isLoading,
    error,
    filter,
    hasMore,
    fetchAlerts,
    fetchMore,
    setFilter,
    acknowledgeAlert,
    fetchUnacknowledgedCount,
    unacknowledgedCount,
    allTotalCount,
  } = useAlertStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [sessionMeta, setSessionMeta] = useState<Record<string, AlertSessionMeta>>({});
  const observerRef = useRef<IntersectionObserver>();
  const sentinelRef = useRef<HTMLDivElement>(null);

  // H-8 / M-17：訂閱儀表板 WS（new_red_flag / red_flag_acknowledged / initial_state /
  // stats_updated），收到後即時更新 alertStore，讓本頁與側欄徽章免重整即時刷新。
  useRedFlagAlerts();

  // §1e 安全：接上 store 的 fetchMore/hasMore 無限捲動，讓超過 20 筆的未處理 critical
  // 也能從 UI 取得（過去只抓首 20 筆，超出者永久看不到）。搜尋為前端過濾，仍持續載入更多至 store。
  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoading) {
          fetchMore();
        }
      },
      { threshold: 0.1 },
    );

    if (sentinelRef.current) observerRef.current.observe(sentinelRef.current);

    return () => observerRef.current?.disconnect();
  }, [hasMore, isLoading, fetchMore]);

  // 切換 UI 語言時 refetch：紅旗 title / triggerReason / suggestedActions 由後端依 Accept-Language 在地化。
  useEffect(() => {
    fetchAlerts(true);
    fetchUnacknowledgedCount();
  }, [fetchAlerts, fetchUnacknowledgedCount, i18n.resolvedLanguage]);

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
                patientName:
                  session.patient?.name ?? session.patientName ?? t('alert.detail.unknownPatient', '未知病患'),
                chiefComplaint:
                  session.chiefComplaintText ??
                  session.chiefComplaint?.name ??
                  t('common:doctor.patient.noComplaint', '未填寫主訴'),
                sessionStatus: sessionStatusLabel(session.status, t),
              },
            ] as const;
          } catch {
            return [
              sessionId,
              {
                patientName: t('alert.detail.unknownPatient', '未知病患'),
                chiefComplaint: t('alertList.unknownComplaintFetchFailed', '未取得主訴'),
                sessionStatus: t('common:status.unknown', '未取得場次狀態'),
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
  }, [alerts, sessionMeta, t]);

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
    // §1e 安全：日期分組內以「未處理優先 → 嚴重度(critical>high>medium) → 較新」排序，
    // 避免較舊但未處理的 critical 被當日較新的 medium/high 推到看不見的位置。
    const severityRank: Record<string, number> = { critical: 0, high: 1, medium: 2 };
    const priority = (a: (typeof visibleAlerts)[number], b: (typeof visibleAlerts)[number]) => {
      const ackA = a.acknowledgedAt ? 1 : 0;
      const ackB = b.acknowledgedAt ? 1 : 0;
      if (ackA !== ackB) return ackA - ackB; // 未處理在前
      const sevA = severityRank[a.severity] ?? 9;
      const sevB = severityRank[b.severity] ?? 9;
      if (sevA !== sevB) return sevA - sevB; // 嚴重度高在前
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(); // 較新在前
    };
    const sorted = [...visibleAlerts].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );

    const groups = sorted.reduce<
      Array<{ key: string; label: string; items: typeof visibleAlerts }>
    >((acc, alert) => {
      const key = getDateKey(alert.createdAt);
      const existing = acc.find((group) => group.key === key);
      if (existing) {
        existing.items.push(alert);
        return acc;
      }
      acc.push({ key, label: getDateLabel(alert.createdAt), items: [alert] });
      return acc;
    }, []);
    groups.forEach((g) => g.items.sort(priority));
    return groups;
  }, [visibleAlerts]);

  const totalAlerts = allTotalCount || alerts.length;
  const acknowledgedCount = Math.max(totalAlerts - unacknowledgedCount, 0);
  const filterTabs = getFilterTabs(t);

  return (
    <div className="space-y-6 animate-fade-in">
      <section className="card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">{t('alertList.eyebrow', '檢傷工作台')}</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">{t('sidebar.nav.redFlagAlerts', '紅旗警示')}</h1>
            <p className="mt-2 max-w-3xl text-body text-ink-secondary">
              {t('alertList.subtitle', '先處理未處理警示，再進一步查看場次與逐字稿。這一頁應該先幫你找出需要優先處理的人，而不是把所有警示平鋪成同一層。')}
            </p>
          </div>
          <div className="rounded-card border border-red-200 bg-red-50/70 px-4 py-3 text-body font-medium text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-300">
            {t('alertList.unacknowledgedBanner', { count: unacknowledgedCount })}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <AlertSummaryCard
            title={t('alertList.summary.totalTitle', '全部警示')}
            value={totalAlerts}
            helper={t('alertList.summary.totalHelper', '目前系統中的警示總量')}
            toneClass="border-edge"
          />
          <AlertSummaryCard
            title={t('alertList.filters.unacknowledged', '未處理')}
            value={unacknowledgedCount}
            helper={t('alertList.summary.unacknowledgedHelper', '仍待醫師確認或註記')}
            toneClass="border-red-200 bg-red-50/70 dark:border-red-900/50 dark:bg-red-950/20"
          />
          <AlertSummaryCard
            title={t('alertList.filters.acknowledged', '已處理')}
            value={acknowledgedCount}
            helper={t('alertList.summary.acknowledgedHelper', '已被醫師確認處理')}
            toneClass="border-green-200 bg-green-50/70 dark:border-green-900/50 dark:bg-green-950/20"
          />
          <AlertSummaryCard
            title={t('alertList.summary.currentTitle', '當前結果')}
            value={visibleAlerts.length}
            helper={
              searchQuery
                ? t('alertList.summary.currentHelperFiltered', '已套用搜尋條件')
                : t('alertList.summary.currentHelperDefault', '目前篩選條件下的清單數量')
            }
            toneClass="border-primary-200 bg-primary-50/70 dark:border-primary-900/50 dark:bg-primary-950/20"
          />
        </div>
      </section>

      <section className="card">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap gap-2">
            {filterTabs.map((tab) => (
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
              placeholder={t('alertList.searchPlaceholder', '搜尋病患、主訴或警示標題')}
              className="input-base h-11"
            />
          </div>
        </div>
      </section>

      {error ? <ErrorState message={error} onRetry={() => fetchAlerts(true)} /> : null}

      {!error && isLoading && alerts.length === 0 ? (
        <AlertListSkeleton />
      ) : !error && visibleAlerts.length === 0 ? (
        <EmptyState title={t('alertList.emptyTitle', '無警示')} message={t('alertList.emptyMessage', '目前沒有符合條件的紅旗警示')} />
      ) : (
        <div className="space-y-6">
          {isLoading ? (
            <div className="rounded-card border border-edge bg-white px-4 py-3 text-small text-ink-muted shadow-card dark:border-dark-border dark:bg-dark-card">
              {t('alertList.updating', '警示資料更新中...')}
            </div>
          ) : null}

          {groupedAlerts.map((group) => (
            <section key={group.key} className="space-y-3">
              <div>
                <h2 className="text-h3 text-ink-heading dark:text-white">{group.label}</h2>
                <p className="mt-1 text-small text-ink-muted">{t('alertList.groupCount', { count: group.items.length })}</p>
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

          <div ref={sentinelRef} className="h-4" />

          {isLoading && alerts.length > 0 ? (
            <div className="flex justify-center py-2">
              <LoadingSpinner size="sm" />
            </div>
          ) : !hasMore ? (
            <p className="py-2 text-center text-small text-ink-muted">
              {t('common:pagination.allLoaded', '已顯示全部')}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
