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
  setError: (error: string | null) => void;
  resetSession: () => void;
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

  setError: (error) => set({ error }),

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
      error: null,
    }),
}));
