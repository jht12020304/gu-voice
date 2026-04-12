// =============================================================================
// SOAP 報告頁 — 含對話逐字稿、摘要、臨床推理、審閱操作
// 設計參考：Stripe (60%) + Intercom (25%) + Sentry (15%) 設計系統融合
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import SOAPCard from '../../components/medical/SOAPCard';
import TranscriptPanel from '../../components/medical/TranscriptPanel';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import { useReportStore } from '../../stores/reportStore';
import { formatDate } from '../../utils/format';

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

  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewAction, setReviewAction] = useState<'approved' | 'revision_needed'>('approved');
  const [reviewNotes, setReviewNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<'report' | 'transcript'>('report');

  useEffect(() => {
    if (sessionId) {
      fetchReportBySession(sessionId);
      fetchConversations(sessionId);
    }
  }, [sessionId, fetchReportBySession, fetchConversations]);

  const handleReview = async () => {
    if (!selectedReport) return;
    setIsSubmitting(true);
    try {
      await reviewReport(selectedReport.id, {
        reviewStatus: reviewAction,
        reviewNotes: reviewNotes || undefined,
      });
      setShowReviewModal(false);
      setReviewNotes('');
    } catch {
      // error handled by store
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message="載入報告..." />;
  if (error) return <ErrorState message={error} onRetry={() => sessionId && fetchReportBySession(sessionId)} />;
  if (!selectedReport) return <ErrorState message="報告尚未產生" />;

  const report = selectedReport;
  const isReviewed = report.reviewStatus !== 'pending';

  return (
    <div className="space-y-3 animate-fade-in">
      {/* ── 標題列 ── */}
      <div className="flex items-center gap-3">
        <button
          className="rounded-card p-1.5 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate(-1)}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-h2 text-ink-heading dark:text-white">AI 問診報告</h1>
          <p className="text-body text-ink-muted">
            {formatDate(report.generatedAt)}
            {report.aiConfidenceScore !== undefined &&
              ` · AI 信心 ${Math.round(report.aiConfidenceScore * 100)}%`}
          </p>
        </div>
        <div className="flex items-center gap-2">
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
        </div>
      </div>

      {/* ── 問診摘要 + ICD-10 合併 ── */}
      {report.summary && (
        <div className="card p-0 overflow-hidden">
          <div className="px-4 py-3">
            <p className="text-body-lg text-ink-body dark:text-white/85 leading-relaxed">{report.summary}</p>
            {report.icd10Codes && report.icd10Codes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {report.icd10Codes.map((code) => (
                  <span key={code} className="rounded-pill border border-primary-200 bg-primary-50 px-2.5 py-0.5 font-data text-body font-medium text-primary-700 dark:border-primary-800 dark:bg-primary-950 dark:text-primary-300">
                    {code}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab 切換 ── */}
      <div className="flex gap-1 rounded-card bg-surface-secondary p-1 dark:bg-dark-surface">
        <button
          className={`flex-1 rounded-card px-4 py-1.5 text-body font-medium transition-colors ${
            activeTab === 'report'
              ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
              : 'text-ink-muted hover:text-ink-secondary'
          }`}
          onClick={() => setActiveTab('report')}
        >
          <span className="flex items-center justify-center gap-2">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            SOAP 結構化報告
          </span>
        </button>
        <button
          className={`flex-1 rounded-card px-4 py-1.5 text-body font-medium transition-colors ${
            activeTab === 'transcript'
              ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
              : 'text-ink-muted hover:text-ink-secondary'
          }`}
          onClick={() => setActiveTab('transcript')}
        >
          <span className="flex items-center justify-center gap-2">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            對話逐字稿
            {conversations.length > 0 && (
              <span className="rounded-pill bg-primary-100 px-1.5 py-0.5 text-small font-semibold text-primary-700 dark:bg-primary-900 dark:text-primary-300">
                {conversations.length}
              </span>
            )}
          </span>
        </button>
      </div>

      {/* ── SOAP 結構化報告 — 2×2 四格 ── */}
      {activeTab === 'report' && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:items-start">
          <SOAPCard
            section="subjective"
            content={report.subjective as Record<string, unknown> | undefined}
          />
          <SOAPCard
            section="objective"
            content={report.objective as Record<string, unknown> | undefined}
          />
          <SOAPCard
            section="assessment"
            content={report.assessment as Record<string, unknown> | undefined}
          />
          <SOAPCard
            section="plan"
            content={report.plan as Record<string, unknown> | undefined}
          />
        </div>
      )}

      {/* ── 對話逐字稿 ── */}
      {activeTab === 'transcript' && (
        <TranscriptPanel
          conversations={conversations}
          isLoading={isLoadingConversations}
        />
      )}

      {/* ── 審閱按鈕 ── */}
      {!isReviewed && (
        <div className="flex gap-3">
          <button
            className="btn-primary bg-alert-success hover:bg-green-700"
            onClick={() => {
              setReviewAction('approved');
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
              setShowReviewModal(true);
            }}
          >
            <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
            </svg>
            退回修改
          </button>
        </div>
      )}

      {/* ── 審閱備註 ── */}
      {isReviewed && report.reviewNotes && (
        <div className="card bg-surface-secondary dark:bg-dark-surface">
          <h3 className="text-caption font-semibold text-ink-secondary">審閱備註</h3>
          <p className="mt-1 text-body text-ink-body">{report.reviewNotes}</p>
          <p className="mt-2 text-tiny text-ink-muted">
            審閱時間: {formatDate(report.reviewedAt)}
          </p>
        </div>
      )}

      {/* ── 審閱 Modal ── */}
      <Modal
        visible={showReviewModal}
        onClose={() => setShowReviewModal(false)}
        title={reviewAction === 'approved' ? '確認報告' : '退回修改'}
        footer={
          <>
            <button
              className="btn-secondary"
              onClick={() => setShowReviewModal(false)}
            >
              取消
            </button>
            <button
              className={`btn-primary ${
                reviewAction === 'approved'
                  ? 'bg-alert-success hover:bg-green-700'
                  : 'bg-alert-high hover:bg-orange-700'
              }`}
              onClick={handleReview}
              disabled={isSubmitting}
            >
              {isSubmitting ? '處理中...' : '確認'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-body text-ink-body">
            {reviewAction === 'approved'
              ? '確認此 SOAP 報告內容正確無誤？'
              : '請說明需要修改的原因：'}
          </p>
          <textarea
            value={reviewNotes}
            onChange={(e) => setReviewNotes(e.target.value)}
            placeholder="輸入備註（選填）..."
            className="input-base min-h-[100px] resize-y"
            rows={4}
          />
        </div>
      </Modal>
    </div>
  );
}
