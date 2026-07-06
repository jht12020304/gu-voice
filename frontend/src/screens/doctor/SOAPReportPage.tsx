// =============================================================================
// SOAP 報告頁 — 審閱工作台
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import toast from 'react-hot-toast';
import { useLocalizedNavigate } from '../../i18n/paths';
import TranscriptPanel from '../../components/medical/TranscriptPanel';
import SOAPCard from '../../components/medical/SOAPCard';
import StatusBadge from '../../components/medical/StatusBadge';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import { useReportStore } from '../../stores/reportStore';
import * as reportsApi from '../../services/api/reports';
import * as sessionsApi from '../../services/api/sessions';
import type { SOAPReport, Session } from '../../types';
import type { SessionStatus } from '../../types/enums';
import { formatDate, formatMRN } from '../../utils/format';

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

function uniqueStrings(items: Array<string | undefined | null>): string[] {
  return [...new Set(items.map((item) => (item ?? '').trim()).filter(Boolean))];
}

function getGenderLabel(
  gender: (Session['patient'] extends { gender: infer G } ? G : string) | undefined,
  t: TFunction,
): string {
  if (gender === 'male') return t('gender.male');
  if (gender === 'female') return t('gender.female');
  if (gender === 'other') return t('gender.other');
  return t('gender.unknown');
}

function extractNegativeFindings(report: SOAPReport): string[] {
  const review = report.subjective?.systemReview ?? {};
  const values = Object.values(review);
  return uniqueStrings(
    values.filter((value) => /^(無|否認|沒有|未見|none)/i.test(value.trim())),
  ).slice(0, 4);
}

function extractPositiveFindings(report: SOAPReport, t: TFunction): string[] {
  const subjective = report.subjective;
  const labs = report.objective?.labResults ?? [];

  return uniqueStrings([
    subjective?.chiefComplaint,
    subjective?.hpi.characteristics,
    ...(subjective?.hpi.associatedSymptoms ?? []),
    ...labs
      .filter((lab) => lab.isAbnormal)
      .map((lab) => t('soap:labels.testResult', { test: lab.testName, result: lab.result })),
  ]).slice(0, 5);
}

function extractRiskFactors(report: SOAPReport, session: Session | null, t: TFunction): string[] {
  const subjective = report.subjective;
  const social = subjective?.socialHistory ?? {};
  const conditions = subjective?.pastMedicalHistory?.conditions ?? [];

  return uniqueStrings([
    ...conditions,
    social.smoking ? t('soap:labels.smokingHistory', { value: social.smoking }) : null,
    social.alcohol ? t('soap:labels.alcoholUse', { value: social.alcohol }) : null,
    session?.redFlagReason ? t('soap:labels.redFlagReason', { value: session.redFlagReason }) : null,
  ]).slice(0, 5);
}

function extractImpression(report: SOAPReport, t: TFunction): string[] {
  const assessment = report.assessment;
  const plan = report.plan;

  return uniqueStrings([
    assessment?.clinicalImpression,
    ...(assessment?.differentialDiagnoses ?? []).slice(0, 2).map((item) => item.diagnosis),
    ...(plan?.recommendedTests ?? []).slice(0, 2).map((item) => t('soap:labels.recommendedTest', { value: item.testName })),
  ]).slice(0, 5);
}

function MetaCard({
  label,
  value,
  helper,
  tone = 'border-edge',
}: {
  label: string;
  value: React.ReactNode;
  helper?: React.ReactNode;
  tone?: string;
}) {
  return (
    <div className={`rounded-card border bg-white px-4 py-3 shadow-card dark:bg-dark-card dark:border-dark-border ${tone}`}>
      <p className="text-tiny font-semibold uppercase tracking-[0.16em] text-ink-muted">{label}</p>
      <div className="mt-2 text-body font-medium text-ink-heading dark:text-white">{value}</div>
      {helper ? <div className="mt-1 text-small text-ink-muted">{helper}</div> : null}
    </div>
  );
}

function HighlightList({
  title,
  items,
  emptyLabel,
}: {
  title: string;
  items: string[];
  emptyLabel: string;
}) {
  return (
    <div className="rounded-card border border-edge bg-white p-4 dark:border-dark-border dark:bg-dark-card">
      <h3 className="text-small font-semibold uppercase tracking-[0.16em] text-ink-muted">{title}</h3>
      {items.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li key={item} className="flex items-start gap-2 text-body text-ink-body dark:text-white/85">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-500" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-body text-ink-muted">{emptyLabel}</p>
      )}
    </div>
  );
}

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
    generateReport,
  } = useReportStore();

  const [session, setSession] = useState<Session | null>(IS_MOCK ? mockSession : null);
  // §1d 安全：session 抓取失敗時不可靜默把「有紅旗場次」渲染成「無紅旗」。
  const [sessionLoadFailed, setSessionLoadFailed] = useState(false);
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [showRegenerateModal, setShowRegenerateModal] = useState(false);
  const [reviewAction, setReviewAction] = useState<'approved' | 'revision_needed'>('approved');
  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [activeTab, setActiveTab] = useState<'report' | 'transcript'>('report');
  const report = selectedReport;
  const positiveFindings = useMemo(() => (report ? extractPositiveFindings(report, t) : []), [report, t]);
  const negativeFindings = useMemo(() => (report ? extractNegativeFindings(report) : []), [report]);
  const riskFactors = useMemo(() => (report ? extractRiskFactors(report, session, t) : []), [report, session, t]);
  const impressionItems = useMemo(() => (report ? extractImpression(report, t) : []), [report, t]);

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
    } catch {
      setReviewError(t('soap:review.submitError', '審閱送出失敗，請稍後再試。'));
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
    } catch {
      toast.error(t('soap:export.error', 'PDF 匯出失敗，請稍後再試'));
    } finally {
      setIsExporting(false);
    }
  };

  const handleRegenerate = async () => {
    if (!sessionId || isRegenerating) return;

    setIsRegenerating(true);
    try {
      await generateReport(sessionId);
      // generateReport 不會 throw，改以 store 內最新狀態判斷成敗
      if (useReportStore.getState().error) {
        toast.error(t('soap:regenerate.error', '報告重新產生失敗，請稍後再試'));
      } else {
        setShowRegenerateModal(false);
        toast.success(t('soap:regenerate.success', '報告已重新產生'));
      }
    } catch {
      toast.error(t('soap:regenerate.error', '報告重新產生失敗，請稍後再試'));
    } finally {
      setIsRegenerating(false);
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
  const sessionStatus = session?.status ? (
    <StatusBadge status={session.status as SessionStatus} size="sm" />
  ) : (
    <span className="text-small text-ink-muted">{t('status.unknown', '未取得場次狀態')}</span>
  );

  return (
    <div className={`animate-fade-in space-y-6 ${!isReviewed ? 'pb-28' : ''}`}>
      <section className="card">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex items-start gap-3">
            <button
              className="rounded-card p-2 text-ink-placeholder transition-colors hover:bg-surface-tertiary hover:text-ink-secondary"
              onClick={() => navigate(-1)}
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>

            <div>
              <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">{t('soap:page.reviewEyebrow', '報告審閱')}</p>
              <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">{t('soap:page.title', 'SOAP 報告')}</h1>
              <p className="mt-2 text-body text-ink-secondary">
                {patientName} · {complaint}
              </p>
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
                    {t('session:complete.aiConfidence', { percent: Math.round(report.aiConfidenceScore * 100) })}
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
            <button
              type="button"
              className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => setShowRegenerateModal(true)}
              disabled={isRegenerating}
            >
              {isRegenerating ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span className="ml-2">{t('soap:regenerate.loading', '重新產生中...')}</span>
                </>
              ) : (
                <>
                  <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                  </svg>
                  {t('soap:regenerate.button', '重新產生')}
                </>
              )}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => sessionId && navigate(`/sessions/${sessionId}`)}
            >
              {t('soap:actions.viewSession', '查看場次')}
            </button>
            {session?.patientId ? (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => navigate(`/patients/${session.patientId}`)}
              >
                {t('soap:actions.viewPatient', '病患資料')}
              </button>
            ) : null}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetaCard
            label={t('soap:metaCard.patient', '病患')}
            value={patientName}
            helper={[
              session?.patient?.medicalRecordNumber ? formatMRN(session.patient.medicalRecordNumber) : null,
              session?.patient ? `${getGenderLabel(session.patient.gender, t)} · ${formatDate(session.patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })}` : null,
            ].filter(Boolean).join(' · ')}
          />
          <MetaCard
            label={t('soap:metaCard.complaint', '主訴')}
            value={complaint}
            helper={session?.createdAt ? t('soap:metaCard.createdHelper', { date: formatDate(session.createdAt) }) : undefined}
          />
          <MetaCard
            label={t('soap:metaCard.sessionStatus', '場次狀態')}
            value={sessionStatus}
            helper={
              session?.completedAt
                ? t('soap:metaCard.completedAt', { date: formatDate(session.completedAt) })
                : session?.startedAt
                  ? t('soap:metaCard.startedAt', { date: formatDate(session.startedAt) })
                  : t('soap:metaCard.noTimeInfo', '尚未取得時間資訊')
            }
          />
          <MetaCard
            label={t('soap:metaCard.report', '報告')}
            value={report.generatedAt ? formatDate(report.generatedAt) : t('soap:metaCard.notGeneratedTime', '尚未產生時間')}
            helper={
              isReviewed
                ? t('soap:metaCard.reviewStatusHelper', {
                    status:
                      report.reviewStatus === 'approved'
                        ? t('soap:reviewStatus.approved', '已核准')
                        : t('soap:reviewStatus.revisionNeeded', '需修改'),
                  })
                : t('soap:metaCard.awaitingReview', '等待醫師審閱')
            }
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.8fr)]">
        <div className="space-y-4">
          <div className="rounded-panel border border-primary-100 bg-primary-50/70 p-5 dark:border-primary-900/50 dark:bg-primary-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-primary-700 dark:text-primary-300">{t('soap:page.clinicalSummaryEyebrow', '臨床摘要')}</p>
            <p className="mt-3 text-body-lg leading-relaxed text-ink-body dark:text-white/85">
              {report.summary || report.assessment?.clinicalImpression || t('soap:page.noSummary', '目前尚無可顯示的摘要。')}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <HighlightList title={t('soap:highlights.positive.title', '重要陽性')} items={positiveFindings} emptyLabel={t('soap:highlights.positive.empty', '目前沒有整理出明確的陽性症狀。')} />
            <HighlightList title={t('soap:highlights.negative.title', '重要陰性')} items={negativeFindings} emptyLabel={t('soap:highlights.negative.empty', '目前沒有整理出明確的陰性症狀。')} />
            <HighlightList title={t('soap:highlights.riskFactors.title', '風險因子')} items={riskFactors} emptyLabel={t('soap:highlights.riskFactors.empty', '目前沒有明顯風險因子。')} />
            <HighlightList title={t('soap:highlights.impression.title', '初步判斷')} items={impressionItems} emptyLabel={t('soap:highlights.impression.empty', '目前沒有整理出明確判斷。')} />
          </div>
        </div>

        <aside className="space-y-4">
          <div className="card">
            <h2 className="text-h3 text-ink-heading dark:text-white">{t('soap:diagnosis.title', '診斷索引')}</h2>
            {report.icd10Codes && report.icd10Codes.length > 0 ? (
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
            ) : (
              <p className="mt-3 text-body text-ink-muted">{t('soap:diagnosis.empty', '目前沒有 ICD-10 編碼。')}</p>
            )}
          </div>

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
        </aside>
      </section>

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

      <div className="hidden lg:grid lg:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.9fr)] lg:items-start lg:gap-6">
        <div className="space-y-4">
          <SOAPCard section="assessment" content={report.assessment as Record<string, unknown> | undefined} />
          <SOAPCard section="plan" content={report.plan as Record<string, unknown> | undefined} />
          <SOAPCard section="subjective" content={report.subjective as Record<string, unknown> | undefined} />
          <SOAPCard section="objective" content={report.objective as Record<string, unknown> | undefined} />
        </div>
        <div className="sticky top-6">
          <TranscriptPanel
            conversations={conversations}
            isLoading={isLoadingConversations}
            defaultExpanded
            collapsible={false}
            maxHeightClass="max-h-[72vh]"
          />
        </div>
      </div>

      <div className="space-y-4 lg:hidden">
        {activeTab === 'report' ? (
          <>
            <SOAPCard section="assessment" content={report.assessment as Record<string, unknown> | undefined} />
            <SOAPCard section="plan" content={report.plan as Record<string, unknown> | undefined} />
            <SOAPCard section="subjective" content={report.subjective as Record<string, unknown> | undefined} />
            <SOAPCard section="objective" content={report.objective as Record<string, unknown> | undefined} />
          </>
        ) : (
          <TranscriptPanel conversations={conversations} isLoading={isLoadingConversations} defaultExpanded />
        )}
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

      <Modal
        visible={showRegenerateModal}
        onClose={() => {
          if (isRegenerating) return;
          setShowRegenerateModal(false);
        }}
        title={t('soap:regenerate.title', '重新產生報告')}
        footer={
          <>
            <button
              className="btn-secondary"
              onClick={() => setShowRegenerateModal(false)}
              disabled={isRegenerating}
            >
              {t('soap:regenerate.cancel', '取消')}
            </button>
            <button
              className="btn-primary bg-alert-high hover:bg-orange-700"
              onClick={handleRegenerate}
              disabled={isRegenerating}
            >
              {isRegenerating ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span className="ml-2">{t('soap:regenerate.loading', '重新產生中...')}</span>
                </>
              ) : (
                t('soap:regenerate.confirm', '確認重新產生')
              )}
            </button>
          </>
        }
      >
        <p className="text-body text-ink-body">
          {t(
            'soap:regenerate.description',
            '重新產生會以最新逐字稿重新執行 AI 分析，並覆蓋現有 SOAP 報告內容，此動作無法復原。確定要繼續嗎？',
          )}
        </p>
      </Modal>
    </div>
  );
}
