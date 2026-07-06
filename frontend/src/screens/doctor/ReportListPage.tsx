// =============================================================================
// SOAP 報告列表頁 — 審閱入口
// =============================================================================

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import type { SOAPReport, Session } from '../../types';
import { formatDate } from '../../utils/format';
import { useReportStore } from '../../stores/reportStore';
import * as reportsApi from '../../services/api/reports';
import * as sessionsApi from '../../services/api/sessions';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

type ReviewFilter = '' | 'pending' | 'approved' | 'revision_needed';

interface ReportMeta {
  patientName: string;
  complaint: string;
  redFlag: boolean;
  sessionStatus?: Session['status'];
}

type MockReport = SOAPReport & {
  patientName: string;
  complaint: string;
  redFlag?: boolean;
};

const mockReports: MockReport[] = [
  {
    id: 'rpt-001',
    sessionId: 's1',
    status: 'generated',
    reviewStatus: 'pending',
    summary: '45歲男性因肉眼血尿持續三天就診，AI 已整理血尿特徵、伴隨頻尿及排尿疼痛。',
    aiConfidenceScore: 0.87,
    icd10Codes: ['R31.0', 'R30.0'],
    generatedAt: '2026-04-10T14:00:00Z',
    createdAt: '2026-04-10T14:00:00Z',
    updatedAt: '2026-04-10T14:00:00Z',
    patientName: '陳小明',
    complaint: '血尿持續三天',
    redFlag: true,
  },
  {
    id: 'rpt-002',
    sessionId: 'rs1',
    status: 'generated',
    reviewStatus: 'approved',
    summary: '60歲女性攝護腺症狀，PSA 偏高需追蹤，建議門診安排後續檢查。',
    aiConfidenceScore: 0.91,
    icd10Codes: ['R97.20'],
    reviewedBy: 'mock-doctor-001',
    reviewedAt: '2026-04-10T12:00:00Z',
    generatedAt: '2026-04-10T11:35:00Z',
    createdAt: '2026-04-10T11:35:00Z',
    updatedAt: '2026-04-10T12:00:00Z',
    patientName: '黃美芳',
    complaint: '排尿不順與夜尿',
  },
  {
    id: 'rpt-003',
    sessionId: 'rs2',
    status: 'generated',
    reviewStatus: 'approved',
    summary: '43歲男性反覆泌尿道感染，建議影像學檢查與菌培養追蹤。',
    aiConfidenceScore: 0.84,
    icd10Codes: ['N39.0'],
    reviewedBy: 'mock-doctor-001',
    reviewedAt: '2026-04-10T11:00:00Z',
    generatedAt: '2026-04-10T10:50:00Z',
    createdAt: '2026-04-10T10:50:00Z',
    updatedAt: '2026-04-10T11:00:00Z',
    patientName: '吳建宏',
    complaint: '反覆泌尿道感染',
  },
  {
    id: 'rpt-004',
    sessionId: 'rs4',
    status: 'generated',
    reviewStatus: 'revision_needed',
    summary: '50歲男性勃起功能障礙，AI 摘要已提出潛在心血管風險，但需補上相關評估依據。',
    aiConfidenceScore: 0.78,
    icd10Codes: ['N52.9'],
    reviewNotes: '需補充心血管評估與用藥史，並在逐字稿中標出對應證據。',
    generatedAt: '2026-04-10T09:20:00Z',
    createdAt: '2026-04-10T09:20:00Z',
    updatedAt: '2026-04-10T09:30:00Z',
    patientName: '周志豪',
    complaint: '勃起功能障礙',
  },
];

const REVIEW_TAB_KEYS: ReviewFilter[] = ['', 'pending', 'approved', 'revision_needed'];

function reviewTabLabel(key: ReviewFilter, t: TFunction): string {
  switch (key) {
    case 'pending':
      return t('reportList.tabs.pending', '待審閱');
    case 'approved':
      return t('reportList.tabs.approved', '已核准');
    case 'revision_needed':
      return t('reportList.tabs.revisionNeeded', '需修改');
    default:
      return t('reportList.tabs.all', '全部');
  }
}

function getReportTimestamp(report: SOAPReport): string {
  return report.generatedAt || report.updatedAt || report.createdAt;
}

function getDateKey(report: SOAPReport): string {
  const date = new Date(getReportTimestamp(report));
  if (Number.isNaN(date.getTime())) return 'unknown';
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getDayLabel(report: SOAPReport): string {
  return formatDate(getReportTimestamp(report), {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
}

function reviewStatusLabel(status: SOAPReport['reviewStatus'], t: TFunction): string {
  switch (status) {
    case 'approved':
      return t('reportList.tabs.approved', '已核准');
    case 'revision_needed':
      return t('reportList.tabs.revisionNeeded', '需修改');
    default:
      return t('reportList.tabs.pending', '待審閱');
  }
}

function reviewStatusClass(status: SOAPReport['reviewStatus']): string {
  switch (status) {
    case 'approved':
      return 'bg-green-50 text-green-700 ring-1 ring-green-200 dark:bg-green-950/40 dark:text-green-300 dark:ring-green-900';
    case 'revision_needed':
      return 'bg-red-50 text-red-700 ring-1 ring-red-200 dark:bg-red-950/30 dark:text-red-300 dark:ring-red-900';
    default:
      return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-900';
  }
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

function countByStatus(reports: SOAPReport[], status: SOAPReport['reviewStatus']): number {
  return reports.filter((report) => report.reviewStatus === status).length;
}

export default function ReportListPage() {
  const { t } = useTranslation('dashboard');
  const navigate = useLocalizedNavigate();
  const { reports, isLoading: storeLoading, hasMore, fetchReports, fetchMore } = useReportStore();
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [summaryReports, setSummaryReports] = useState<SOAPReport[]>(IS_MOCK ? mockReports : []);
  const [sessionMeta, setSessionMeta] = useState<Record<string, ReportMeta>>({});
  const isLoading = IS_MOCK ? false : storeLoading;
  const observerRef = useRef<IntersectionObserver>();
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (IS_MOCK) return;
    fetchReports({ reviewStatus: reviewFilter || undefined });
  }, [reviewFilter, fetchReports]);

  // §5a：接上 store 的 fetchMore/hasMore 無限捲動，讓 >20 筆的報告可達（過去只抓首 20 筆）。
  // 搜尋為前端過濾，仍持續載入更多至 store。
  useEffect(() => {
    if (IS_MOCK) return;
    if (observerRef.current) observerRef.current.disconnect();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !storeLoading) {
          fetchMore({ reviewStatus: reviewFilter || undefined });
        }
      },
      { threshold: 0.1 },
    );

    if (sentinelRef.current) observerRef.current.observe(sentinelRef.current);

    return () => observerRef.current?.disconnect();
  }, [hasMore, storeLoading, fetchMore, reviewFilter]);

  useEffect(() => {
    if (IS_MOCK) return;

    let cancelled = false;

    async function loadSummaryReports() {
      try {
        const response = await reportsApi.getReports({ limit: 100 });
        if (!cancelled) {
          setSummaryReports(response.data);
        }
      } catch {
        if (!cancelled) {
          setSummaryReports([]);
        }
      }
    }

    loadSummaryReports();

    return () => {
      cancelled = true;
    };
  }, []);

  const displayReports = useMemo(() => {
    if (IS_MOCK) {
      return reviewFilter ? mockReports.filter((report) => report.reviewStatus === reviewFilter) : mockReports;
    }
    return reports;
  }, [reports, reviewFilter]);

  useEffect(() => {
    if (IS_MOCK || displayReports.length === 0) return;

    let cancelled = false;

    async function loadSessionMeta() {
      const missingSessionIds = displayReports
        .map((report) => report.sessionId)
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
                patientName: session.patient?.name ?? session.patientName ?? session.patientId,
                complaint:
                  session.chiefComplaintText ??
                  session.chiefComplaint?.name ??
                  t('reportList.complaintEmpty', '未填寫主訴'),
                redFlag: session.redFlag,
                sessionStatus: session.status,
              },
            ] as const;
          } catch {
            return [
              sessionId,
              {
                patientName: sessionId,
                complaint: t('reportList.complaintFetchFailed', '未取得主訴'),
                redFlag: false,
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
  }, [displayReports, sessionMeta, t]);

  // 病患姓名 / 病歷號 / 主訴 前端搜尋（比照 AlertListPage：姓名不在 report 本體，故對已載入清單過濾）。
  const filteredReports = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return displayReports;
    return displayReports.filter((report) => {
      const meta = IS_MOCK
        ? { patientName: (report as MockReport).patientName, complaint: (report as MockReport).complaint }
        : sessionMeta[report.sessionId];
      const haystack = [meta?.patientName, meta?.complaint, report.sessionId]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [displayReports, searchQuery, sessionMeta]);

  const overviewReports = summaryReports.length > 0 ? summaryReports : displayReports;
  const groupedReports = useMemo(() => {
    const sorted = [...filteredReports].sort(
      (a, b) => new Date(getReportTimestamp(b)).getTime() - new Date(getReportTimestamp(a)).getTime(),
    );

    return sorted.reduce<Array<{ key: string; label: string; reports: SOAPReport[] }>>((groups, report) => {
      const key = getDateKey(report);
      const existing = groups.find((group) => group.key === key);
      if (existing) {
        existing.reports.push(report);
        return groups;
      }
      groups.push({
        key,
        label: getDayLabel(report),
        reports: [report],
      });
      return groups;
    }, []);
  }, [filteredReports]);

  return (
    <div className="animate-fade-in space-y-6">
      <section className="card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">{t('reportList.eyebrow', '審閱工作台')}</p>
            <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">{t('sidebar.nav.soapReports', 'SOAP 報告')}</h1>
            <p className="mt-2 max-w-3xl text-body text-ink-secondary">
              {t('reportList.subtitle', '集中查看 AI 問診摘要、待審閱報告與退回修改紀錄。先從待審閱開始，再回到逐字稿核對內容依據。')}
            </p>
          </div>
          <div className="rounded-card border border-primary-100 bg-primary-50/70 px-4 py-3 text-body text-primary-700 dark:border-primary-900/50 dark:bg-primary-950/20 dark:text-primary-300">
            {t('reportList.displayCount', { count: filteredReports.length })}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-card border border-edge bg-white px-4 py-4 shadow-card dark:border-dark-border dark:bg-dark-card">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-ink-muted">{t('reportList.summaryTotal', '全部報告')}</p>
            <p className="mt-3 text-display text-ink-heading dark:text-white">{overviewReports.length}</p>
          </div>
          <div className="rounded-card border border-amber-200 bg-amber-50/70 px-4 py-4 shadow-card dark:border-amber-900/50 dark:bg-amber-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300">{t('reportList.tabs.pending', '待審閱')}</p>
            <p className="mt-3 text-display text-amber-700 dark:text-amber-300">{countByStatus(overviewReports, 'pending')}</p>
          </div>
          <div className="rounded-card border border-green-200 bg-green-50/70 px-4 py-4 shadow-card dark:border-green-900/50 dark:bg-green-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-green-700 dark:text-green-300">{t('reportList.tabs.approved', '已核准')}</p>
            <p className="mt-3 text-display text-green-700 dark:text-green-300">{countByStatus(overviewReports, 'approved')}</p>
          </div>
          <div className="rounded-card border border-red-200 bg-red-50/70 px-4 py-4 shadow-card dark:border-red-900/50 dark:bg-red-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-red-700 dark:text-red-300">{t('reportList.tabs.revisionNeeded', '需修改')}</p>
            <p className="mt-3 text-display text-red-700 dark:text-red-300">{countByStatus(overviewReports, 'revision_needed')}</p>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap gap-2">
            {REVIEW_TAB_KEYS.map((key) => (
              <button
                key={key || 'all'}
                type="button"
                className={`rounded-pill px-4 py-2 text-body font-medium transition-colors ${
                  reviewFilter === key
                    ? 'bg-primary-600 text-white shadow-sm'
                    : 'bg-surface-secondary text-ink-secondary hover:text-ink-heading dark:bg-dark-surface dark:text-dark-text-muted dark:hover:text-white'
                }`}
                onClick={() => setReviewFilter(key)}
              >
                {reviewTabLabel(key, t)}
              </button>
            ))}
          </div>

          <div className="w-full xl:max-w-sm">
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('reportList.searchPlaceholder', '搜尋病患姓名或病歷號')}
              className="input-base h-11"
            />
          </div>
        </div>
      </section>

      {isLoading && displayReports.length === 0 ? (
        <LoadingSpinner fullPage />
      ) : filteredReports.length === 0 ? (
        <EmptyState title={t('reportList.emptyTitle', '無報告')} message={t('reportList.emptyMessage', '目前沒有符合條件的 SOAP 報告')} />
      ) : (
        <div className="space-y-6">
          {groupedReports.map((group) => (
            <section key={group.key} className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-h3 text-ink-heading dark:text-white">{group.label}</h2>
                  <p className="mt-1 text-small text-ink-muted">{t('reportList.groupCount', { count: group.reports.length })}</p>
                </div>
              </div>

              <div className="space-y-3">
                {group.reports.map((report) => {
                  const meta = IS_MOCK
                    ? {
                        patientName: (report as MockReport).patientName,
                        complaint: (report as MockReport).complaint,
                        redFlag: Boolean((report as MockReport).redFlag),
                        sessionStatus: 'completed' as Session['status'],
                      }
                    : sessionMeta[report.sessionId];

                  return (
                    <button
                      key={report.id}
                      type="button"
                      className="card w-full text-left transition-all hover:-translate-y-0.5 hover:shadow-lg"
                      onClick={() => navigate(`/reports/${report.sessionId}`)}
                    >
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-h3 text-ink-heading dark:text-white">
                              {meta?.patientName ?? report.sessionId}
                            </h3>
                            <span className={`rounded-pill px-3 py-1 text-small font-semibold ${reviewStatusClass(report.reviewStatus)}`}>
                              {reviewStatusLabel(report.reviewStatus, t)}
                            </span>
                            {meta?.redFlag ? (
                              <span className="rounded-pill bg-red-50 px-3 py-1 text-small font-semibold text-red-600 ring-1 ring-red-200 dark:bg-red-950/20 dark:text-red-300 dark:ring-red-900">
                                {t('reportList.redFlagBadge', '紅旗場次')}
                              </span>
                            ) : null}
                          </div>

                          <div className="mt-2 flex flex-wrap items-center gap-3 text-small text-ink-muted">
                            <span>{t('reportList.chiefComplaintLabel', { value: meta?.complaint ?? t('reportList.complaintFetchFailed', '未取得主訴') })}</span>
                            <span>{t('reportList.sessionStatusLabel', { value: sessionStatusLabel(meta?.sessionStatus, t) })}</span>
                          </div>

                          <p className="mt-4 line-clamp-3 text-body leading-relaxed text-ink-body dark:text-white/85">
                            {report.summary || t('reportList.summaryEmpty', '目前尚無 AI 摘要內容。')}
                          </p>

                          <div className="mt-4 flex flex-wrap items-center gap-3">
                            {report.icd10Codes && report.icd10Codes.length > 0 ? (
                              <div className="flex flex-wrap gap-2">
                                {report.icd10Codes.slice(0, 3).map((code) => (
                                  <span
                                    key={code}
                                    className="rounded-pill border border-primary-200 bg-primary-50 px-3 py-1 text-small font-data font-medium text-primary-700 dark:border-primary-800 dark:bg-primary-950/40 dark:text-primary-300"
                                  >
                                    {code}
                                  </span>
                                ))}
                              </div>
                            ) : null}

                            {report.aiConfidenceScore !== undefined ? (
                              <span className="text-small font-medium text-ink-muted">
                                {t('reportList.aiConfidence', { percent: Math.round(report.aiConfidenceScore * 100) })}
                              </span>
                            ) : null}
                          </div>

                          {report.reviewStatus === 'revision_needed' && report.reviewNotes ? (
                            <div className="mt-4 rounded-card border border-red-200 bg-red-50/70 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/10">
                              <p className="text-small font-semibold uppercase tracking-[0.14em] text-red-700 dark:text-red-300">
                                {t('reportList.revisionReason', '退回原因')}
                              </p>
                              <p className="mt-2 text-body text-red-700/90 dark:text-red-300/85">
                                {report.reviewNotes}
                              </p>
                            </div>
                          ) : null}
                        </div>

                        <div className="flex shrink-0 items-center gap-3 xl:flex-col xl:items-end">
                          <div className="text-right">
                            <p className="text-small font-semibold text-ink-heading dark:text-white">{t('reportList.reportTime', '報告時間')}</p>
                            <p className="mt-1 text-small text-ink-muted">
                              {formatDate(getReportTimestamp(report), {
                                month: '2-digit',
                                day: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </p>
                          </div>
                          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-secondary text-ink-placeholder dark:bg-dark-surface">
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                            </svg>
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}

          {!IS_MOCK ? (
            <>
              <div ref={sentinelRef} className="h-4" />
              {storeLoading && displayReports.length > 0 ? (
                <div className="flex justify-center py-2">
                  <LoadingSpinner size="sm" />
                </div>
              ) : !hasMore ? (
                <p className="py-2 text-center text-small text-ink-muted">
                  {t('common:pagination.allLoaded', '已顯示全部')}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
