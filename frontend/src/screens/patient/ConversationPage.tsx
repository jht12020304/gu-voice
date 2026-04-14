// =============================================================================
// 語音問診對話頁（病患端核心頁面）
// =============================================================================

import { useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ChatBubble from '../../components/chat/ChatBubble';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import StatusBadge from '../../components/medical/StatusBadge';
import { useConversationStore, conversationToMessage } from '../../stores/conversationStore';
import { useConversationWebSocket } from '../../hooks/useWebSocket';
import { useAudioStream } from '../../hooks/useAudioStream';
import * as sessionsApi from '../../services/api/sessions';
import { formatDuration } from '../../utils/format';
import type { SessionStatus } from '../../types/enums';
import type { Session } from '../../types';
import type {
  STTPartialPayload,
  STTFinalPayload,
  AIResponseStartPayload,
  AIResponseChunkPayload,
  AIResponseEndPayload,
  RedFlagAlertPayload,
  SessionStatusPayload,
} from '../../types/websocket';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockConvSession: Session = {
  id: 's1', patientId: 'p1', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc1',
  chiefComplaintText: '血尿持續三天', status: 'in_progress', redFlag: true,
  redFlagReason: '肉眼血尿持續超過 48 小時', language: 'zh-TW',
  startedAt: '2026-04-10T13:30:00Z', durationSeconds: 300,
  createdAt: '2026-04-10T13:30:00Z', updatedAt: '2026-04-10T13:35:00Z',
};

const mockConvMessages: Array<{ id: string; sessionId: string; sender: 'patient' | 'assistant' | 'system'; content: string; timestamp: string }> = [
  { id: 'cm1', sessionId: 's1', sender: 'system', content: '問診開始 — 主訴: 血尿持續三天', timestamp: '2026-04-10T13:30:00Z' },
  { id: 'cm2', sessionId: 's1', sender: 'assistant', content: '您好，我是泌尿科 AI 問診助手。請問您的血尿是什麼時候開始的？', timestamp: '2026-04-10T13:30:15Z' },
  { id: 'cm3', sessionId: 's1', sender: 'patient', content: '大概三天前，小便結束時有紅色，後來整泡尿都是紅色的。', timestamp: '2026-04-10T13:31:00Z' },
  { id: 'cm4', sessionId: 's1', sender: 'assistant', content: '排尿時是否有疼痛或灼熱感？有沒有頻尿、急尿或腰痛？', timestamp: '2026-04-10T13:31:15Z' },
  { id: 'cm5', sessionId: 's1', sender: 'patient', content: '有一點痛，尾端會刺刺的。比較頻尿，一小時跑一次廁所。', timestamp: '2026-04-10T13:32:00Z' },
];

export default function ConversationPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const activeSourceRef = useRef<AudioBufferSourceNode | null>(null);

  const {
    currentSession,
    conversations,
    isRecording,
    isAIResponding,
    sttPartialText,
    aiStreamingText,
    recordingDuration,
    waveformData,
    activeRedFlags,
    error,
    setCurrentSession,
    addConversation,
    setConversations,
    updateSTTPartial,
    setAIResponding,
    appendAIStreamingText,
    finalizeAIResponse,
    addRedFlag,
    setError,
    resetSession,
  } = useConversationStore();

  const { on, off, send } = useConversationWebSocket(sessionId ?? null);

  // 根據 session 狀態自動啟動 VAD（in_progress / waiting 時才開麥克風）
  const isSessionActiveForMic =
    currentSession?.status === 'in_progress' || currentSession?.status === 'waiting';
  const { muteVAD, unmuteVAD } = useAudioStream(isSessionActiveForMic);

  // TTS 播放（用 AudioContext + atob 直接解碼 base64，避開 CSP connect-src 對 data: URL 的限制）
  // 播放期間 VAD 保持靜音，播完後恢復 VAD 讓使用者直接說下一句
  const playTTSAudio = useCallback(
    async (dataUrl: string): Promise<void> => {
      if (!dataUrl) {
        unmuteVAD();
        return;
      }
      try {
        // 從 data URL 取出純 base64 字串
        const commaIdx = dataUrl.indexOf(',');
        const base64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;

        // base64 → Uint8Array → ArrayBuffer（不透過 fetch，不觸發 CSP）
        const binaryStr = atob(base64);
        const len = binaryStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = binaryStr.charCodeAt(i);

        if (!audioCtxRef.current) {
          audioCtxRef.current = new (window.AudioContext ??
            (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
        }
        const ctx = audioCtxRef.current;
        if (ctx.state === 'suspended') {
          await ctx.resume();
        }

        const audioBuf = await ctx.decodeAudioData(bytes.buffer);
        // 若前一段 TTS 尚未播完，先停掉避免重疊
        if (activeSourceRef.current) {
          try { activeSourceRef.current.stop(); } catch { /* ignore */ }
          activeSourceRef.current = null;
        }
        const source = ctx.createBufferSource();
        source.buffer = audioBuf;
        source.connect(ctx.destination);
        source.onended = () => {
          activeSourceRef.current = null;
          // TTS 播完 → 恢復 VAD，使用者可以直接說下一句
          unmuteVAD();
        };
        activeSourceRef.current = source;
        source.start(0);
      } catch (err) {
        console.error('[TTS] 播放失敗:', err);
        // 出錯也要恢復 VAD，避免卡死
        unmuteVAD();
      }
    },
    [unmuteVAD],
  );

  // 載入場次資料與歷史對話
  useEffect(() => {
    if (!sessionId) return;

    if (IS_MOCK) {
      setCurrentSession(mockConvSession);
      setConversations(mockConvMessages);
      return () => { resetSession(); };
    }

    async function load() {
      try {
        const [session, convs] = await Promise.all([
          sessionsApi.getSession(sessionId!),
          sessionsApi.getSessionConversations(sessionId!, { limit: 100 }),
        ]);
        setCurrentSession(session);
        // 只在 WS 尚未開始串流訊息時才從 API 載入歷史記錄
        // 若已有訊息（WS 開場語正在串流），則不覆蓋
        if (useConversationStore.getState().conversations.length === 0) {
          setConversations(convs.data.map(conversationToMessage));
        }
      } catch {
        setError('無法載入對話');
      }
    }
    load();

    return () => {
      resetSession();
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // WebSocket 事件處理
  useEffect(() => {
    // STT 中間結果
    on('stt_partial', (payload) => {
      const data = payload as STTPartialPayload;
      updateSTTPartial(data.text);
    });

    // STT 最終結果
    on('stt_final', (payload) => {
      const data = payload as STTFinalPayload;
      updateSTTPartial('');
      addConversation({
        id: data.messageId,
        sessionId: sessionId!,
        sender: 'patient',
        content: data.text,
        timestamp: new Date().toISOString(),
        sttConfidence: data.confidence,
      });
    });

    // AI 回應開始
    on('ai_response_start', (payload) => {
      const data = payload as AIResponseStartPayload;
      setAIResponding(true);
      // AI 準備說話，關掉 VAD 以免把 TTS 聲音當成使用者輸入
      muteVAD();
      addConversation({
        id: data.messageId,
        sessionId: sessionId!,
        sender: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        isStreaming: true,
      });
    });

    // AI 回應串流片段
    on('ai_response_chunk', (payload) => {
      const data = payload as AIResponseChunkPayload;
      appendAIStreamingText(data.text);
      useConversationStore.setState((state) => ({
        conversations: state.conversations.map((msg) =>
          msg.id === data.messageId
            ? { ...msg, content: msg.content + data.text }
            : msg,
        ),
      }));
    });

    // AI 回應結束
    on('ai_response_end', (payload) => {
      const data = payload as AIResponseEndPayload;
      finalizeAIResponse(data.messageId, data.fullText);
      if (data.ttsAudioUrl) {
        // 播放後會在 onended 恢復 VAD
        playTTSAudio(data.ttsAudioUrl);
      } else {
        // 沒有 TTS 音訊，直接恢復 VAD 讓使用者能回答
        unmuteVAD();
      }
    });

    // 紅旗警示
    on('red_flag_alert', (payload) => {
      const data = payload as RedFlagAlertPayload;
      addRedFlag({
        id: data.alertId,
        title: data.title,
        description: data.description,
        severity: data.severity,
        timestamp: new Date().toISOString(),
        suggestedActions: data.suggestedActions,
        isAcknowledged: false,
      });
    });

    // WebSocket 連線確認 → 更新場次狀態為進行中
    on('connection_ack', () => {
      if (currentSession && currentSession.status === 'waiting') {
        setCurrentSession({ ...currentSession, status: 'in_progress' as SessionStatus });
      }
    });

    // 場次狀態變更
    on('session_status', (payload) => {
      const data = payload as SessionStatusPayload;
      if (currentSession) {
        setCurrentSession({ ...currentSession, status: data.status as SessionStatus });
      }
      if (data.status === 'completed') {
        navigate(`/patient/session/${sessionId}/complete`);
      } else if (data.status === 'failed') {
        setError('問診中斷，請重新開始');
      }
    });

    // 後端錯誤（STT_ERROR / AI_SERVICE_UNAVAILABLE / INVALID_AUDIO / ...）
    on('error', (payload) => {
      const data = payload as { code?: string; message?: string };
      setError(data.message || 'AI 服務暫時無法回應，請稍後再試');
      // 也解除 VAD mute，避免使用者卡在「等 AI 回應」的狀態
      unmuteVAD();
    });

    // WebSocket 連線狀態
    on('_disconnected', () => {
      setError('連線中斷，正在重新連線...');
      muteVAD(); // 斷線期間暫停收音
    });
    on('_reconnecting', () => {
      setError('連線中斷，正在重新連線...');
    });
    on('_connected', () => {
      setError(null);
      unmuteVAD();
    });

    return () => {
      off('connection_ack');
      off('stt_partial');
      off('stt_final');
      off('ai_response_start');
      off('ai_response_chunk');
      off('ai_response_end');
      off('red_flag_alert');
      off('session_status');
      off('error');
      off('_disconnected');
      off('_reconnecting');
      off('_connected');
    };
  }, [sessionId, currentSession]); // eslint-disable-line react-hooks/exhaustive-deps

  // 自動捲動到底部
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [conversations, aiStreamingText, sttPartialText]);

  // 結束問診
  const handleEndSession = () => {
    send('control', { action: 'end_session' });
    navigate(`/patient/session/${sessionId}/complete`);
  };

  if (!currentSession && !error) {
    return <LoadingSpinner fullPage message="載入對話..." />;
  }

  const isSessionActive = isSessionActiveForMic;

  // 未確認的紅旗
  const unacknowledgedFlags = activeRedFlags.filter((f) => !f.isAcknowledged);

  return (
    <div className="flex h-screen flex-col bg-chat-bg dark:bg-dark-bg">
      {/* 頂部欄 */}
      <header className="flex items-center justify-between border-b border-edge bg-white px-4 py-3 dark:bg-dark-surface dark:border-dark-border">
        <button
          className="rounded-card p-2 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate(-1)}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="text-center">
          <h1 className="text-caption font-semibold text-ink-heading dark:text-white">AI 問診</h1>
          <div className="flex items-center justify-center gap-2">
            {currentSession && <StatusBadge status={currentSession.status as SessionStatus} size="sm" />}
          </div>
        </div>
        <button
          className="rounded-btn px-3 py-1.5 text-caption font-medium text-alert-critical hover:bg-alert-critical-bg transition-colors"
          onClick={handleEndSession}
        >
          結束問診
        </button>
      </header>

      {/* 紅旗警示橫幅 */}
      {unacknowledgedFlags.length > 0 && (
        <div className="border-b border-red-700 bg-alert-critical px-4 py-3 text-white animate-slide-down">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-body font-medium">{unacknowledgedFlags[0].title}</span>
          </div>
          {unacknowledgedFlags[0].description && (
            <p className="mt-1 text-small opacity-90">{unacknowledgedFlags[0].description}</p>
          )}
        </div>
      )}

      {/* 錯誤訊息 */}
      {error && (
        <div className="border-b border-alert-critical-border bg-alert-critical-bg px-4 py-2 text-body text-alert-critical-text">
          {error}
        </div>
      )}

      {/* 對話區域 */}
      <div ref={chatContainerRef} className="flex-1 overflow-y-auto px-4 py-4">
        {conversations.map((msg) => (
          <ChatBubble
            key={msg.id}
            message={{
              id: msg.id,
              content: msg.content,
              sender: msg.sender,
              timestamp: msg.timestamp,
              isStreaming: msg.isStreaming,
            }}
          />
        ))}

        {/* STT 即時文字 */}
        {sttPartialText && (
          <div className="my-2 flex justify-end">
            <div className="chat-bubble-patient opacity-70">
              <p className="text-body italic">{sttPartialText}</p>
            </div>
          </div>
        )}

        {/* AI 思考中 */}
        {isAIResponding && !aiStreamingText && (
          <div className="my-2 flex justify-start">
            <div className="chat-bubble-ai">
              <div className="thinking-dots text-ink-muted">
                <span /><span /><span />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 底部控制區（自動語音偵測） */}
      <div className="border-t border-edge bg-white px-4 py-5 dark:bg-dark-surface dark:border-dark-border">
        {/* 麥克風狀態指示圈（顯示狀態，無需點擊） */}
        <div className="flex items-center justify-center">
          <div
            className={`flex h-14 w-14 items-center justify-center rounded-full transition-colors ${
              !isSessionActive
                ? 'bg-surface-tertiary text-ink-placeholder'
                : isAIResponding
                  ? 'bg-primary-50 text-primary-500'
                  : isRecording
                    ? 'bg-alert-critical text-white shadow-lg shadow-alert-critical/30'
                    : 'bg-primary-50 text-primary-600'
            }`}
          >
            <svg
              className={`h-7 w-7 ${isRecording ? 'animate-pulse' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19 11a7 7 0 01-14 0m7 7v4m-4 0h8M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z"
              />
            </svg>
          </div>
        </div>

        {/* 波形視覺化（持續顯示；錄音時紅色強調） */}
        <div className="mt-3 flex items-end justify-center gap-1 h-10">
          {waveformData.slice(0, 32).map((value, i) => {
            const height = Math.max(3, value * 38);
            return (
              <div
                key={i}
                className={`w-1 rounded-full transition-all duration-75 ${
                  isRecording ? 'bg-alert-critical' : 'bg-primary-300 dark:bg-primary-700'
                }`}
                style={{ height: `${height}px` }}
              />
            );
          })}
        </div>

        {/* 狀態文字 */}
        <p className="mt-2 text-center text-small text-ink-muted">
          {!isSessionActive
            ? '問診尚未開始'
            : isAIResponding
              ? 'AI 回應中...'
              : isRecording
                ? `正在聆聽你說話 ${formatDuration(recordingDuration)}`
                : '請直接開始說話，我會自動聽取'}
        </p>
      </div>
    </div>
  );
}
