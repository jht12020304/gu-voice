// =============================================================================
// 語音問診對話頁（病患端核心頁面）
// =============================================================================

import { useEffect, useRef, useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
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
  TtsFailedPayload,
} from '../../types/websocket';

/** Fix 20：首次進入對話頁的 onboarding 提示 localStorage 鍵 */
const ONBOARDING_KEY = 'urosense:onboarding:voice:v1';

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
  const { t } = useTranslation(['conversation', 'common', 'ws']);
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useLocalizedNavigate();
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const activeSourceRef = useRef<AudioBufferSourceNode | null>(null);
  // 句級 TTS 佇列：每個 ai_response_chunk 帶來的音訊依序排入此鏈，前一句播完才播下一句
  const ttsChainRef = useRef<Promise<void>>(Promise.resolve());

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
    acknowledgeRedFlag,
    setError,
    resetSession,
    markMessageTtsFailed,
    appendTtsAudioChunk,
  } = useConversationStore();

  const { on, off, send } = useConversationWebSocket(sessionId ?? null);

  // 根據 session 狀態自動啟動 VAD（in_progress / waiting 時才開麥克風）
  const isSessionActiveForMic =
    currentSession?.status === 'in_progress' || currentSession?.status === 'waiting';
  const { muteVAD, unmuteVAD, enableBargeIn } = useAudioStream(isSessionActiveForMic);

  /** 立即停止目前正在播放的 TTS（用於使用者打斷 AI） */
  const stopActiveTTS = useCallback(() => {
    const src = activeSourceRef.current;
    if (src) {
      try {
        src.onended = null;
        src.stop();
      } catch {
        /* ignore */
      }
      activeSourceRef.current = null;
    }
  }, []);

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

  /**
   * 句級 TTS：將一個 base64 音訊排入播放佇列，並確保前一句播完才播下一句。
   * 與 playTTSAudio 不同的是，這個不會停掉正在播放的前一句 — 因為那會撞掉剛剛才
   * 開始播的句子。整條鏈由 ttsChainRef 串起，失敗會自動跳過這句繼續下一句。
   */
  const enqueueTTSAudioB64 = useCallback(
    (audioB64: string): void => {
      if (!audioB64) return;
      const step = async (): Promise<void> => {
        try {
          const binaryStr = atob(audioB64);
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
          // 等待前一句的 source 徹底播完（ttsChainRef 已經保證了順序，但保險起見
          // 若仍有殘留 activeSource，串到其 onended 之後）
          await new Promise<void>((resolve) => {
            const source = ctx.createBufferSource();
            source.buffer = audioBuf;
            source.connect(ctx.destination);
            source.onended = () => {
              if (activeSourceRef.current === source) {
                activeSourceRef.current = null;
              }
              resolve();
            };
            activeSourceRef.current = source;
            try {
              source.start(0);
            } catch (err) {
              console.error('[TTS] source.start 失敗:', err);
              resolve();
            }
          });
        } catch (err) {
          console.error('[TTS] 句級播放失敗:', err);
        }
      };
      ttsChainRef.current = ttsChainRef.current.then(step).catch((err) => {
        console.error('[TTS] 佇列步驟錯誤:', err);
      });
    },
    [],
  );

  /** 清空句級 TTS 播放佇列（用於使用者打斷 AI） */
  const clearTTSQueue = useCallback(() => {
    ttsChainRef.current = Promise.resolve();
  }, []);

  /**
   * Fix 18：重播某則 AI 訊息的快取 TTS 音訊。
   * 會先停掉目前正在播放的 TTS（與 in-flight 佇列共用 activeSourceRef）。
   * 若使用者 barge-in（開始說話），既有 effect 會呼叫 stopActiveTTS 也會停這個重播。
   */
  const replayMessageAudio = useCallback(
    (messageId: string) => {
      const msg = useConversationStore
        .getState()
        .conversations.find((m) => m.id === messageId);
      const chunks = msg?.ttsAudioChunks;
      if (!chunks || chunks.length === 0) return;

      // 停掉目前正在播放的任何 TTS（in-flight 串流或上一次的重播）
      stopActiveTTS();
      clearTTSQueue();

      // 把所有快取片段依序排入佇列
      chunks.forEach((b64) => enqueueTTSAudioB64(b64));
    },
    [stopActiveTTS, clearTTSQueue, enqueueTTSAudioB64],
  );

  /** Fix 16：統一把某則訊息標記為 TTS 失敗的 helper（Option A / B 共用） */
  const markMessageTtsFailedHelper = useCallback(
    (messageId: string) => {
      if (!messageId) return;
      markMessageTtsFailed(messageId);
    },
    [markMessageTtsFailed],
  );

  // Fix 20：首次 onboarding 提示狀態
  const [showOnboarding, setShowOnboarding] = useState(false);
  useEffect(() => {
    try {
      const seen = typeof window !== 'undefined' && window.localStorage.getItem(ONBOARDING_KEY);
      if (!seen) {
        setShowOnboarding(true);
        // 3 秒後自動消失
        const t = setTimeout(() => {
          setShowOnboarding(false);
          try {
            window.localStorage.setItem(ONBOARDING_KEY, '1');
          } catch {
            /* ignore */
          }
        }, 3000);
        return () => clearTimeout(t);
      }
    } catch {
      /* localStorage 不可用就忽略 */
    }
  }, []);

  // 偵測到第一次說話時，立即關閉 onboarding 並寫入 localStorage
  useEffect(() => {
    if (showOnboarding && isRecording) {
      setShowOnboarding(false);
      try {
        window.localStorage.setItem(ONBOARDING_KEY, '1');
      } catch {
        /* ignore */
      }
    }
  }, [showOnboarding, isRecording]);

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
        setError(t('conversation:error.loadFailed'));
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
      // AI 準備說話 → 進入 barge-in 模式：VAD 仍開著，但用較高門檻，
      // 使用者大聲講話即可打斷 AI（見下方 isRecording + isAIResponding 的 effect）。
      enableBargeIn();
      addConversation({
        id: data.messageId,
        sessionId: sessionId!,
        sender: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        isStreaming: true,
      });
    });

    // AI 回應串流片段（句級：每句同時帶 text + base64 audio）
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
      // Fix 16 Option B：此 chunk 直接帶 ttsFailed → 標記訊息
      if (data.ttsFailed) {
        markMessageTtsFailedHelper(data.messageId);
      }
      // Fix 18：若此句有音訊，快取到訊息上 + 排入 TTS 佇列依序播放
      if (data.audioB64) {
        appendTtsAudioChunk(data.messageId, data.audioB64);
        enqueueTTSAudioB64(data.audioB64);
      }
    });

    // Fix 16 Option A：獨立的 tts_failed 事件
    on('tts_failed', (payload) => {
      const data = payload as TtsFailedPayload;
      markMessageTtsFailedHelper(data.messageId);
    });

    // AI 回應結束（音訊已透過 ai_response_chunk 逐句送達，此處僅最終化文字）
    on('ai_response_end', (payload) => {
      const data = payload as AIResponseEndPayload;
      finalizeAIResponse(data.messageId, data.fullText);
      // 向後相容：若後端仍送來整段 ttsAudioUrl（舊流程），才用舊的 playTTSAudio
      if (data.ttsAudioUrl) {
        playTTSAudio(data.ttsAudioUrl);
        return;
      }
      // 句級流程：在佇列尾端附加一個「播完所有句子 → 恢復正常 VAD 門檻」步驟。
      // 若沒有任何句子有音訊（如全部 TTS 失敗），這個步驟會立即執行。
      ttsChainRef.current = ttsChainRef.current.then(() => {
        unmuteVAD();
      });
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

    // 場次狀態變更（TODO-E2：canonical code payload；code/params 渲染走 i18n）
    on('session_status', (payload) => {
      const data = payload as SessionStatusPayload;
      if (currentSession && data.status) {
        setCurrentSession({ ...currentSession, status: data.status as SessionStatus });
      }
      if (data.status === 'completed') {
        navigate(`/patient/session/${sessionId}/thank-you`, { replace: true });
      } else if (data.status === 'failed') {
        setError(t('conversation:error.sessionInterrupted'));
      } else if (data.code) {
        // 非最終狀態（idle_timeout / aborted_red_flag / resumed 等）用 canonical code 提示
        setError(
          t(data.code, {
            ns: 'ws',
            ...(data.params ?? {}),
            defaultValue: t('conversation:error.sessionInterrupted'),
          }) as string,
        );
      }
    });

    // 後端錯誤（TODO-E2：canonical code payload）
    on('error', (payload) => {
      const data = payload as { code?: string; params?: Record<string, unknown> };
      if (data.code) {
        setError(
          t(data.code, {
            ns: 'ws',
            ...(data.params ?? {}),
            defaultValue: t('conversation:error.aiUnavailable'),
          }) as string,
        );
      } else {
        setError(t('conversation:error.aiUnavailable'));
      }
      // 也解除 VAD mute，避免使用者卡在「等 AI 回應」的狀態
      unmuteVAD();
    });

    // WebSocket 連線狀態
    on('_disconnected', () => {
      setError(t('conversation:error.disconnected'));
      muteVAD(); // 斷線期間暫停收音
    });
    on('_reconnecting', () => {
      setError(t('conversation:error.disconnected'));
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
      off('tts_failed');
      off('red_flag_alert');
      off('session_status');
      off('error');
      off('_disconnected');
      off('_reconnecting');
      off('_connected');
    };
  }, [sessionId, currentSession]); // eslint-disable-line react-hooks/exhaustive-deps

  // 使用者 barge-in：AI 正在講話時 VAD 觸發錄音 → 立即停掉 TTS 並清空句級佇列，
  // 讓使用者接手。否則佇列中剩餘句子會在 stopActiveTTS 後繼續播放。
  useEffect(() => {
    if (isRecording && isAIResponding) {
      stopActiveTTS();
      clearTTSQueue();
    }
  }, [isRecording, isAIResponding, stopActiveTTS, clearTTSQueue]);

  // 聊天自動捲動（使用者上捲時暫停）
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const [pendingNewMessages, setPendingNewMessages] = useState(0);
  const SCROLL_BOTTOM_THRESHOLD_PX = 100;

  const handleChatScroll = useCallback(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > SCROLL_BOTTOM_THRESHOLD_PX) {
      setUserScrolledUp(true);
    } else {
      setUserScrolledUp(false);
      setPendingNewMessages(0);
    }
  }, []);

  const scrollChatToBottom = useCallback((smooth = true) => {
    const el = chatContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    setUserScrolledUp(false);
    setPendingNewMessages(0);
  }, []);

  // 自動捲動到底部（未上捲時才自動捲動；上捲時累積未讀計數）
  useEffect(() => {
    if (!chatContainerRef.current) return;
    if (!userScrolledUp) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    } else {
      setPendingNewMessages((n) => n + 1);
    }
    // userScrolledUp 本身改變時不應被視為有新訊息，因此不列入 deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations.length]);

  // AI 串流文字 / STT 部分結果更新時，若未上捲則跟著捲動到底部
  useEffect(() => {
    if (!chatContainerRef.current || userScrolledUp) return;
    chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
  }, [aiStreamingText, sttPartialText, userScrolledUp]);

  // 結束問診
  const handleEndSession = () => {
    send('control', { action: 'end_session' });
    navigate(`/patient/session/${sessionId}/thank-you`, { replace: true });
  };

  if (!currentSession && !error) {
    return <LoadingSpinner fullPage message={t('conversation:loading')} />;
  }

  const isSessionActive = isSessionActiveForMic;

  // 未確認的紅旗（依嚴重度排序：critical > high > medium > low）
  const severityRank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const unacknowledgedFlags = activeRedFlags
    .filter((f) => !f.isAcknowledged)
    .slice()
    .sort(
      (a, b) =>
        (severityRank[a.severity] ?? 99) - (severityRank[b.severity] ?? 99),
    );
  const visibleFlags = unacknowledgedFlags.slice(0, 3);
  const extraFlagCount = Math.max(0, unacknowledgedFlags.length - visibleFlags.length);

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
          <h1 className="text-caption font-semibold text-ink-heading dark:text-white">{t('conversation:title')}</h1>
          <div className="flex items-center justify-center gap-2">
            {currentSession && <StatusBadge status={currentSession.status as SessionStatus} size="sm" />}
          </div>
        </div>
        <button
          className="rounded-btn px-3 py-1.5 text-caption font-medium text-alert-critical hover:bg-alert-critical-bg transition-colors"
          onClick={handleEndSession}
        >
          {t('conversation:endSession')}
        </button>
      </header>

      {/* 紅旗警示橫幅（最多 3 張疊起，依嚴重度排序） */}
      {visibleFlags.length > 0 && (
        <div className="flex flex-col gap-1 border-b border-red-700 bg-alert-critical/5 px-4 py-2 animate-slide-down">
          {visibleFlags.map((alert) => {
            const bg =
              alert.severity === 'critical'
                ? 'bg-alert-critical'
                : alert.severity === 'high'
                  ? 'bg-orange-600'
                  : 'bg-yellow-600';
            return (
              <div
                key={alert.id}
                className={`flex items-start justify-between gap-3 rounded-card px-3 py-2 text-white shadow-sm ${bg}`}
              >
                <div className="flex items-start gap-2 flex-1 min-w-0">
                  <svg
                    className="h-5 w-5 flex-shrink-0 mt-0.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                    />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <p className="text-body font-medium truncate">{alert.title}</p>
                    {alert.description && (
                      <p className="mt-0.5 text-small opacity-90 line-clamp-2">
                        {alert.description}
                      </p>
                    )}
                  </div>
                </div>
                <button
                  className="flex-shrink-0 rounded-btn bg-white/20 px-3 py-1 text-caption font-medium hover:bg-white/30 transition-colors"
                  onClick={() => acknowledgeRedFlag(alert.id)}
                >
                  {t('common:acknowledge')}
                </button>
              </div>
            );
          })}
          {extraFlagCount > 0 && (
            <p className="px-1 text-small text-ink-secondary dark:text-slate-300">
              {t('conversation:redFlag.more', { count: extraFlagCount })}
            </p>
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
      <div className="relative flex-1 min-h-0">
      <div
        ref={chatContainerRef}
        onScroll={handleChatScroll}
        className="absolute inset-0 overflow-y-auto px-4 py-4"
      >
        {conversations.map((msg) => (
          <ChatBubble
            key={msg.id}
            message={{
              id: msg.id,
              content: msg.content,
              sender: msg.sender,
              timestamp: msg.timestamp,
              isStreaming: msg.isStreaming,
              sttConfidence: msg.sttConfidence,
              hasTtsFailure: msg.hasTtsFailure,
              canReplay: (msg.ttsAudioChunks?.length ?? 0) > 0,
            }}
            onReplay={replayMessageAudio}
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
              <div className="thinking-dots text-ink-secondary dark:text-slate-400">
                <span /><span /><span />
              </div>
            </div>
          </div>
        )}
      </div>

        {/* 「回到最新訊息」浮動按鈕（使用者上捲且有新訊息時顯示） */}
        {userScrolledUp && (
          <button
            onClick={() => scrollChatToBottom(true)}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-primary-600 px-4 py-2 text-caption font-medium text-white shadow-lg hover:bg-primary-700 transition-colors flex items-center gap-1.5"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
            <span>
              {pendingNewMessages > 0
                ? t('conversation:scroll.latestWithCount', { count: pendingNewMessages })
                : t('conversation:scroll.latest')}
            </span>
          </button>
        )}
      </div>

      {/* 底部控制區（自動語音偵測） */}
      <div className="relative border-t border-edge bg-white px-4 py-5 dark:bg-dark-surface dark:border-dark-border">
        {/* Fix 20：首次 onboarding 提示（3 秒或首次說話後消失） */}
        {showOnboarding && (
          <div
            role="status"
            aria-live="polite"
            className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-full mb-2 animate-slide-down rounded-card bg-ink-heading px-3 py-2 text-caption font-medium text-white shadow-elevated dark:bg-slate-200 dark:text-slate-900 whitespace-nowrap"
          >
            {t('conversation:onboarding.hint')}
            <span
              className="absolute left-1/2 top-full -translate-x-1/2 h-0 w-0 border-x-8 border-t-8 border-x-transparent border-t-ink-heading dark:border-t-slate-200"
              aria-hidden="true"
            />
          </div>
        )}
        {/* 麥克風狀態指示圈（顯示狀態，無需點擊） */}
        <div className="flex items-center justify-center">
          <div
            className={`flex h-14 w-14 items-center justify-center rounded-full transition-colors ${
              !isSessionActive
                ? 'bg-surface-tertiary text-ink-placeholder dark:bg-dark-card dark:text-slate-500'
                : isAIResponding
                  ? 'bg-primary-50 text-primary-500 dark:bg-primary-950 dark:text-primary-300'
                  : isRecording
                    ? 'bg-alert-critical text-white shadow-lg shadow-alert-critical/30'
                    : 'bg-primary-50 text-primary-600 dark:bg-primary-950 dark:text-primary-300'
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

        {/* 波形視覺化：錄音時顯示即時頻譜彩條，閒置時顯示低透明度呼吸動畫佔位 */}
        <div className="mt-3 flex items-end justify-center gap-1 h-10">
          {isRecording
            ? waveformData.slice(0, 32).map((value, i) => {
                const height = Math.max(3, value * 38);
                return (
                  <div
                    key={i}
                    className="w-1 rounded-full bg-alert-critical transition-all duration-75"
                    style={{ height: `${height}px` }}
                  />
                );
              })
            : Array.from({ length: 32 }).map((_, i) => (
                <div
                  key={i}
                  className="w-1 h-1.5 rounded-full bg-primary-300/50 dark:bg-primary-700/50 animate-pulse"
                  style={{ animationDelay: `${(i % 8) * 80}ms` }}
                />
              ))}
        </div>

        {/* 狀態文字（Fix 21：改用 ink-secondary 達到 WCAG AA） */}
        <p className="mt-2 text-center text-small text-ink-secondary dark:text-slate-300">
          {!isSessionActive
            ? t('conversation:status.notStarted')
            : isAIResponding
              ? t('conversation:status.aiResponding')
              : isRecording
                ? t('conversation:status.listening', { duration: formatDuration(recordingDuration) })
                : t('conversation:status.idle')}
        </p>
      </div>
    </div>
  );
}
