// =============================================================================
// 問診完成頁 — 顯示摘要、報告狀態、建議後續動作
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import { useReportStore } from '../../stores/reportStore';
import { formatDate } from '../../utils/format';
import type { Session } from '../../types';
import * as sessionsApi from '../../services/api/sessions';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockSession: Session = {
  id: 'mock-session-001',
  patientId: 'mock-patient-001',
  doctorId: 'mock-doctor-001',
  chiefComplaintId: 'cc1',
  chiefComplaintText: '血尿持續三天',
  status: 'completed',
  redFlag: true,
  redFlagReason: '肉眼血尿持續超過 48 小時',
  language: 'zh-TW',
  startedAt: '2026-04-10T13:30:00Z',
  completedAt: '2026-04-10T13:45:00Z',
  durationSeconds: 900,
  createdAt: '2026-04-10T13:30:00Z',
  updatedAt: '2026-04-10T13:45:00Z',
};

export default function SessionCompletePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('session');
  const { selectedReport, isLoading: reportLoading, fetchReportBySession } = useReportStore();
  const [session, setSession] = useState<Session | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(true);

  useEffect(() => {
    if (!sessionId) return;

    async function load() {
      if (IS_MOCK) {
        setSession(mockSession);
        setIsLoadingSession(false);
      } else {
        try {
          const s = await sessionsApi.getSession(sessionId!);
          setSession(s);
        } catch {
          // 靜默
        } finally {
          setIsLoadingSession(false);
        }
      }
      fetchReportBySession(sessionId!);
    }
    load();
  }, [sessionId, fetchReportBySession]);

  if (isLoadingSession) return <LoadingSpinner fullPage message={t('complete.loading')} />;

  const report = selectedReport;
  const hasReport = !!report && report.status === 'generated';

  const reviewStatusLabel = report
    ? report.reviewStatus === 'approved'
      ? t('complete.reviewStatusApproved')
      : report.reviewStatus === 'revision_needed'
        ? t('complete.reviewStatusRevisionNeeded')
        : t('complete.reviewStatusPending')
    : '';

  return (
    <div className="mx-auto max-w-2xl px-6 py-10 animate-fade-in">

      {/* 完成標誌 */}
      <div className="mb-10 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
          <svg className="h-7 w-7 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        </div>
        <h1 className="text-h1 font-semibold tracking-tight text-ink-heading dark:text-white">{t('complete.title')}</h1>
        <p className="mt-2 text-body text-ink-muted dark:text-white/50">
          {t('complete.subtitle')}
        </p>
      </div>

      {/* 問診摘要 */}
      {session && (
        <div className="rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
          <div className="px-5 py-4 border-b border-edge/60 dark:border-dark-border">
            <h2 className="text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">{t('complete.summaryTitle')}</h2>
          </div>

          <div className="divide-y divide-edge/60 dark:divide-dark-border">
            <div className="flex items-center justify-between px-5 py-3.5">
              <span className="text-small text-ink-muted dark:text-white/50">{t('complete.summaryChiefComplaint')}</span>
              <span className="text-body font-medium text-ink-heading dark:text-white">
                {session.chiefComplaintText}
              </span>
            </div>
            <div className="flex items-center justify-between px-5 py-3.5">
              <span className="text-small text-ink-muted dark:text-white/50">{t('complete.summaryStartedAt')}</span>
              <span className="text-body text-ink-body dark:text-white/75">
                {formatDate(session.startedAt)}
              </span>
            </div>
            <div className="flex items-center justify-between px-5 py-3.5">
              <span className="text-small text-ink-muted dark:text-white/50">{t('complete.summaryDuration')}</span>
              <span className="text-body font-data text-ink-body dark:text-white/75">
                {session.durationSeconds
                  ? t('complete.durationMinutes', { minutes: Math.round(session.durationSeconds / 60) })
                  : t('complete.durationEmpty')}
              </span>
            </div>

            {session.redFlag && (
              <div className="px-5 py-3.5">
                <div className="rounded-card bg-red-50 px-4 py-3 dark:bg-red-900/20">
                  <p className="text-small font-medium text-red-700 dark:text-red-300">{t('complete.redFlagTitle')}</p>
                  <p className="mt-0.5 text-small text-red-600/80 dark:text-red-400/70">{session.redFlagReason}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* AI 分析報告 */}
      <div className="mt-4 rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
        <div className="px-5 py-4 border-b border-edge/60 dark:border-dark-border">
          <h2 className="text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">{t('complete.reportTitle')}</h2>
        </div>

        <div className="px-5 py-4">
          {reportLoading ? (
            <div className="flex items-center gap-3">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
              <p className="text-body text-ink-muted dark:text-white/50">{t('complete.reportAnalyzing')}</p>
            </div>
          ) : hasReport ? (
            <div className="space-y-3">
              {report.summary && (
                <p className="text-body leading-relaxed text-ink-body dark:text-white/80">
                  {report.summary}
                </p>
              )}
              {report.icd10Codes && report.icd10Codes.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {report.icd10Codes.map((code) => (
                    <span key={code} className="rounded-pill border border-primary-200 bg-primary-50 px-2.5 py-0.5 font-data text-small text-primary-700 dark:border-primary-800 dark:bg-primary-950 dark:text-primary-300">
                      {code}
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <span className={`badge ${report.reviewStatus === 'approved' ? 'badge-completed' : report.reviewStatus === 'revision_needed' ? 'badge-red-flag' : 'badge-waiting'}`}>
                  {reviewStatusLabel}
                </span>
                {report.aiConfidenceScore !== undefined && (
                  <span className="text-small font-data text-ink-muted dark:text-white/40">
                    {t('complete.aiConfidence', { percent: Math.round(report.aiConfidenceScore * 100) })}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <p className="text-body text-ink-muted dark:text-white/40">{t('complete.reportEmpty')}</p>
          )}
        </div>
      </div>

      {/* 後續注意事項 */}
      <div className="mt-4 rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
        <div className="px-5 py-4 border-b border-edge/60 dark:border-dark-border">
          <h2 className="text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">{t('complete.nextStepsTitle')}</h2>
        </div>
        <ul className="divide-y divide-edge/60 px-5 dark:divide-dark-border">
          {(['complete.nextStep1', 'complete.nextStep2', 'complete.nextStep3'] as const).map((key) => (
            <li key={key} className="flex items-start gap-3 py-3.5">
              <span className="mt-px shrink-0 text-ink-muted dark:text-white/30">—</span>
              <span className="text-body text-ink-body dark:text-white/80">{t(key)}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* 操作按鈕 */}
      <div className="mt-6 flex gap-3">
        <button
          className="btn-primary flex-1 py-3"
          onClick={() => navigate('/patient')}
        >
          {t('complete.actionHome')}
        </button>
        <button
          className="btn-secondary flex-1 py-3"
          onClick={() => navigate('/patient/history')}
        >
          {t('complete.actionHistory')}
        </button>
      </div>
    </div>
  );
}
