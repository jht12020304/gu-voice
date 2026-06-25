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
