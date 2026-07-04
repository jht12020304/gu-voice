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
import {
  useConversationStore,
  conversationToMessage,
  normalizeSupervisorGuidance,
  shouldUnmuteVAD,
} from '../../stores/conversationStore';
import type {
  SupervisorGuidancePayload,
  VadResumeTrigger,
} from '../../stores/conversationStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { useConversationWebSocket } from '../../hooks/useWebSocket';
import { conversationWS } from '../../services/websocket';
import { useAudioStream } from '../../hooks/useAudioStream';
import * as sessionsApi from '../../services/api/sessions';
import { formatDuration } from '../../utils/format';
import type { SessionStatus } from '../../types/enums';
import type { Session } from '../../types';
import type {
  STTFinalPayload,
  AIResponseStartPayload,
  AIResponseChunkPayload,
  AIResponseEndPayload,
  RedFlagAlertPayload,
  SessionStatusPayload,
} from '../../types/websocket';

/** Fix 20：首次進入對話頁的 onboarding 提示 localStorage 鍵 */
const ONBOARDING_KEY = 'urosense:onboarding:voice:v1';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

/** #6 AI 語音語速循環選項（前端 playbackRate 倍率） */
const SPEED_PRESETS = [1.0, 1.25, 1.5];

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
  // TTS 世代：clearTTSQueue（靜音/打斷）會 +1；已排入但尚未播的句子比對 epoch 不符即跳過，
  // 避免「在句子間隙靜音時，下一句仍照播」（光重設 ttsChainRef 擋不掉已 chain 的 callback）。
  const ttsEpochRef = useRef(0);

  const {
    currentSession,
    conversations,
    isRecording,
    isAIResponding,
    sttProcessing,
    userPaused,
    sttPartialText,
    aiStreamingText,
    recordingDuration,
    waveformData,
    activeRedFlags,
    supervisorGuidance,
    supervisorDegraded,
    error,
    setCurrentSession,
    addConversation,
    setConversations,
    updateSTTPartial,
    setSttProcessing,
    setUserPaused,
    setAIResponding,
    appendAIStreamingText,
    finalizeAIResponse,
    addRedFlag,
    acknowledgeRedFlag,
    setSupervisorGuidance,
    setSupervisorDegraded,
    setError,
    resetSession,
    markMessageTtsFailed,
    appendTtsAudioChunk,
  } = useConversationStore();

  const { on, off, send, retry, connectionState } = useConversationWebSocket(sessionId ?? null);

  // 是否曾經連線成功 — 用來區分「初次連線中（不警示）」與「斷線後重連中（要警示）」。
  const hasConnectedRef = useRef(false);
  if (connectionState === 'open') hasConnectedRef.current = true;

  // #4：出聲模式 AI 回合硬鎖是否尚未由 TTS 鏈解除。isAIResponding 在 ai_response_end 事件時
  // 就被 finalizeAIResponse 設回 false（TTS 可能還在播），不能拿來判斷硬鎖，故獨立追蹤。
  const pendingAiUnmuteRef = useRef(false);
  // W4-3：重播（點擊訊息重聽 TTS）播放期間的硬鎖，語意等同 pendingAiUnmuteRef 但獨立追蹤——
  // 重播可能發生在「無 AI 回合進行中」（單純重聽舊訊息）或「打斷仍在串流的 AI 回合」兩種
  // 情境，兩顆鎖各自對應各自的音訊來源是否仍在播放／佇列中，任一顆鎖著都不得自動開麥
  // （見下方 unmuteIfAllowed 的 aiTurnLocked 計算，OR 兩者）。
  const pendingReplayUnmuteRef = useRef(false);

  // 根據 session 狀態自動啟動 VAD（in_progress / waiting 時才開麥克風）
  const isSessionActiveForMic =
    currentSession?.status === 'in_progress' || currentSession?.status === 'waiting';
  const { muteVAD, unmuteVAD, forceEndSegment } = useAudioStream(isSessionActiveForMic);

  /** #4：所有「自動恢復收音」路徑一律走這裡，由 shouldUnmuteVAD 決策矩陣把關。
   * wsDown 直接讀 WS 服務的同步狀態，不走 React state（render 才同步的 ref 會慢半拍：
   * onclose 內停掉 TTS 時鏈尾 microtask 緊接著跑，讀到過期的 'open' 就會在斷線瞬間解鎖）。 */
  const unmuteIfAllowed = useCallback(
    (trigger: VadResumeTrigger) => {
      if (
        shouldUnmuteVAD(trigger, {
          userPaused: useConversationStore.getState().userPaused,
          // W4-3：AI 回合硬鎖 OR 重播硬鎖，任一鎖著都不放行自動開麥。
          aiTurnLocked: pendingAiUnmuteRef.current || pendingReplayUnmuteRef.current,
          wsDown: conversationWS.getConnectionState() !== 'open',
        })
      ) {
        unmuteVAD();
      }
    },
    [unmuteVAD],
  );

  // 連線中斷／重連中 → 顯示非警示性持續橫幅（病患不會對著死連線講話）。
  // 條件：曾經連上過（排除初次載入中），且場次仍進行中（排除結束導向時的 disconnect）。
  const isConnectionDown =
    hasConnectedRef.current &&
    isSessionActiveForMic &&
    (connectionState === 'reconnecting' || connectionState === 'closed');

  /** 立即停止目前正在播放的 TTS（用於使用者打斷 AI） */
  const stopActiveTTS = useCallback(() => {
    const src = activeSourceRef.current;
    if (src) {
      // 醫療安全：句級佇列（enqueueTTSAudioB64）的 step promise 靠 onended resolve；
      // 若只把 handler 清掉再 stop()，該 promise 永不 resolve，ai_response_end 掛在鏈尾
      // 的「清硬鎖 + 恢復收音」步驟就永遠不會執行 → VAD 卡死。故取下 handler 後手動
      // 呼叫一次（不留給 stop() 觸發，確保 stop() 拋錯時鏈也一定前進）。
      const onended = src.onended;
      src.onended = null;
      activeSourceRef.current = null;
      try {
        src.stop();
      } catch {
        /* ignore */
      }
      if (onended) {
        try {
          onended.call(src, new Event('ended'));
        } catch {
          /* ignore */
        }
      }
    }
  }, []);

  // TTS 播放（用 AudioContext + atob 直接解碼 base64，避開 CSP connect-src 對 data: URL 的限制）
  // 播放期間 VAD 保持靜音，播完後恢復 VAD 讓使用者直接說下一句
  const playTTSAudio = useCallback(
    async (dataUrl: string): Promise<void> => {
      if (!dataUrl) {
        pendingAiUnmuteRef.current = false;
        unmuteIfAllowed('ai_tts_done');
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
        // #6 語速：前端 playbackRate（純前端、即時，會略升音高，已限 ≤1.5）
        source.playbackRate.value = useSettingsStore.getState().ttsSpeed;
        source.connect(ctx.destination);
        source.onended = () => {
          activeSourceRef.current = null;
          // TTS 播完 → 恢復 VAD，使用者可以直接說下一句
          pendingAiUnmuteRef.current = false;
          unmuteIfAllowed('ai_tts_done');
        };
        activeSourceRef.current = source;
        source.start(0);
      } catch (err) {
        console.error('[TTS] 播放失敗:', err);
        // 出錯也要恢復 VAD，避免卡死
        pendingAiUnmuteRef.current = false;
        unmuteIfAllowed('ai_tts_done');
      }
    },
    [unmuteIfAllowed],
  );

  /**
   * 句級 TTS：將一個 base64 音訊排入播放佇列，並確保前一句播完才播下一句。
   * 與 playTTSAudio 不同的是，這個不會停掉正在播放的前一句 — 因為那會撞掉剛剛才
   * 開始播的句子。整條鏈由 ttsChainRef 串起，失敗會自動跳過這句繼續下一句。
   */
  const enqueueTTSAudioB64 = useCallback(
    (audioB64: string): void => {
      if (!audioB64) return;
      const epoch = ttsEpochRef.current;
      const step = async (): Promise<void> => {
        // 已被 clearTTSQueue 取消（靜音 / barge-in）→ 跳過這句，不要在靜音後又播出來。
        if (ttsEpochRef.current !== epoch) return;
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
          // decode 是 async，期間可能剛好被靜音 / 打斷 → 再檢查一次 epoch 才播。
          if (ttsEpochRef.current !== epoch) return;
          // 等待前一句的 source 徹底播完（ttsChainRef 已經保證了順序，但保險起見
          // 若仍有殘留 activeSource，串到其 onended 之後）
          await new Promise<void>((resolve) => {
            const source = ctx.createBufferSource();
            source.buffer = audioBuf;
            // #6 語速：套用使用者設定的播放倍率（replay 也吃同一設定）
            source.playbackRate.value = useSettingsStore.getState().ttsSpeed;
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

  /** 清空句級 TTS 播放佇列（用於使用者打斷 AI / 靜音）。bump epoch 讓已排入但尚未播的句子失效。 */
  const clearTTSQueue = useCallback(() => {
    ttsEpochRef.current += 1;
    ttsChainRef.current = Promise.resolve();
  }, []);

  // ── #6 AI 語音（TTS）控制：靜音 / 語速 / 打字輸入 ──────────────
  const ttsMuted = useSettingsStore((s) => s.ttsMuted);
  const ttsSpeed = useSettingsStore((s) => s.ttsSpeed);
  const toggleTtsMuted = useSettingsStore((s) => s.toggleTtsMuted);
  const setTtsSpeed = useSettingsStore((s) => s.setTtsSpeed);

  const cycleSpeed = useCallback(() => {
    const idx = SPEED_PRESETS.findIndex((p) => Math.abs(p - ttsSpeed) < 0.01);
    const next = SPEED_PRESETS[(idx + 1) % SPEED_PRESETS.length] ?? 1.0;
    setTtsSpeed(next);
  }, [ttsSpeed, setTtsSpeed]);

  // 切到「靜音」時：立即停掉正在播的句子 + 清空佇列，並確保 VAD 不會卡住（醫療安全：
  // 病患必須能繼續說話）。切回「出聲」不需處理，下一句 AI 回覆自然會播。
  const handleToggleMute = useCallback(() => {
    const willMute = !ttsMuted;
    toggleTtsMuted();
    if (willMute) {
      stopActiveTTS();
      clearTTSQueue();
      pendingAiUnmuteRef.current = false;
      unmuteIfAllowed('tts_mute_toggle');
    }
  }, [ttsMuted, toggleTtsMuted, stopActiveTTS, clearTTSQueue, unmuteIfAllowed]);

  // 打字輸入：語音收不到時的備援。樂觀在本地顯示病患氣泡，再送後端 text_message
  // （後端會走與語音同一條 _handle_text_message：紅旗篩檢 / LLM / auto-conclude 都照跑）。
  const [textDraft, setTextDraft] = useState('');
  const handleSendText = useCallback(() => {
    const text = textDraft.trim();
    if (!text || !sessionId) return;
    // 醫療安全：連線中斷時，send() 會靜默丟棄（只 console.warn）。若仍樂觀顯示氣泡 + 清空草稿，
    // 病患會誤以為已送出，但後端從未收到 → 該症狀陳述不會經紅旗篩檢、也無法重送。
    // 故未連線時：保留草稿、不顯示假氣泡、不送出（送出鍵也會在未連線時 disabled）。
    if (connectionState !== 'open') {
      setError(t('conversation:input.sendOffline'));
      return;
    }
    setError(null);
    addConversation({
      id: crypto.randomUUID(),
      sessionId,
      sender: 'patient',
      content: text,
      timestamp: new Date().toISOString(),
    });
    send('text_message', { text });
    setTextDraft('');
  }, [textDraft, sessionId, addConversation, send, connectionState, setError, t]);

  // #4：暫停/繼續收音。暫停會先 flush 進行中的段落（已講的半句照常送出辨識——
  // MediaRecorder fallback 的 chunk 已即時上送，丟棄會在後端留下無 isFinal 的殘段），
  // 再通知後端進入 is_paused；繼續則交由決策矩陣決定是否立即開麥。
  const handleTogglePause = useCallback(() => {
    if (!useConversationStore.getState().userPaused) {
      setUserPaused(true);
      muteVAD(); // hard-mute：isSpeaking 時同步 flush（WAV chunk + isFinal）→ 先於 pause 控制送達
      send('control', { action: 'pause_recording' });
    } else {
      setUserPaused(false);
      send('control', { action: 'resume_recording' });
      unmuteIfAllowed('user_resume'); // AI 出聲硬鎖中則保持 mute，TTS 播畢由鏈尾解鎖
    }
  }, [setUserPaused, muteVAD, send, unmuteIfAllowed]);

  // #4：「我說完了」——立即結束當前段落送出，不等 2 秒靜音（audioStream silenceEndMs=2000）
  const handleFinishSpeaking = useCallback(() => {
    forceEndSegment();
  }, [forceEndSegment]);

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

      // W4-3：重播播放期間比照 AI 出聲硬鎖，避免喇叭放語音時麥克風開著造成回授
      // （回授不變式）。用獨立旗標追蹤（見 pendingReplayUnmuteRef 宣告處說明）。
      // 若此刻沒有「仍在串流」的 AI 回合（isAIResponding false）——即使
      // pendingAiUnmuteRef 還是 true，它原本掛在鏈尾的釋放步驟也已被上面
      // clearTTSQueue() 判為過期、永遠不會再跑，不視同接管清掉會讓硬鎖永久卡住
      // （死鎖）。若仍在串流，保留該旗標，交由真正 AI 回合之後用新世代續接的鏈尾
      // （不會過期）自行決定何時釋放；重播鏈尾只釋放「重播」自己這一份鎖，兩者
      // 各自獨立、由 unmuteIfAllowed 的 aiTurnLocked 一併把關。
      if (!useConversationStore.getState().isAIResponding) {
        pendingAiUnmuteRef.current = false;
      }
      pendingReplayUnmuteRef.current = true;
      muteVAD();

      // 把所有快取片段依序排入佇列
      chunks.forEach((b64) => enqueueTTSAudioB64(b64));

      // 鏈尾補上「重播播畢 → 解鎖重播硬鎖」步驟；epoch 防禦同 ai_response_end：若鏈尾
      // 執行時世代已變（又被新的重播 / 靜音切換 / 斷線打斷），代表本次重播已被取代，
      // 鎖的釋放交給新擁有者自己的鏈尾步驟負責，這裡不得越權清鎖。
      const chainEpoch = ttsEpochRef.current;
      ttsChainRef.current = ttsChainRef.current.then(() => {
        if (ttsEpochRef.current !== chainEpoch) return;
        pendingReplayUnmuteRef.current = false;
        unmuteIfAllowed('replay_end');
      });
    },
    [stopActiveTTS, clearTTSQueue, enqueueTTSAudioB64, muteVAD, unmuteIfAllowed],
  );

  /** Fix 16：統一把某則訊息標記為 TTS 失敗的 helper（Option A / B 共用） */
  const markMessageTtsFailedHelper = useCallback(
    (messageId: string) => {
      if (!messageId) return;
      markMessageTtsFailed(messageId);
    },
    [markMessageTtsFailed],
  );

  // #6：空 stt_final 的短暫可見提示（系統提示樣式，非對話氣泡），4 秒自動消失、再開口即收
  const [showNoSpeechHint, setShowNoSpeechHint] = useState(false);
  const noSpeechTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flashNoSpeechHint = useCallback(() => {
    setShowNoSpeechHint(true);
    if (noSpeechTimerRef.current) clearTimeout(noSpeechTimerRef.current);
    noSpeechTimerRef.current = setTimeout(() => setShowNoSpeechHint(false), 4000);
  }, []);
  useEffect(
    () => () => {
      if (noSpeechTimerRef.current) clearTimeout(noSpeechTimerRef.current);
    },
    [],
  );
  useEffect(() => {
    if (isRecording) setShowNoSpeechHint(false);
  }, [isRecording]);

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
      } catch (err) {
        console.error('[ConversationPage] load failed', err);
        const anyErr = err as any;
        if (anyErr?.response) {
          console.error('[ConversationPage] response.status=', anyErr.response.status, 'data=', anyErr.response.data);
        }
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
    // STT 最終結果（後端僅送 stt_final，無 stt_partial）
    on('stt_final', (payload) => {
      const data = payload as STTFinalPayload;
      updateSTTPartial('');
      setSttProcessing(false); // #3：辨識結果已到，清除「正在辨識」提示
      // 醫療安全：Whisper 沒聽出字（空辨識）時後端不會回 ai_response，而 onSpeechEnd 已把
      // VAD hard-mute；若不在這裡重新解鎖，病患就無法再用語音開口（minSpeechMs 調低後更易遇到）。
      // 空結果時 re-arm VAD 並略過空氣泡；有字才照常顯示並等 AI 回覆（回覆結束會自然 unmute）。
      if (!data.text || !data.text.trim()) {
        // #6：空辨識不再靜默——暫停中不提示（暫停徽章已說明現況），其餘顯示短暫提示
        if (!useConversationStore.getState().userPaused) flashNoSpeechHint();
        unmuteIfAllowed('empty_stt');
        return;
      }
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
      setSttProcessing(false); // #3：AI 開始回應 → 切換到「AI 回應中」，清除辨識提示
      setAIResponding(true);
      // #1 AI 講話時鎖麥克風：出聲模式硬鎖 VAD 整個 AI 回合，杜絕病患聲音或喇叭→麥克風
      // 回授被當成下一個答案（病患回報「AI 講話時收到聲音會直接變成答案」）。回合結束由
      // 下方 ai_response_end 的 ttsChain.then(unmuteVAD) 解鎖；空 STT/錯誤/重連也都會 re-arm
      // （VAD 不可卡死不變式）。靜音模式沒有 TTS 可回授 → 用正常門檻開 VAD 讓病患能立刻接話。
      if (useSettingsStore.getState().ttsMuted) {
        pendingAiUnmuteRef.current = false;
        unmuteIfAllowed('ai_start_tts_muted');
      } else {
        pendingAiUnmuteRef.current = true;
        muteVAD();
      }
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
      // Fix 18：音訊一律快取到訊息上（讓「播放鍵」/replay 在靜音模式仍可用），
      // 但只有「非靜音」時才自動排入佇列播放（#6 靜音＝只擋自動播放，不影響文字/紅旗）。
      if (data.audioB64) {
        appendTtsAudioChunk(data.messageId, data.audioB64);
        if (!useSettingsStore.getState().ttsMuted) {
          enqueueTTSAudioB64(data.audioB64);
        }
      }
    });

    // AI 回應結束（音訊已透過 ai_response_chunk 逐句送達，此處僅最終化文字）
    on('ai_response_end', (payload) => {
      const data = payload as AIResponseEndPayload;
      finalizeAIResponse(data.messageId, data.fullText);
      // 醫療安全：靜音時不可走 playTTSAudio，必須讓流程落到下方 ttsChain 的 unmuteVAD()，
      // 否則 VAD 會卡在 mute、病患無法再開口。出聲且有舊式 ttsAudioUrl 才用 playTTSAudio。
      if (data.ttsAudioUrl && !useSettingsStore.getState().ttsMuted) {
        playTTSAudio(data.ttsAudioUrl);
        return;
      }
      // 句級流程：在佇列尾端附加一個「播完所有句子 → 恢復正常 VAD 門檻」步驟。
      // 靜音時佇列沒有音訊步驟，這個 unmute 會立即執行（病患永遠能繼續說話）。
      // W4-2/W4-3 epoch 防禦：捕捉附加當下的世代；若鏈尾真正執行時世代已變（被
      // clearTTSQueue 打斷——重播 / 靜音切換 / 斷線），代表本回合已被新的擁有者
      // 取代，鎖的釋放交由新擁有者自己的鏈尾步驟負責，這裡不得越權清鎖／開麥
      // （否則會打穿新擁有者的硬鎖，見 replayMessageAudio 的對稱處理）。
      const chainEpoch = ttsEpochRef.current;
      ttsChainRef.current = ttsChainRef.current.then(() => {
        if (ttsEpochRef.current !== chainEpoch) return;
        pendingAiUnmuteRef.current = false;
        unmuteIfAllowed('ai_tts_done');
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

    // CONV-2：Supervisor 動態問診指導（後端 snake_case payload → 前端 camelCase）
    on('supervisor_guidance', (payload) => {
      const data = payload as SupervisorGuidancePayload;
      setSupervisorGuidance(normalizeSupervisorGuidance(data));
    });

    // CONV-2：Supervisor 降級（逾時／不可用）→ 設旗標，UI 顯示非警示性提示
    on('supervisor_degraded', () => {
      setSupervisorDegraded(true);
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
      // #3：錯誤路徑（rate limit / 音訊格式 / STT 失敗）後端不會送 stt_final，這裡清辨識提示
      setSttProcessing(false);
      // 也解除 VAD mute，避免使用者卡在「等 AI 回應」的狀態
      pendingAiUnmuteRef.current = false;
      pendingReplayUnmuteRef.current = false; // W4-3：錯誤路徑視為各硬鎖來源皆作廢，避免卡死
      unmuteIfAllowed('ws_error');
    });

    // WebSocket 連線狀態：透過頂部非警示性「重連中」橫幅呈現（見下方 isConnectionDown），
    // 不再灌入 error（保留給真正的對話／場次錯誤）。此處僅控制斷線期間暫停收音。
    on('_disconnected', () => {
      // 斷線即停掉本地仍在播的 TTS 並清佇列（該 AI 回合已作廢）：否則 _connected 解鎖
      // 麥克風時喇叭還在播 AI 語音，回授會被當成病患答案（AI 講話期間硬鎖麥克風不變式）。
      // 文字已在畫面上，病患可用重播鍵重聽。muteVAD 放最後：stopActiveTTS 會補跑 onended
      // （舊式 playTTSAudio 路徑會同步 unmute），最後 mute 確保斷線期間必定停止收音。
      stopActiveTTS();
      clearTTSQueue();
      muteVAD(); // 斷線期間暫停收音，避免對著死連線講話
      setSttProcessing(false); // #3：斷線時清辨識提示，避免卡住
    });
    on('_connected', () => {
      pendingAiUnmuteRef.current = false; // 後端 handler 重啟，舊 AI 回合作廢
      pendingReplayUnmuteRef.current = false; // W4-3：重播鎖同理，連線是全新的，重播已無意義
      // W4-2：unmute 前防禦——保險起見清掉任何殘留 TTS 播放/佇列。正常應已由 _disconnected
      // 清空；此處防禦「_disconnected 未觸發的快速斷連」或「TTS chain 卡在 await 中段」等
      // 邊界路徑，避免喇叭仍放語音時麥克風已被打開造成回授。冪等：無殘留時為 no-op。
      stopActiveTTS();
      clearTTSQueue();
      if (useConversationStore.getState().userPaused) {
        // 後端 is_paused 是連線區域變數（conversation_handler.py），重連即歸零 → 重申暫停
        send('control', { action: 'pause_recording' });
      } else {
        unmuteIfAllowed('reconnected'); // 重連成功 → 恢復收音
      }
    });

    return () => {
      off('connection_ack');
      off('stt_final');
      off('ai_response_start');
      off('ai_response_chunk');
      off('ai_response_end');
      off('red_flag_alert');
      off('supervisor_guidance');
      off('supervisor_degraded');
      off('session_status');
      off('error');
      off('_disconnected');
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

  // #4：麥克風重開（openMic 會把 mute 狀態重設）或任何競態下，手動暫停必須重新生效。
  // isRecording 列入 deps：若 mute 在暫停期間遺失、VAD 意外開錄，此 effect 會立即重新
  // hard-mute（後端 is_paused 另有丟棄 audio_chunk 的第二道防線）。
  useEffect(() => {
    if (isSessionActiveForMic && userPaused) muteVAD();
  }, [isSessionActiveForMic, userPaused, isRecording, muteVAD]);

  // W4-1：AI 出聲硬鎖／重播硬鎖同款 re-assert（比照上面 userPaused）。麥克風重開會讓
  // useAudioStream 的開麥 effect 重跑、把 vadMuteMode 重設為 none；此時若硬鎖仍生效
  // （AI 出聲中或重播播放中）需要立即補鎖，否則喇叭放語音、麥克風卻悄悄開著會造成
  // 回授（違反回授不變式）。isRecording 列入 deps 同上：若補鎖有空窗、VAD 意外先開錄，
  // 這裡會在偵測到開錄的當下立刻重新 hard-mute（並中止該段落；後端 is_paused 以外，
  // AI 回合本身無第二道防線，故此 re-assert 尤其重要）。pendingAiUnmuteRef /
  // pendingReplayUnmuteRef 是 ref，故不列入 deps（React refs 本就不需要）。
  //
  // 注意：語言切換（LanguageLayout 的 URL-driven i18n.changeLanguage()）本身「不會」
  // 觸發這段開麥重跑——useAudioStream 的開麥 effect 刻意不依賴 `t`（改用 tRef 讀取
  // 最新翻譯函式），避免單純切換語言就誤觸 closeMic()+openMic() 重置 vadMuteMode。
  // 這段 re-assert 仍保留，作為斷線重連等「真正」需要重開麥克風情境的防線。
  useEffect(() => {
    if (isSessionActiveForMic && (pendingAiUnmuteRef.current || pendingReplayUnmuteRef.current)) {
      muteVAD();
    }
  }, [isSessionActiveForMic, isRecording, muteVAD]);

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
        <div className="flex items-center gap-1">
          {/* #6 靜音切換 */}
          <button
            type="button"
            onClick={handleToggleMute}
            aria-pressed={ttsMuted}
            title={ttsMuted ? t('conversation:tts.unmuteLabel') : t('conversation:tts.muteLabel')}
            aria-label={ttsMuted ? t('conversation:tts.unmuteLabel') : t('conversation:tts.muteLabel')}
            className={`rounded-card p-2 transition-colors ${
              ttsMuted
                ? 'text-alert-critical hover:bg-alert-critical-bg'
                : 'text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary'
            }`}
          >
            {ttsMuted ? (
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M17 9l4 4m0-4l-4 4" />
              </svg>
            ) : (
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072M18.364 5.636a9 9 0 010 12.728" />
              </svg>
            )}
          </button>
          {/* #6 語速循環（靜音時淡化但仍可調，下次出聲生效） */}
          <button
            type="button"
            onClick={cycleSpeed}
            title={t('conversation:tts.speedLabel', { rate: ttsSpeed })}
            aria-label={t('conversation:tts.speedLabel', { rate: ttsSpeed })}
            className={`rounded-card px-2 py-1.5 text-caption font-semibold tabular-nums transition-colors ${
              ttsMuted
                ? 'text-ink-placeholder/50'
                : 'text-ink-secondary hover:bg-surface-tertiary'
            }`}
          >
            {ttsSpeed}x
          </button>
          <button
            className="rounded-btn px-3 py-1.5 text-caption font-medium text-alert-critical hover:bg-alert-critical-bg transition-colors"
            onClick={handleEndSession}
          >
            {t('conversation:endSession')}
          </button>
        </div>
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

      {/* 連線中斷／重連中橫幅（非警示性，持續顯示直到重連成功；附手動重試） */}
      {isConnectionDown && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 border-b border-amber-300 bg-amber-50 px-4 py-2 text-small text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="h-3.5 w-3.5 flex-shrink-0 animate-spin rounded-full border-2 border-amber-400 border-t-transparent dark:border-amber-500 dark:border-t-transparent"
              aria-hidden="true"
            />
            <span className="truncate">
              {t('conversation:connection.reconnecting', '連線中斷，重新連線中…')}
            </span>
          </div>
          <button
            type="button"
            onClick={retry}
            className="flex-shrink-0 rounded-btn bg-amber-100 px-3 py-1 text-caption font-medium text-amber-900 hover:bg-amber-200 transition-colors dark:bg-amber-900/40 dark:text-amber-100 dark:hover:bg-amber-900/60"
          >
            {t('conversation:connection.retry', '重試')}
          </button>
        </div>
      )}

      {/* 錯誤訊息 */}
      {error && (
        <div className="border-b border-alert-critical-border bg-alert-critical-bg px-4 py-2 text-body text-alert-critical-text">
          {error}
        </div>
      )}

      {/* CONV-2：Supervisor 降級提示（非警示性，僅告知問診仍照常進行） */}
      {supervisorDegraded && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 border-b border-edge bg-surface-secondary px-4 py-2 text-small text-ink-secondary dark:bg-dark-card dark:border-dark-border dark:text-slate-300"
        >
          <svg className="h-4 w-4 flex-shrink-0 text-ink-placeholder" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{t('conversation:supervisor.degraded')}</span>
        </div>
      )}

      {/* CONV-2：Supervisor 動態問診指導（輕量提示，僅在有正常指導時顯示） */}
      {supervisorGuidance && !supervisorGuidance.fallback && supervisorGuidance.nextFocus && (
        <div className="flex flex-col gap-1.5 border-b border-edge bg-primary-50/60 px-4 py-2 dark:bg-primary-950/30 dark:border-dark-border">
          <div className="flex items-start gap-2">
            <svg className="h-4 w-4 flex-shrink-0 mt-0.5 text-primary-500 dark:text-primary-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <p className="text-small text-ink-secondary dark:text-slate-300">
              <span className="font-medium text-ink-heading dark:text-slate-100">
                {t('conversation:supervisor.hintLabel')}
              </span>
              <span className="mx-1">·</span>
              {supervisorGuidance.nextFocus}
            </p>
          </div>
          {supervisorGuidance.missingHpi.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pl-6">
              <span className="text-tiny text-ink-placeholder dark:text-slate-400">
                {t('conversation:supervisor.missingLabel')}
              </span>
              {supervisorGuidance.missingHpi.map((dim) => (
                <span
                  key={dim}
                  className="rounded-full bg-white/70 px-2 py-0.5 text-tiny text-ink-secondary dark:bg-black/20 dark:text-slate-300"
                >
                  {t(`conversation:supervisor.hpi.${dim}`, {
                    defaultValue: dim,
                  })}
                </span>
              ))}
            </div>
          )}
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
            voiceOff={ttsMuted}
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
        {/* #6：空辨識提示（系統提示樣式，4 秒自動消失、再開口即收） */}
        {showNoSpeechHint && (
          <div role="status" aria-live="polite" className="mb-3 flex justify-center">
            <span className="animate-slide-down rounded-full bg-amber-100 px-4 py-2 text-caption font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
              {t('conversation:status.noSpeechDetected')}
            </span>
          </div>
        )}
        {/* 麥克風狀態圈 + 手動語音控制（#4） */}
        <div className="flex items-center justify-center gap-4">
          {/* 暫停／繼續收音（醒目：暫停中轉為 amber 實心） */}
          <button
            type="button"
            onClick={handleTogglePause}
            disabled={!isSessionActive}
            aria-pressed={userPaused}
            className={`h-12 rounded-btn px-4 text-body font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              userPaused
                ? 'bg-amber-500 text-white shadow-md hover:bg-amber-600'
                : 'bg-surface-tertiary text-ink-secondary hover:bg-surface-secondary dark:bg-dark-card dark:text-slate-300'
            }`}
          >
            {userPaused ? t('conversation:voiceControl.resume') : t('conversation:voiceControl.pause')}
          </button>

          <div className="relative">
            <div
              className={`flex h-14 w-14 items-center justify-center rounded-full transition-colors ${
                !isSessionActive
                  ? 'bg-surface-tertiary text-ink-placeholder dark:bg-dark-card dark:text-slate-500'
                  : userPaused
                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
                    : isAIResponding
                      ? 'bg-primary-50 text-primary-500 dark:bg-primary-950 dark:text-primary-300'
                      : isRecording
                        ? 'bg-alert-critical text-white shadow-lg shadow-alert-critical/30'
                        : 'bg-primary-50 text-primary-600 dark:bg-primary-950 dark:text-primary-300'
              }`}
            >
              <svg
                className={`h-7 w-7 ${isRecording && !userPaused ? 'animate-pulse' : ''}`}
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
                {/* 暫停：麥克風加斜線 */}
                {userPaused && <path strokeLinecap="round" d="M4 4l16 16" />}
              </svg>
            </div>
            {/* #6：辨識中在麥克風圈疊真 spinner 環（錄音紅色回饋不變） */}
            {sttProcessing && !isAIResponding && !userPaused && (
              <span
                aria-hidden="true"
                className="absolute -inset-1 animate-spin rounded-full border-4 border-primary-400 border-t-transparent"
              />
            )}
          </div>

          {/* 我說完了：講話中才可見（invisible 佔位避免版面跳動），點擊立即送出不等 2 秒靜音 */}
          <button
            type="button"
            onClick={handleFinishSpeaking}
            className={`h-12 rounded-btn bg-primary-600 px-4 text-body font-semibold text-white shadow-md hover:bg-primary-700 transition-colors ${
              isRecording && !userPaused && isSessionActive ? '' : 'invisible'
            }`}
          >
            {t('conversation:voiceControl.finishSpeaking')}
          </button>
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

        {/* 狀態呈現：#4 暫停 / #6 辨識中用醒目徽章，其餘狀態維持小字（Fix 21：ink-secondary 達 WCAG AA） */}
        {userPaused ? (
          <div role="status" aria-live="polite" className="mt-3 flex justify-center">
            <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-4 py-2 text-body font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
              <svg
                className="h-4 w-4 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6" />
              </svg>
              {t('conversation:voiceControl.pausedBanner')}
            </span>
          </div>
        ) : sttProcessing && !isAIResponding ? (
          <div role="status" aria-live="polite" className="mt-3 flex justify-center">
            <span className="inline-flex items-center gap-2 rounded-full bg-primary-50 px-4 py-2 text-body font-medium text-primary-700 dark:bg-primary-950 dark:text-primary-300">
              <span
                aria-hidden="true"
                className="h-4 w-4 animate-spin rounded-full border-2 border-primary-500 border-t-transparent"
              />
              {t('conversation:status.transcribing')}
            </span>
          </div>
        ) : (
          <p className="mt-2 text-center text-small text-ink-secondary dark:text-slate-300">
            {!isSessionActive
              ? t('conversation:status.notStarted')
              : isAIResponding
                ? t('conversation:status.aiResponding')
                : isRecording
                  ? t('conversation:status.listening', { duration: formatDuration(recordingDuration) })
                  : t('conversation:status.idle')}
          </p>
        )}

        {/* 打字輸入備援：語音收不到時可直接打字（送後端 text_message，仍走紅旗篩檢） */}
        {isSessionActive && (
          <form
            className="mt-3 flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              handleSendText();
            }}
          >
            <input
              type="text"
              value={textDraft}
              onChange={(e) => setTextDraft(e.target.value)}
              maxLength={2000}
              placeholder={t('conversation:input.textPlaceholder')}
              aria-label={t('conversation:input.textPlaceholder')}
              className="input-base h-11 flex-1"
            />
            <button
              type="submit"
              disabled={!textDraft.trim() || connectionState !== 'open'}
              className="btn-primary h-11 shrink-0 px-4 text-body disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('conversation:input.send')}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
