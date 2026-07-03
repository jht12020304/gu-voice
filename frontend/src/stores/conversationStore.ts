// =============================================================================
// 對話狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { Conversation, Session } from '../types';

/** 聊天訊息（前端用） */
export interface ChatMessage {
  id: string;
  sessionId: string;
  sender: 'patient' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  audioUrl?: string;
  audioDuration?: number;
  sttConfidence?: number;
  isStreaming?: boolean;
  /** Fix 16：該訊息至少有一句 TTS 合成失敗 */
  hasTtsFailure?: boolean;
  /** Fix 18：快取的句級 TTS base64（不含 data URL 前綴），供使用者點擊重播 */
  ttsAudioChunks?: string[];
}

/** CONV-2：Supervisor 動態問診指導（對應後端 supervisor.py 輸出） */
export interface SupervisorGuidance {
  /** 下一步發問建議（單一具體指令） */
  nextFocus: string;
  /** 尚未問到的 HPI 維度 id（snake_case，由後端 HPI_FIELD_IDS 定義） */
  missingHpi: string[];
  /** HPI 十欄整體完整度 0-100 */
  hpiCompletionPercentage: number;
  /** 後端 supervisor 逾時／不可用時回退指導 */
  fallback?: boolean;
}

/** 紅旗事件 */
export interface RedFlagEvent {
  id: string;
  title: string;
  description?: string;
  severity: 'critical' | 'high' | 'medium';
  timestamp: string;
  suggestedActions: string[];
  isAcknowledged: boolean;
}

interface ConversationState {
  currentSession: Session | null;
  conversations: ChatMessage[];
  isRecording: boolean;
  isAIResponding: boolean;
  /** #3：送出 isFinal 後到收到 stt_final 前的「正在辨識」狀態，避免長語音看起來像當機。 */
  sttProcessing: boolean;
  /** #4：使用者手動暫停收音。與 AI 回合硬鎖、斷線 mute 分離；只有「繼續收音」鈕能解除。 */
  userPaused: boolean;
  sttPartialText: string;
  aiStreamingText: string;
  recordingDuration: number;
  audioLevel: number;
  waveformData: number[];
  activeRedFlags: RedFlagEvent[];
  /** CONV-2：最近一次 Supervisor 指導（由後端 supervisor_guidance WS 事件推送） */
  supervisorGuidance: SupervisorGuidance | null;
  /** CONV-2：缺失 HPI 維度（supervisorGuidance.missingHpi 的快捷讀取） */
  missingHpi: string[];
  /** CONV-2：後端 supervisor 降級（逾時／不可用）旗標，由 supervisor_degraded WS 事件設定 */
  supervisorDegraded: boolean;
  error: string | null;
}

interface ConversationActions {
  setCurrentSession: (session: Session | null) => void;
  addConversation: (msg: ChatMessage) => void;
  setConversations: (msgs: ChatMessage[]) => void;
  updateSTTPartial: (text: string) => void;
  setAIResponding: (responding: boolean) => void;
  appendAIStreamingText: (chunk: string) => void;
  finalizeAIResponse: (messageId: string, fullText: string) => void;
  setRecording: (recording: boolean) => void;
  /** #3：設定／清除「正在辨識」狀態。 */
  setSttProcessing: (processing: boolean) => void;
  /** #4：設定使用者手動暫停狀態。 */
  setUserPaused: (paused: boolean) => void;
  setRecordingDuration: (duration: number) => void;
  setAudioLevel: (level: number) => void;
  setWaveformData: (data: number[]) => void;
  addRedFlag: (event: RedFlagEvent) => void;
  acknowledgeRedFlag: (flagId: string) => void;
  /** CONV-2：設定／清除最近一次 Supervisor 指導 */
  setSupervisorGuidance: (guidance: SupervisorGuidance | null) => void;
  /** CONV-2：設定 supervisor 降級旗標 */
  setSupervisorDegraded: (degraded: boolean) => void;
  setError: (error: string | null) => void;
  resetSession: () => void;
  /** Fix 16：標記某則訊息有 TTS 合成失敗 */
  markMessageTtsFailed: (messageId: string) => void;
  /** Fix 18：把一段 TTS base64 附加到指定訊息的 ttsAudioChunks 快取中 */
  appendTtsAudioChunk: (messageId: string, audioB64: string) => void;
}

/**
 * CONV-2：後端 supervisor_guidance WS 事件的原始 payload（snake_case，對齊
 * supervisor.py 輸出 / conversation_handler 寫入 Redis 的欄位）。
 */
export interface SupervisorGuidancePayload {
  next_focus?: string;
  missing_hpi?: string[];
  hpi_completion_percentage?: number;
  fallback?: boolean;
}

/**
 * CONV-2：把後端 snake_case payload 正規化成前端 camelCase 的 SupervisorGuidance。
 * 純函式、無副作用，便於單元測試。
 */
export function normalizeSupervisorGuidance(
  payload: SupervisorGuidancePayload | null | undefined,
): SupervisorGuidance | null {
  if (!payload) return null;
  return {
    nextFocus: payload.next_focus ?? '',
    missingHpi: Array.isArray(payload.missing_hpi) ? payload.missing_hpi : [],
    hpiCompletionPercentage:
      typeof payload.hpi_completion_percentage === 'number'
        ? payload.hpi_completion_percentage
        : 0,
    fallback: payload.fallback ?? false,
  };
}

/**
 * #4：VAD「自動恢復收音」決策矩陣（純函式，無副作用，便於單元測試）。
 * 醫療安全不變式：任何 mute 都必須有對應的 unmute 擁有者（見 ConversationPage 掛點對照），
 * 使用者手動暫停優先於所有自動恢復路徑，且只有「繼續收音」鈕（user_resume）能解除。
 */
export type VadResumeTrigger =
  | 'empty_stt'          // 空 stt_final（Whisper 沒聽出字）
  | 'ai_start_tts_muted' // AI 回合開始且 TTS 靜音（無回授風險，立即開麥）
  | 'ai_tts_done'        // 出聲模式 AI 回合的 TTS 全部播畢（鏈尾步驟 / 舊式 playTTSAudio 結束）
  | 'ws_error'           // 後端 error 事件（rate limit / 音訊格式 / STT 失敗）
  | 'reconnected'        // WS 斷線後重連成功
  | 'tts_mute_toggle'    // 使用者切到 TTS 靜音（停播 + 清佇列後恢復收音）
  | 'user_resume';       // 使用者點「繼續收音」

export interface VadResumeContext {
  /** 使用者手動暫停中 */
  userPaused: boolean;
  /** 出聲模式 AI 回合硬鎖尚未由 TTS 鏈解除（pendingAiUnmuteRef） */
  aiTurnLocked: boolean;
  /** WS 非 open（斷線/重連中，unmute 只會對著死連線收音） */
  wsDown: boolean;
}

export function shouldUnmuteVAD(trigger: VadResumeTrigger, ctx: VadResumeContext): boolean {
  // 重連成功：斷線 mute 的唯一解鎖者，只讓手動暫停擋下（暫停狀態由 _connected 重申給後端）
  if (trigger === 'reconnected') return !ctx.userPaused;
  // 手動繼續：不得在 AI 出聲期間解除硬鎖（回授不變式）；斷線時交給 reconnected 補償
  if (trigger === 'user_resume') return !ctx.aiTurnLocked && !ctx.wsDown;
  // 其餘所有自動恢復路徑：手動暫停優先；斷線時延後到 reconnected
  return !ctx.userPaused && !ctx.wsDown;
}

/** 將後端 Conversation 轉為前端 ChatMessage */
export function conversationToMessage(conv: Conversation): ChatMessage {
  return {
    id: conv.id,
    sessionId: conv.sessionId,
    sender: conv.role,
    content: conv.contentText,
    timestamp: conv.createdAt,
    audioUrl: conv.audioUrl ?? undefined,
    audioDuration: conv.audioDurationSeconds ?? undefined,
    sttConfidence: conv.sttConfidence ?? undefined,
  };
}

export const useConversationStore = create<ConversationState & ConversationActions>((set) => ({
  // ---- State ----
  currentSession: null,
  conversations: [],
  isRecording: false,
  isAIResponding: false,
  sttProcessing: false,
  userPaused: false,
  sttPartialText: '',
  aiStreamingText: '',
  recordingDuration: 0,
  audioLevel: 0,
  waveformData: [],
  activeRedFlags: [],
  supervisorGuidance: null,
  missingHpi: [],
  supervisorDegraded: false,
  error: null,

  // ---- Actions ----

  setCurrentSession: (session) => set({ currentSession: session }),

  addConversation: (msg) =>
    set((state) => ({
      conversations: [...state.conversations, msg],
    })),

  setConversations: (msgs) => set({ conversations: msgs }),

  updateSTTPartial: (text) => set({ sttPartialText: text }),

  setAIResponding: (responding) =>
    set({ isAIResponding: responding, aiStreamingText: responding ? '' : '' }),

  appendAIStreamingText: (chunk) =>
    set((state) => ({ aiStreamingText: state.aiStreamingText + chunk })),

  finalizeAIResponse: (messageId, fullText) =>
    set((state) => ({
      isAIResponding: false,
      aiStreamingText: '',
      conversations: state.conversations.map((msg) =>
        msg.id === messageId ? { ...msg, content: fullText, isStreaming: false } : msg,
      ),
    })),

  setRecording: (recording) => set({ isRecording: recording }),
  setSttProcessing: (processing) => set({ sttProcessing: processing }),
  setUserPaused: (paused) => set({ userPaused: paused }),
  setRecordingDuration: (duration) => set({ recordingDuration: duration }),
  setAudioLevel: (level) => set({ audioLevel: level }),
  setWaveformData: (data) => set({ waveformData: data }),

  addRedFlag: (event) =>
    set((state) => ({
      activeRedFlags: [...state.activeRedFlags, event],
    })),

  acknowledgeRedFlag: (flagId) =>
    set((state) => ({
      activeRedFlags: state.activeRedFlags.map((f) =>
        f.id === flagId ? { ...f, isAcknowledged: true } : f,
      ),
    })),

  setSupervisorGuidance: (guidance) =>
    set({
      supervisorGuidance: guidance,
      missingHpi: guidance?.missingHpi ?? [],
      // 收到一份非 fallback 的正常指導 → 視為已恢復，清除降級旗標。
      supervisorDegraded: guidance?.fallback ?? false,
    }),

  setSupervisorDegraded: (degraded) => set({ supervisorDegraded: degraded }),

  setError: (error) => set({ error }),

  markMessageTtsFailed: (messageId) =>
    set((state) => ({
      conversations: state.conversations.map((msg) =>
        msg.id === messageId ? { ...msg, hasTtsFailure: true } : msg,
      ),
    })),

  appendTtsAudioChunk: (messageId, audioB64) =>
    set((state) => ({
      conversations: state.conversations.map((msg) =>
        msg.id === messageId
          ? { ...msg, ttsAudioChunks: [...(msg.ttsAudioChunks ?? []), audioB64] }
          : msg,
      ),
    })),

  resetSession: () =>
    set({
      currentSession: null,
      conversations: [],
      isRecording: false,
      isAIResponding: false,
      sttProcessing: false,
      userPaused: false,
      sttPartialText: '',
      aiStreamingText: '',
      recordingDuration: 0,
      audioLevel: 0,
      waveformData: [],
      activeRedFlags: [],
      supervisorGuidance: null,
      missingHpi: [],
      supervisorDegraded: false,
      error: null,
    }),
}));
