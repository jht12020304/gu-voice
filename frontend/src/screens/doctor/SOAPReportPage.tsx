// =============================================================================
// SOAP 報告頁 — 審閱工作台
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { apiErrorMessage } from '../../services/api/client';
import { useShallow } from 'zustand/react/shallow';
import toast from 'react-hot-toast';
import { useLocalizedNavigate } from '../../i18n/paths';
import QuickOrdersCard from '../../components/medical/QuickOrdersCard';
import TranscriptPanel from '../../components/medical/TranscriptPanel';
import SOAPCard from '../../components/medical/SOAPCard';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import { useReportStore } from '../../stores/reportStore';
import * as reportsApi from '../../services/api/reports';
import * as sessionsApi from '../../services/api/sessions';
import type { Session } from '../../types';
import { formatDate, formatDuration } from '../../utils/format';
import { consultWindow } from '../../utils/consultWindow';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockSession: Session = {
  id: 's1',
  patientId: 'p1',
  doctorId: 'mock-doctor-001',
  chiefComplaintId: 'cc1',
  chiefComplaintText: '血尿持續三天',
  status: 'completed',
  redFlag: false,
  language: 'zh-TW',
  startedAt: '2026-04-10T13:30:00Z',
  completedAt: '2026-04-10T13:58:00Z',
  durationSeconds: 1680,
  createdAt: '2026-04-10T13:30:00Z',
  updatedAt: '2026-04-10T13:58:00Z',
  patient: {
    id: 'p1',
    userId: 'u1',
    medicalRecordNumber: 'MRN-2026-0001',
    name: '陳小明',
    gender: 'male',
    dateOfBirth: '1985-03-15',
    phone: '0912-345-678',
    createdAt: '2026-01-15T08:00:00Z',
    updatedAt: '2026-04-10T10:00:00Z',
  },
};

export default function SOAPReportPage() {
  const { t } = useTranslation('common');
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useLocalizedNavigate();
  const {
    selectedReport,
    conversations,
    isLoading,
    isLoadingConversations,
    error,
    fetchReportBySession,
    fetchConversations,
    reviewReport,
  } = useReportStore(
    useShallow((s) => ({
      selectedReport: s.selectedReport,
      conversations: s.conversations,
      isLoading: s.isLoading,
      isLoadingConversations: s.isLoadingConversations,
      error: s.error,
      fetchReportBySession: s.fetchReportBySession,
      fetchConversations: s.fetchConversations,
      reviewReport: s.reviewReport,
    })),
  );

  const [session, setSession] = useState<Session | null>(IS_MOCK ? mockSession : null);
  // §1d 安全：session 抓取失敗時不可靜默把「有紅旗場次」渲染成「無紅旗」。
  const [sessionLoadFailed, setSessionLoadFailed] = useState(false);
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewAction, setReviewAction] = useState<'approved' | 'revision_needed'>('approved');
  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [activeTab, setActiveTab] = useState<'report' | 'transcript'>('report');
  const report = selectedReport;
  useEffect(() => {
    if (!sessionId) return;

    fetchReportBySession(sessionId);
    fetchConversations(sessionId);

    if (IS_MOCK) {
      setSession({ ...mockSession, id: sessionId });
      return;
    }

    sessionsApi
      .getSession(sessionId)
      .then((data) => {
        setSession(data);
        setSessionLoadFailed(false);
      })
      .catch(() => {
        setSession(null);
        setSessionLoadFailed(true); // 顯性化，紅旗區塊改顯示「載入失敗」而非默默消失
      });
  }, [sessionId, fetchReportBySession, fetchConversations]);

  const handleReview = async () => {
    if (!selectedReport) return;
    // §5d 防禦：非 generated 的報告不可核准/退回（UI 已隱藏按鈕，此為第二道保險）。
    if (selectedReport.status !== 'generated') return;

    if (reviewAction === 'revision_needed' && !reviewNotes.trim()) {
      setReviewError(t('soap:review.notesRequiredError', '退回修改時必須填寫原因。'));
      return;
    }

    setIsSubmitting(true);
    setReviewError('');
    try {
      await reviewReport(selectedReport.id, {
        reviewStatus: reviewAction,
        reviewNotes: reviewNotes.trim() || undefined,
      });
      setShowReviewModal(false);
      setReviewNotes('');
    } catch (err) {
      setReviewError(apiErrorMessage(err, t, t('soap:review.submitError', '審閱送出失敗，請稍後再試。')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleExportPDF = async () => {
    if (!selectedReport || isExporting) return;

    setIsExporting(true);
    try {
      const blob = await reportsApi.exportReportPDF(selectedReport.id);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `soap-report-${selectedReport.id}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      toast.success(t('soap:export.success', 'PDF 已開始下載'));
    } catch (err) {
      toast.error(apiErrorMessage(err, t, t('soap:export.error', 'PDF 匯出失敗，請稍後再試')));
    } finally {
      setIsExporting(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message={t('soap:page.loadingReport', '載入報告...')} />;
  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => {
          if (!sessionId) return;
          fetchReportBySession(sessionId);
          fetchConversations(sessionId);
        }}
      />
    );
  }
  if (!report) return <ErrorState message={t('soap:page.notGenerated', '報告尚未產生')} />;

  const isReviewed = report.reviewStatus !== 'pending';
  const patientName =
    session?.patientName ??
    session?.patient?.name ??
    t('dashboard:alert.detail.unknownPatient', '未知病患');
  const complaint =
    session?.chiefComplaintText ||
    session?.chiefComplaint?.name ||
    report.subjective?.chiefComplaint ||
    t('doctor.patient.noComplaint', '未填寫主訴');
  const win = consultWindow(session, conversations.map((c) => c.createdAt));
  const clock = (ms: number) => new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  return (
    <div className={`animate-fade-in space-y-6 ${!isReviewed ? 'pb-28' : ''}`}>
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex items-start gap-3">
            <button
              className="rounded-card p-2 text-ink-placeholder transition-colors hover:bg-surface-tertiary hover:text-ink-secondary"
              onClick={() => navigate('/reports')}
              aria-label={t('soap:page.backToList')}
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>

            <div>
              <h1 className="text-h1 text-ink-heading dark:text-white">{patientName}</h1>
              <p className="mt-1 text-body text-ink-secondary">
                {complaint}
                {report.generatedAt ? <span className="text-ink-muted"> · {formatDate(report.generatedAt)}</span> : null}
              </p>
              {win.start != null || win.seconds != null ? (
                <p data-testid="consult-window" className="mt-1 text-small text-ink-muted font-data">
                  {win.start != null ? `${clock(win.start)}–${win.end != null ? clock(win.end) : ''}` : null}
                  {win.start != null && win.seconds != null ? ' · ' : null}
                  {win.seconds != null ? `${t('soap:page.consultDuration')} ${formatDuration(win.seconds)}` : null}
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <span
                  className={`badge ${
                    report.status === 'generated'
                      ? 'badge-completed'
                      : report.status === 'generating'
                        ? 'badge-in-progress'
                        : 'badge-red-flag'
                  }`}
                >
                  {report.status === 'generated'
                    ? t('soap:reportStatus.generated', '已產生')
                    : report.status === 'generating'
                      ? t('soap:reportStatus.generating', '產生中')
                      : t('soap:reportStatus.failed', '失敗')}
                </span>
                <span
                  className={`badge ${
                    report.reviewStatus === 'approved'
                      ? 'badge-completed'
                      : report.reviewStatus === 'revision_needed'
                        ? 'badge-red-flag'
                        : 'badge-waiting'
                  }`}
                >
                  {report.reviewStatus === 'approved'
                    ? t('soap:reviewStatus.approved', '已核准')
                    : report.reviewStatus === 'revision_needed'
                      ? t('soap:reviewStatus.revisionNeeded', '需修改')
                      : t('soap:reviewStatus.pending', '待審閱')}
                </span>
                {report.aiConfidenceScore !== undefined ? (
                  <span className="rounded-pill bg-primary-50 px-3 py-1 text-small font-semibold text-primary-700 dark:bg-primary-950/40 dark:text-primary-300">
                    {t('soap:page.aiConfidence', { percent: Math.round(report.aiConfidenceScore * 100) })}
                  </span>
                ) : null}
                {session?.redFlag ? (
                  <span className="rounded-pill bg-red-50 px-3 py-1 text-small font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
                    {t('soap:meta.redFlagSession', '紅旗場次')}
                  </span>
                ) : sessionLoadFailed ? (
                  <span className="rounded-pill bg-amber-50 px-3 py-1 text-small font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
                    {t('soap:meta.redFlagLoadFailedBadge', '⚠ 紅旗狀態載入失敗')}
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
              onClick={handleExportPDF}
              disabled={isExporting || report.status !== 'generated'}
            >
              {isExporting ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span className="ml-2">{t('soap:export.loading', '匯出中...')}</span>
                </>
              ) : (
                <>
                  <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                  </svg>
                  {t('soap:export.button', '匯出 PDF')}
                </>
              )}
            </button>
          </div>
        </div>
      </section>

      {session?.redFlag ? (
        <div className="card border-red-200 bg-red-50/70 dark:border-red-900/50 dark:bg-red-950/10">
          <h2 className="text-h3 text-red-700 dark:text-red-400">{t('soap:redFlag.title', '紅旗註記')}</h2>
          <p className="mt-3 text-body leading-relaxed text-red-700/90 dark:text-red-300/85">
            {session.redFlagReason || t('soap:redFlag.defaultReason', '此場次曾觸發紅旗警示，建議審閱時特別核對摘要與逐字稿。')}
          </p>
        </div>
      ) : sessionLoadFailed ? (
        <div className="card border-amber-200 bg-amber-50/70 dark:border-amber-900/50 dark:bg-amber-950/10">
          <h2 className="text-h3 text-amber-700 dark:text-amber-400">{t('soap:redFlag.loadFailedTitle', '紅旗狀態載入失敗')}</h2>
          <p className="mt-3 text-body leading-relaxed text-amber-800/90 dark:text-amber-300/85">
            {t('soap:redFlag.loadFailedDescription', '無法載入此場次的紅旗狀態，請重新整理頁面後再核對，切勿逕自當作「無紅旗」。')}
          </p>
        </div>
      ) : null}

      {isReviewed && report.reviewNotes ? (
        <div className="card">
          <h2 className="text-h3 text-ink-heading dark:text-white">{t('soap:reviewNotesCard.title', '審閱備註')}</h2>
          <p className="mt-3 text-body leading-relaxed text-ink-body dark:text-white/85">{report.reviewNotes}</p>
          {report.reviewedAt ? (
            <p className="mt-3 text-small text-ink-muted">{t('soap:reviewNotesCard.reviewedAtLabel', { date: formatDate(report.reviewedAt) })}</p>
          ) : null}
        </div>
      ) : null}

      <div className="lg:hidden">
        <div className="flex gap-1 rounded-card bg-surface-secondary p-1 dark:bg-dark-surface">
          <button
            className={`flex-1 rounded-card px-4 py-2 text-body font-medium transition-colors ${
              activeTab === 'report'
                ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
                : 'text-ink-muted hover:text-ink-secondary'
            }`}
            onClick={() => setActiveTab('report')}
          >
            {t('soap:tabs.report', 'SOAP 結構化報告')}
          </button>
          <button
            className={`flex-1 rounded-card px-4 py-2 text-body font-medium transition-colors ${
              activeTab === 'transcript'
                ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
                : 'text-ink-muted hover:text-ink-secondary'
            }`}
            onClick={() => setActiveTab('transcript')}
          >
            {t('soap:tabs.transcript', '對話逐字稿')}
          </button>
        </div>
      </div>

      <div className="space-y-4 lg:grid lg:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.9fr)] lg:items-start lg:gap-6 lg:space-y-0">
        <div className={`space-y-4 lg:block ${activeTab === 'report' ? '' : 'hidden'}`}>
          <div className="rounded-panel border border-primary-100 bg-primary-50/70 p-5 dark:border-primary-900/50 dark:bg-primary-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-primary-700 dark:text-primary-300">{t('soap:page.clinicalSummaryEyebrow', '臨床摘要')}</p>
            <p className="mt-3 text-body-lg leading-relaxed text-ink-body dark:text-white/85">
              {report.summary || report.assessment?.clinicalImpression || t('soap:page.noSummary', '目前尚無可顯示的摘要。')}
            </p>
            {report.icd10Codes && report.icd10Codes.length > 0 ? (
              <>
                {report.icd10Verified === false && (
                  <p className="mt-3 inline-flex items-center rounded-pill border border-amber-200 bg-amber-50/70 px-3 py-1 text-small font-semibold text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/10 dark:text-amber-400">
                    {t('soap:diagnosis.unverified', 'ICD-10 未驗證，請醫師確認')}
                  </p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                {report.icd10Codes.map((code) => (
                  <span
                    key={code}
                    className="rounded-pill border border-primary-200 bg-primary-50 px-3 py-1 font-data text-body font-medium text-primary-700 dark:border-primary-800 dark:bg-primary-950 dark:text-primary-300"
                  >
                    {code}
                  </span>
                ))}
                </div>
              </>
            ) : (
              <p className="mt-3 text-body text-ink-muted">{t('soap:diagnosis.empty', '目前沒有 ICD-10 編碼。')}</p>
            )}
          </div>
          <SOAPCard section="assessment" content={report.assessment as Record<string, unknown> | undefined} />
          <SOAPCard section="plan" content={report.plan as Record<string, unknown> | undefined} />
          <SOAPCard section="subjective" content={report.subjective as Record<string, unknown> | undefined} />
          <SOAPCard section="objective" content={report.objective as Record<string, unknown> | undefined} />
        </div>
        <div className="space-y-4">
          {sessionId && report.status !== 'failed' ? (
            <div className={`lg:block ${activeTab === 'report' ? '' : 'hidden'}`}>
              <QuickOrdersCard sessionId={sessionId} report={report} />
            </div>
          ) : null}
          <div className={`lg:block ${activeTab === 'transcript' ? '' : 'hidden'}`}>
            <TranscriptPanel
              conversations={conversations}
              isLoading={isLoadingConversations}
              defaultExpanded
              collapsible={false}
              maxHeightClass="max-h-[70vh]"
            />
          </div>
        </div>
      </div>

      {/* §5d 安全：只有 status==='generated'（非 generating/failed）才可核准/退回，
          與 PDF 匯出的 gate 一致，避免核准佔位/失敗的報告。 */}
      {!isReviewed && report.status === 'generated' ? (
        <div className="sticky bottom-4 z-20">
          <div className="rounded-panel border border-edge bg-white/95 p-4 shadow-lg backdrop-blur dark:border-dark-border dark:bg-dark-card/95">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-small font-semibold uppercase tracking-[0.16em] text-ink-muted">{t('soap:review.actionEyebrow', '審閱動作')}</p>
                <p className="mt-1 text-body text-ink-body dark:text-white/85">
                  {t('soap:review.instructions', '請先確認摘要、評估與計畫能回到逐字稿找到依據，再決定核准或退回修改。')}
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  className="btn-primary bg-alert-success hover:bg-green-700"
                  onClick={() => {
                    setReviewAction('approved');
                    setReviewError('');
                    setShowReviewModal(true);
                  }}
                >
                  <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {t('soap:review.approveButton', '確認報告')}
                </button>
                <button
                  className="btn-primary bg-alert-high hover:bg-orange-700"
                  onClick={() => {
                    setReviewAction('revision_needed');
                    setReviewError('');
                    setShowReviewModal(true);
                  }}
                >
                  <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                  </svg>
                  {t('soap:review.rejectButton', '退回修改')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <Modal
        visible={showReviewModal}
        onClose={() => {
          setShowReviewModal(false);
          setReviewError('');
        }}
        title={reviewAction === 'approved' ? t('soap:review.approveButton', '確認報告') : t('soap:review.rejectButton', '退回修改')}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setShowReviewModal(false)}>
              {t('soap:common.cancel', '取消')}
            </button>
            <button
              className={`btn-primary ${
                reviewAction === 'approved'
                  ? 'bg-alert-success hover:bg-green-700'
                  : 'bg-alert-high hover:bg-orange-700'
              }`}
              onClick={handleReview}
              disabled={isSubmitting || (reviewAction === 'revision_needed' && !reviewNotes.trim())}
            >
              {isSubmitting ? t('soap:common.processing', '處理中...') : t('soap:common.confirm', '確認')}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-body text-ink-body">
            {reviewAction === 'approved'
              ? t('soap:review.approveDescription', '確認此 SOAP 報告可作為正式臨床摘要？如有補充可留下備註。')
              : t('soap:review.rejectDescription', '請填寫需要修改的原因，這會作為退回修正的依據。')}
          </p>
          <textarea
            value={reviewNotes}
            onChange={(event) => setReviewNotes(event.target.value)}
            placeholder={
              reviewAction === 'approved'
                ? t('soap:review.approveNotesPlaceholder', '輸入審閱備註（選填）...')
                : t('soap:review.rejectNotesPlaceholder', '請輸入退回修改原因...')
            }
            className="input-base min-h-[120px] resize-y"
            rows={5}
          />
          {reviewError ? (
            <p className="text-small font-medium text-red-600 dark:text-red-400">{reviewError}</p>
          ) : null}
        </div>
      </Modal>

    </div>
  );
}
