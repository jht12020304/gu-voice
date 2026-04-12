// =============================================================================
// 語音問診對話頁（病患端核心頁面）
// =============================================================================

import { useEffect, useRef, useCallback, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ChatBubble from '../../components/chat/ChatBubble';
import MicButton from '../../components/audio/MicButton';
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
  const { startRecording, stopRecording } = useAudioStream();

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
        setConversations(convs.data.map(conversationToMessage));
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

    // 場次狀態變更
    on('session_status', (payload) => {
      const data = payload as SessionStatusPayload;
      if (currentSession) {
        setCurrentSession({ ...currentSession, status: data.status as SessionStatus });
      }
    });

    return () => {
      off('stt_partial');
      off('stt_final');
      off('ai_response_start');
      off('ai_response_chunk');
      off('ai_response_end');
      off('red_flag_alert');
      off('session_status');
    };
  }, [sessionId, currentSession]); // eslint-disable-line react-hooks/exhaustive-deps

  // 自動捲動到底部
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [conversations, aiStreamingText, sttPartialText]);

  // 文字輸入狀態
  const [inputText, setInputText] = useState('');
  const [inputMode, setInputMode] = useState<'voice' | 'text'>('text'); // 預設改為文字比較好測試

  // 麥克風按鈕處理
  const handleMicToggle = useCallback(async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  // 發送文字訊息
  const handleSendText = () => {
    if (!inputText.trim()) return;
    
    // 透過 websocket 發送
    send('text_message', { text: inputText.trim() });
    
    // 加入畫面
    addConversation({
      id: `msg-${Date.now()}`,
      sessionId: sessionId!,
      sender: 'patient',
      content: inputText.trim(),
      timestamp: new Date().toISOString(),
    });
    
    setInputText('');
  };

  // 結束問診
  const handleEndSession = () => {
    send('control', { action: 'end_session' });
    navigate('/dashboard');
  };

  if (!currentSession && !error) {
    return <LoadingSpinner fullPage message="載入對話..." />;
  }

  const isSessionActive =
    currentSession?.status === 'in_progress' || currentSession?.status === 'waiting';

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

      {/* 底部控制區 */}
      <div className="border-t border-edge bg-white px-4 py-4 dark:bg-dark-surface dark:border-dark-border">
        {/* 模式切換鈕 */}
        <div className="flex justify-center mb-2 gap-4 text-sm">
          <button 
            className={`px-3 py-1 rounded-full ${inputMode === 'text' ? 'bg-primary-50 text-primary-600 font-medium' : 'text-ink-muted'}`}
            onClick={() => setInputMode('text')}
          >
            文字輸入
          </button>
          <button 
            className={`px-3 py-1 rounded-full ${inputMode === 'voice' ? 'bg-primary-50 text-primary-600 font-medium' : 'text-ink-muted'}`}
            onClick={() => setInputMode('voice')}
          >
            語音輸入
          </button>
        </div>

        {inputMode === 'voice' ? (
          <>
            {/* 波形視覺化 */}
            {isRecording && (
              <div className="mb-3 flex items-center justify-center gap-1">
                {waveformData.slice(0, 24).map((value, i) => (
                  <div
                    key={i}
                    className="w-1 rounded-full bg-alert-critical transition-all"
                    style={{ height: `${Math.max(4, value * 32)}px` }}
                  />
                ))}
                <span className="ml-3 text-caption font-data text-alert-critical">
                  {formatDuration(recordingDuration)}
                </span>
              </div>
            )}

            {/* 麥克風按鈕 */}
            <div className="flex items-center justify-center">
              <MicButton
                state={
                  !isSessionActive
                    ? 'disabled'
                    : isRecording
                      ? 'recording'
                      : isAIResponding
                        ? 'processing'
                        : 'idle'
                }
                onPress={handleMicToggle}
                mode="toggle"
                size="lg"
              />
            </div>
            <p className="mt-2 text-center text-small text-ink-muted">
              {isRecording ? '點擊停止錄音' : isAIResponding ? 'AI 回應中...' : '點擊開始說話'}
            </p>
          </>
        ) : (
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendText();
                }
              }}
              placeholder="輸入訊息..."
              className="flex-1 rounded-full border border-edge bg-surface-primary px-4 py-2.5 text-body text-ink-primary focus:border-primary-500 focus:outline-none dark:bg-dark-elem dark:text-white dark:border-dark-border"
              disabled={!isSessionActive || isAIResponding}
            />
            <button
              onClick={handleSendText}
              disabled={!inputText.trim() || !isSessionActive || isAIResponding}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-600 text-white disabled:opacity-50"
            >
              <svg className="h-5 w-5 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
