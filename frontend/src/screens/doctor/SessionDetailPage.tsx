// =============================================================================
// 場次詳情頁（含對話紀錄）
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { useLocalizedNavigate } from '../../i18n/paths';
import ChatBubble from '../../components/chat/ChatBubble';
import StatusBadge from '../../components/medical/StatusBadge';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import * as sessionsApi from '../../services/api/sessions';
import * as reportsApi from '../../services/api/reports';
import { useReportStore } from '../../stores/reportStore';
import { useAuthStore } from '../../stores/authStore';
import type { Session, Conversation } from '../../types';
import type { SessionStatus } from '../../types/enums';
import { formatDate, formatDuration } from '../../utils/format';

type StatusAction = 'completed' | 'cancelled';

export default function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('session');

  const currentUser = useAuthStore((s) => s.user);
  const generateReport = useReportStore((s) => s.generateReport);

  const [session, setSession] = useState<Session | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [hasReport, setHasReport] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  // 狀態變更（完成／取消）— 走確認 Modal
  const [statusModal, setStatusModal] = useState<StatusAction | null>(null);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);

  // 指派醫師（指派給自己）
  const [isAssigning, setIsAssigning] = useState(false);

  // 產生報告
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    const id = sessionId;

    async function load() {
      setIsLoading(true);
      setError('');
      try {
        const [sessionData, convData] = await Promise.all([
          sessionsApi.getSession(id),
          sessionsApi.getSessionConversations(id, { limit: 100 }),
        ]);
        setSession(sessionData);
        setConversations(convData.data);
        // 偵測是否已有報告（決定是否顯示「產生報告」）
        if (sessionData.status === 'completed') {
          try {
            await reportsApi.getReportBySession(id);
            setHasReport(true);
          } catch {
            setHasReport(false);
          }
        }
      } catch {
        setError(t('doctor.detail.loadError'));
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [sessionId, t]);

  const handleStatusChange = async (status: StatusAction) => {
    if (!session) return;
    setIsUpdatingStatus(true);
    try {
      const updated = await sessionsApi.updateSessionStatus(session.id, status);
      setSession(updated);
      setStatusModal(null);
      toast.success(
        status === 'completed'
          ? t('doctor.detail.statusCompletedSuccess', '場次已標記為完成')
          : t('doctor.detail.statusCancelledSuccess', '場次已取消'),
      );
    } catch {
      toast.error(t('doctor.detail.statusUpdateError', '更新場次狀態失敗，請稍後再試'));
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const handleAssignToMe = async () => {
    if (!session || !currentUser) return;
    setIsAssigning(true);
    try {
      const updated = await sessionsApi.assignDoctor(session.id, currentUser.id);
      setSession(updated);
      toast.success(t('doctor.detail.assignSuccess', '已將場次指派給您'));
    } catch {
      toast.error(t('doctor.detail.assignError', '指派醫師失敗，請稍後再試'));
    } finally {
      setIsAssigning(false);
    }
  };

  const handleGenerateReport = async () => {
    if (!session) return;
    setIsGenerating(true);
    try {
      await generateReport(session.id);
      const storeError = useReportStore.getState().error;
      if (storeError) {
        toast.error(t('doctor.detail.generateReportError', '報告生成失敗，請稍後再試'));
        return;
      }
      toast.success(t('doctor.detail.generateReportSuccess', '報告已生成'));
      setHasReport(true);
      navigate(`/reports/${session.id}`);
    } catch {
      toast.error(t('doctor.detail.generateReportError', '報告生成失敗，請稍後再試'));
    } finally {
      setIsGenerating(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message={t('doctor.detail.loading')} />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!session) return <ErrorState message={t('doctor.detail.notFound')} />;

  const isAssignedToMe = !!currentUser && session.doctorId === currentUser.id;
  const canComplete = session.status === 'waiting' || session.status === 'in_progress';
  const canCancel = session.status === 'waiting' || session.status === 'in_progress';
  const canGenerateReport = session.status === 'completed' && !hasReport;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 標題列 */}
      <div className="flex items-center gap-4">
        <button
          className="rounded-card p-2 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate(-1)}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-h1 text-ink-heading dark:text-white">{t('doctor.detail.title')}</h1>
          <p className="text-small text-ink-muted font-data">{t('doctor.detail.idLabel', { id: session.id })}</p>
        </div>
        <StatusBadge status={session.status as SessionStatus} />
      </div>

      {/* 基本資訊 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <InfoCard label={t('doctor.detail.infoChiefComplaint')} value={session.chiefComplaintText || t('doctor.detail.infoChiefComplaintEmpty')} />
        <InfoCard label={t('doctor.detail.infoLanguage')} value={session.language} />
        <InfoCard label={t('doctor.detail.infoStartedAt')} value={session.startedAt ? formatDate(session.startedAt) : '-'} />
        <InfoCard label={t('doctor.detail.infoDuration')} value={formatDuration(session.durationSeconds)} numeric />
      </div>

      {/* 紅旗標記 */}
      {session.redFlag && (
        <div className="alert-card alert-card-critical">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 text-alert-critical" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-body font-semibold text-alert-critical">{t('doctor.detail.redFlagTitle')}</span>
          </div>
          {session.redFlagReason && (
            <p className="mt-1 text-body text-alert-critical-text">{session.redFlagReason}</p>
          )}
        </div>
      )}

      {/* 場次操作（醫師變更／指派／產生報告） */}
      <div className="card">
        <h2 className="mb-1 text-h3 text-ink-heading dark:text-white">
          {t('doctor.detail.actionsTitle', '場次操作')}
        </h2>
        <p className="mb-4 text-small text-ink-muted">
          {isAssignedToMe
            ? t('doctor.detail.assignedToMe', '此場次已指派給您')
            : t('doctor.detail.actionsHint', '可指派場次給自己、變更狀態或產生報告')}
        </p>
        <div className="flex flex-wrap gap-3">
          {/* 指派給自己 */}
          {!isAssignedToMe && (
            <button
              className="btn-secondary"
              onClick={handleAssignToMe}
              disabled={isAssigning || !currentUser}
            >
              {isAssigning ? (
                <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                </svg>
              )}
              {isAssigning ? t('doctor.detail.assigning', '指派中...') : t('doctor.detail.assignToMe', '指派給我')}
            </button>
          )}

          {/* 標記完成 */}
          {canComplete && (
            <button
              className="btn-primary bg-alert-success hover:bg-green-700"
              onClick={() => setStatusModal('completed')}
              disabled={isUpdatingStatus}
            >
              <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {t('doctor.detail.markCompleted', '標記完成')}
            </button>
          )}

          {/* 取消場次 */}
          {canCancel && (
            <button
              className="btn-secondary text-alert-critical hover:bg-red-50 dark:hover:bg-red-950/30"
              onClick={() => setStatusModal('cancelled')}
              disabled={isUpdatingStatus}
            >
              <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {t('doctor.detail.cancelSession', '取消場次')}
            </button>
          )}

          {/* 產生報告（完成且尚無報告時） */}
          {canGenerateReport && (
            <button
              className="btn-primary"
              onClick={handleGenerateReport}
              disabled={isGenerating}
            >
              {isGenerating ? (
                <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              )}
              {isGenerating ? t('doctor.detail.generatingReport', '生成報告中...') : t('doctor.detail.generateReport', '產生報告')}
            </button>
          )}
        </div>
      </div>

      {/* 導覽按鈕 */}
      <div className="flex gap-3">
        <button
          className="btn-primary"
          onClick={() => navigate(`/reports/${session.id}`)}
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          {t('doctor.detail.viewReport')}
        </button>
        <button
          className="btn-secondary"
          onClick={() => navigate(`/conversation/${session.id}`)}
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
          </svg>
          {t('doctor.detail.enterConversation')}
        </button>
      </div>

      {/* 對話紀錄 */}
      <div className="card">
        <h2 className="mb-4 text-h3 text-ink-heading dark:text-white">{t('doctor.detail.conversationsTitle')}</h2>
        <div className="max-h-[600px] space-y-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <p className="py-8 text-center text-body text-ink-muted">{t('doctor.detail.conversationsEmpty')}</p>
          ) : (
            conversations
              .sort((a, b) => a.sequenceNumber - b.sequenceNumber)
              .map((conv) => (
                <ChatBubble
                  key={conv.id}
                  message={{
                    id: conv.id,
                    content: conv.contentText,
                    sender: conv.role,
                    timestamp: conv.createdAt,
                    isStreaming: false,
                  }}
                />
              ))
          )}
        </div>
      </div>

      {/* 狀態變更確認 Modal */}
      <Modal
        visible={statusModal !== null}
        onClose={() => {
          if (!isUpdatingStatus) setStatusModal(null);
        }}
        title={
          statusModal === 'completed'
            ? t('doctor.detail.markCompletedTitle', '標記場次完成')
            : t('doctor.detail.cancelSessionTitle', '取消場次')
        }
        closable={!isUpdatingStatus}
        footer={
          <>
            <button
              className="btn-secondary"
              onClick={() => setStatusModal(null)}
              disabled={isUpdatingStatus}
            >
              {t('doctor.detail.cancelAction', '取消')}
            </button>
            <button
              className={`btn-primary ${statusModal === 'cancelled' ? 'bg-alert-critical hover:bg-red-700' : ''}`}
              onClick={() => statusModal && handleStatusChange(statusModal)}
              disabled={isUpdatingStatus}
            >
              {isUpdatingStatus && (
                <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {isUpdatingStatus
                ? t('doctor.detail.processing', '處理中...')
                : t('doctor.detail.confirm', '確認')}
            </button>
          </>
        }
      >
        <p className="text-body text-ink-body dark:text-white/85">
          {statusModal === 'completed'
            ? t('doctor.detail.markCompletedConfirm', '確認將此場次標記為完成？完成後可產生 SOAP 報告。')
            : t('doctor.detail.cancelSessionConfirm', '確認取消此場次？此操作無法復原。')}
        </p>
      </Modal>
    </div>
  );
}

function InfoCard({ label, value, numeric }: { label: string; value: string; numeric?: boolean }) {
  return (
    <div className="card">
      <p className="text-tiny font-semibold uppercase tracking-wider text-ink-muted">{label}</p>
      <p className={`mt-1 text-body font-medium text-ink-heading dark:text-white ${numeric ? 'font-tnum' : ''}`}>{value}</p>
    </div>
  );
}
