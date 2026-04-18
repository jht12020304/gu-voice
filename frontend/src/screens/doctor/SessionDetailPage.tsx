// =============================================================================
// 場次詳情頁（含對話紀錄）
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useLocalizedNavigate } from '../../i18n/paths';
import ChatBubble from '../../components/chat/ChatBubble';
import StatusBadge from '../../components/medical/StatusBadge';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import * as sessionsApi from '../../services/api/sessions';
import type { Session, Conversation } from '../../types';
import type { SessionStatus } from '../../types/enums';
import { formatDate, formatDuration } from '../../utils/format';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockSession: Session = {
  id: 's1', patientId: 'p1', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc1',
  chiefComplaintText: '血尿持續三天', status: 'in_progress', redFlag: true,
  redFlagReason: '肉眼血尿持續超過 48 小時，需排除膀胱腫瘤', language: 'zh-TW',
  startedAt: '2026-04-10T13:30:00Z', durationSeconds: 1200,
  createdAt: '2026-04-10T13:30:00Z', updatedAt: '2026-04-10T13:50:00Z',
  patient: { id: 'p1', userId: 'u1', medicalRecordNumber: 'MRN-2026-0001', name: '陳小明', gender: 'male', dateOfBirth: '1985-03-15', createdAt: '2026-01-15T08:00:00Z', updatedAt: '2026-04-10T10:00:00Z' },
};

const mockConversations: Conversation[] = [
  { id: 'cv1', sessionId: 's1', sequenceNumber: 1, role: 'system', contentText: '問診開始，主訴: 血尿持續三天', redFlagDetected: false, createdAt: '2026-04-10T13:30:00Z' },
  { id: 'cv2', sessionId: 's1', sequenceNumber: 2, role: 'assistant', contentText: '您好，陳先生。我是泌尿科 AI 問診助手，將協助您進行初步問診。請問您的血尿是什麼時候開始的？', redFlagDetected: false, createdAt: '2026-04-10T13:30:15Z' },
  { id: 'cv3', sessionId: 's1', sequenceNumber: 3, role: 'patient', contentText: '大概三天前開始的，剛開始小便結束的時候有一點紅色，後來整泡尿都是紅色的。', redFlagDetected: false, createdAt: '2026-04-10T13:31:00Z', sttConfidence: 0.92 },
  { id: 'cv4', sessionId: 's1', sequenceNumber: 4, role: 'assistant', contentText: '了解。請問您排尿時是否有疼痛或灼熱感？有沒有伴隨其他症狀，例如頻尿、急尿或腰痛？', redFlagDetected: false, createdAt: '2026-04-10T13:31:15Z' },
  { id: 'cv5', sessionId: 's1', sequenceNumber: 5, role: 'patient', contentText: '有一點痛，就是小便的時候尾端會有點刺刺的。然後比較頻尿，大概一個小時就要跑一次廁所。腰倒是不太痛。', redFlagDetected: false, createdAt: '2026-04-10T13:32:00Z', sttConfidence: 0.89 },
  { id: 'cv6', sessionId: 's1', sequenceNumber: 6, role: 'assistant', contentText: '謝謝您的描述。有幾個重要的問題想再確認：\n1. 血尿中有沒有看到血塊？\n2. 有沒有發燒？\n3. 之前有沒有類似的情況？', redFlagDetected: false, createdAt: '2026-04-10T13:32:15Z' },
  { id: 'cv7', sessionId: 's1', sequenceNumber: 7, role: 'patient', contentText: '有血塊，昨天比較多。沒有發燒。以前沒有過這種情況，這是第一次。', redFlagDetected: true, createdAt: '2026-04-10T13:33:00Z', sttConfidence: 0.94 },
];

export default function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useLocalizedNavigate();

  const [session, setSession] = useState<Session | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) return;

    if (IS_MOCK) {
      setSession(mockSession);
      setConversations(mockConversations);
      setIsLoading(false);
      return;
    }

    async function load() {
      try {
        const [sessionData, convData] = await Promise.all([
          sessionsApi.getSession(sessionId!),
          sessionsApi.getSessionConversations(sessionId!, { limit: 100 }),
        ]);
        setSession(sessionData);
        setConversations(convData.data);
      } catch {
        setError('無法載入場次資料');
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [sessionId]);

  if (isLoading) return <LoadingSpinner fullPage message="載入場次..." />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!session) return <ErrorState message="場次不存在" />;

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
          <h1 className="text-h1 text-ink-heading dark:text-white">場次詳情</h1>
          <p className="text-small text-ink-muted font-data">ID: {session.id}</p>
        </div>
        <StatusBadge status={session.status as SessionStatus} />
      </div>

      {/* 基本資訊 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <InfoCard label="主訴" value={session.chiefComplaintText || '-'} />
        <InfoCard label="語言" value={session.language} />
        <InfoCard label="開始時間" value={formatDate(session.startedAt)} />
        <InfoCard label="持續時間" value={formatDuration(session.durationSeconds)} numeric />
      </div>

      {/* 紅旗標記 */}
      {session.redFlag && (
        <div className="alert-card alert-card-critical">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 text-alert-critical" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-body font-semibold text-alert-critical">紅旗警示</span>
          </div>
          {session.redFlagReason && (
            <p className="mt-1 text-body text-alert-critical-text">{session.redFlagReason}</p>
          )}
        </div>
      )}

      {/* 操作按鈕 */}
      <div className="flex gap-3">
        <button
          className="btn-primary"
          onClick={() => navigate(`/reports/${session.id}`)}
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          查看 SOAP 報告
        </button>
        <button
          className="btn-secondary"
          onClick={() => navigate(`/conversation/${session.id}`)}
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
          </svg>
          進入對話
        </button>
      </div>

      {/* 對話紀錄 */}
      <div className="card">
        <h2 className="mb-4 text-h3 text-ink-heading dark:text-white">對話紀錄</h2>
        <div className="max-h-[600px] space-y-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <p className="py-8 text-center text-body text-ink-muted">尚無對話紀錄</p>
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
