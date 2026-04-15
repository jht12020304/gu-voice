// =============================================================================
// SOAP 報告頁 — 審閱工作台
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import TranscriptPanel from '../../components/medical/TranscriptPanel';
import SOAPCard from '../../components/medical/SOAPCard';
import StatusBadge from '../../components/medical/StatusBadge';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import { useReportStore } from '../../stores/reportStore';
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

function getGenderLabel(gender?: Session['patient'] extends { gender: infer T } ? T : string): string {
  if (gender === 'male') return '男';
  if (gender === 'female') return '女';
  if (gender === 'other') return '其他';
  return '未提供';
}

function extractNegativeFindings(report: SOAPReport): string[] {
  const review = report.subjective?.systemReview ?? {};
  const values = Object.values(review);
  return uniqueStrings(
    values.filter((value) => /^(無|否認|沒有|未見|none)/i.test(value.trim())),
  ).slice(0, 4);
}

function extractPositiveFindings(report: SOAPReport): string[] {
  const subjective = report.subjective;
  const labs = report.objective?.labResults ?? [];

  return uniqueStrings([
    subjective?.chiefComplaint,
    subjective?.hpi.characteristics,
    ...(subjective?.hpi.associatedSymptoms ?? []),
    ...labs
      .filter((lab) => lab.isAbnormal)
      .map((lab) => `${lab.testName}：${lab.result}`),
  ]).slice(0, 5);
}

function extractRiskFactors(report: SOAPReport, session: Session | null): string[] {
  const subjective = report.subjective;
  const social = subjective?.socialHistory ?? {};
  const conditions = subjective?.pastMedicalHistory?.conditions ?? [];

  return uniqueStrings([
    ...conditions,
    social.smoking ? `吸菸史：${social.smoking}` : null,
    social.alcohol ? `飲酒：${social.alcohol}` : null,
    session?.redFlagReason ? `紅旗原因：${session.redFlagReason}` : null,
  ]).slice(0, 5);
}

function extractImpression(report: SOAPReport): string[] {
  const assessment = report.assessment;
  const plan = report.plan;

  return uniqueStrings([
    assessment?.clinicalImpression,
    ...(assessment?.differentialDiagnoses ?? []).slice(0, 2).map((item) => item.diagnosis),
    ...(plan?.recommendedTests ?? []).slice(0, 2).map((item) => `建議：${item.testName}`),
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
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const {
    selectedReport,
    conversations,
    isLoading,
    isLoadingConversations,
    error,
    fetchReportBySession,
    fetchConversations,
    reviewReport,
  } = useReportStore();

  const [session, setSession] = useState<Session | null>(IS_MOCK ? mockSession : null);
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewAction, setReviewAction] = useState<'approved' | 'revision_needed'>('approved');
  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<'report' | 'transcript'>('report');
  const report = selectedReport;
  const positiveFindings = useMemo(() => (report ? extractPositiveFindings(report) : []), [report]);
  const negativeFindings = useMemo(() => (report ? extractNegativeFindings(report) : []), [report]);
  const riskFactors = useMemo(() => (report ? extractRiskFactors(report, session) : []), [report, session]);
  const impressionItems = useMemo(() => (report ? extractImpression(report) : []), [report]);

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
      .then((data) => setSession(data))
      .catch(() => setSession(null));
  }, [sessionId, fetchReportBySession, fetchConversations]);

  const handleReview = async () => {
    if (!selectedReport) return;

    if (reviewAction === 'revision_needed' && !reviewNotes.trim()) {
      setReviewError('退回修改時必須填寫原因。');
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
      setReviewError('審閱送出失敗，請稍後再試。');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message="載入報告..." />;
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
  if (!report) return <ErrorState message="報告尚未產生" />;

  const isReviewed = report.reviewStatus !== 'pending';
  const patientName = session?.patientName ?? session?.patient?.name ?? '未知病患';
  const complaint =
    session?.chiefComplaintText ||
    session?.chiefComplaint?.name ||
    report.subjective?.chiefComplaint ||
    '未填寫主訴';
  const sessionStatus = session?.status ? (
    <StatusBadge status={session.status as SessionStatus} size="sm" />
  ) : (
    <span className="text-small text-ink-muted">未取得場次狀態</span>
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
              <p className="text-small font-semibold uppercase tracking-[0.18em] text-ink-muted">Report Review</p>
              <h1 className="mt-2 text-h1 text-ink-heading dark:text-white">SOAP 報告</h1>
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
                  {report.status === 'generated' ? '已產生' : report.status === 'generating' ? '產生中' : '失敗'}
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
                    ? '已核准'
                    : report.reviewStatus === 'revision_needed'
                      ? '需修改'
                      : '待審閱'}
                </span>
                {report.aiConfidenceScore !== undefined ? (
                  <span className="rounded-pill bg-primary-50 px-3 py-1 text-small font-semibold text-primary-700 dark:bg-primary-950/40 dark:text-primary-300">
                    AI 信心 {Math.round(report.aiConfidenceScore * 100)}%
                  </span>
                ) : null}
                {session?.redFlag ? (
                  <span className="rounded-pill bg-red-50 px-3 py-1 text-small font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
                    紅旗場次
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => sessionId && navigate(`/sessions/${sessionId}`)}
            >
              查看場次
            </button>
            {session?.patientId ? (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => navigate(`/patients/${session.patientId}`)}
              >
                病患資料
              </button>
            ) : null}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetaCard
            label="病患"
            value={patientName}
            helper={[
              session?.patient?.medicalRecordNumber ? formatMRN(session.patient.medicalRecordNumber) : null,
              session?.patient ? `${getGenderLabel(session.patient.gender)} · ${formatDate(session.patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })}` : null,
            ].filter(Boolean).join(' · ')}
          />
          <MetaCard
            label="主訴"
            value={complaint}
            helper={session?.createdAt ? `場次建立 ${formatDate(session.createdAt)}` : undefined}
          />
          <MetaCard
            label="場次狀態"
            value={sessionStatus}
            helper={
              session?.completedAt
                ? `完成於 ${formatDate(session.completedAt)}`
                : session?.startedAt
                  ? `開始於 ${formatDate(session.startedAt)}`
                  : '尚未取得時間資訊'
            }
          />
          <MetaCard
            label="報告"
            value={report.generatedAt ? formatDate(report.generatedAt) : '尚未產生時間'}
            helper={isReviewed ? `審閱狀態：${report.reviewStatus === 'approved' ? '已核准' : '需修改'}` : '等待醫師審閱'}
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.8fr)]">
        <div className="space-y-4">
          <div className="rounded-panel border border-primary-100 bg-primary-50/70 p-5 dark:border-primary-900/50 dark:bg-primary-950/20">
            <p className="text-small font-semibold uppercase tracking-[0.16em] text-primary-700 dark:text-primary-300">Clinical Summary</p>
            <p className="mt-3 text-body-lg leading-relaxed text-ink-body dark:text-white/85">
              {report.summary || report.assessment?.clinicalImpression || '目前尚無可顯示的摘要。'}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <HighlightList title="重要陽性" items={positiveFindings} emptyLabel="目前沒有整理出明確的陽性症狀。" />
            <HighlightList title="重要陰性" items={negativeFindings} emptyLabel="目前沒有整理出明確的陰性症狀。" />
            <HighlightList title="風險因子" items={riskFactors} emptyLabel="目前沒有明顯風險因子。" />
            <HighlightList title="初步判斷" items={impressionItems} emptyLabel="目前沒有整理出明確判斷。" />
          </div>
        </div>

        <aside className="space-y-4">
          <div className="card">
            <h2 className="text-h3 text-ink-heading dark:text-white">診斷索引</h2>
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
              <p className="mt-3 text-body text-ink-muted">目前沒有 ICD-10 編碼。</p>
            )}
          </div>

          {session?.redFlag ? (
            <div className="card border-red-200 bg-red-50/70 dark:border-red-900/50 dark:bg-red-950/10">
              <h2 className="text-h3 text-red-700 dark:text-red-400">紅旗註記</h2>
              <p className="mt-3 text-body leading-relaxed text-red-700/90 dark:text-red-300/85">
                {session.redFlagReason || '此場次曾觸發紅旗警示，建議審閱時特別核對摘要與逐字稿。'}
              </p>
            </div>
          ) : null}

          {isReviewed && report.reviewNotes ? (
            <div className="card">
              <h2 className="text-h3 text-ink-heading dark:text-white">審閱備註</h2>
              <p className="mt-3 text-body leading-relaxed text-ink-body dark:text-white/85">{report.reviewNotes}</p>
              {report.reviewedAt ? (
                <p className="mt-3 text-small text-ink-muted">審閱時間：{formatDate(report.reviewedAt)}</p>
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
            SOAP 結構化報告
          </button>
          <button
            className={`flex-1 rounded-card px-4 py-2 text-body font-medium transition-colors ${
              activeTab === 'transcript'
                ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
                : 'text-ink-muted hover:text-ink-secondary'
            }`}
            onClick={() => setActiveTab('transcript')}
          >
            對話逐字稿
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

      {!isReviewed ? (
        <div className="sticky bottom-4 z-20">
          <div className="rounded-panel border border-edge bg-white/95 p-4 shadow-lg backdrop-blur dark:border-dark-border dark:bg-dark-card/95">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-small font-semibold uppercase tracking-[0.16em] text-ink-muted">Review Action</p>
                <p className="mt-1 text-body text-ink-body dark:text-white/85">
                  請先確認摘要、評估與計畫能回到逐字稿找到依據，再決定核准或退回修改。
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
                  確認報告
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
                  退回修改
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
        title={reviewAction === 'approved' ? '確認報告' : '退回修改'}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setShowReviewModal(false)}>
              取消
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
              {isSubmitting ? '處理中...' : '確認'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-body text-ink-body">
            {reviewAction === 'approved'
              ? '確認此 SOAP 報告可作為正式臨床摘要？如有補充可留下備註。'
              : '請填寫需要修改的原因，這會作為退回修正的依據。'}
          </p>
          <textarea
            value={reviewNotes}
            onChange={(event) => setReviewNotes(event.target.value)}
            placeholder={reviewAction === 'approved' ? '輸入審閱備註（選填）...' : '請輸入退回修改原因...'}
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
