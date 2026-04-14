// =============================================================================
// WebSocket 訊息型別
// =============================================================================

/** 通用 WebSocket 訊息信封 */
export interface WSMessage<T = unknown> {
  type: string;
  id: string;
  timestamp: string;
  payload: T;
}

// =============================================================================
// Client -> Server 訊息
// =============================================================================

export interface AudioChunkPayload {
  audioData: string; // base64
  chunkIndex: number;
  isFinal: boolean;
  format: 'wav';
  sampleRate: number;
}

export interface TextMessagePayload {
  text: string;
}

export interface ControlPayload {
  action: 'end_session' | 'pause_recording' | 'resume_recording';
}

export interface PingPayload {
  // 空物件
}

export type ClientMessageType = 'audio_chunk' | 'text_message' | 'control' | 'ping';

// =============================================================================
// Server -> Client 訊息
// =============================================================================

export interface ConnectionAckPayload {
  sessionId: string;
  status: string;
  config: {
    audioFormat: string;
    sampleRate: number;
    maxChunkSizeBytes: number;
  };
}

export interface STTPartialPayload {
  text: string;
  confidence: number;
  isFinal: false;
}

export interface STTFinalPayload {
  messageId: string;
  text: string;
  confidence: number;
  isFinal: true;
}

export interface AIResponseStartPayload {
  messageId: string;
}

export interface AIResponseChunkPayload {
  messageId: string;
  text: string;
  chunkIndex: number;
  /** 句級 base64 音訊（mp3）。若為空字串代表此句無對應音訊。 */
  audioB64?: string;
}

export interface AIResponseEndPayload {
  messageId: string;
  fullText: string;
  ttsAudioUrl: string;
}

export interface RedFlagAlertPayload {
  alertId: string;
  severity: 'critical' | 'high' | 'medium';
  title: string;
  description: string;
  suggestedActions: string[];
}

export interface SessionStatusPayload {
  sessionId: string;
  status: string;
  previousStatus: string;
  reason?: string;
}

export interface WSErrorPayload {
  code: string;
  message: string;
}

export interface PongPayload {
  serverTime: string;
}

export type ServerMessageType =
  | 'connection_ack'
  | 'stt_partial'
  | 'stt_final'
  | 'ai_response_start'
  | 'ai_response_chunk'
  | 'ai_response_end'
  | 'red_flag_alert'
  | 'session_status'
  | 'error'
  | 'pong';

// =============================================================================
// 儀表板 WebSocket 事件
// =============================================================================

export interface SessionCreatedPayload {
  sessionId: string;
  patientName: string;
  chiefComplaint: string;
  status: string;
}

export interface SessionStatusChangedPayload {
  sessionId: string;
  status: string;
  previousStatus: string;
  reason?: string;
}

export interface NewRedFlagPayload {
  alertId: string;
  sessionId: string;
  patientName: string;
  severity: 'critical' | 'high' | 'medium';
  title: string;
  description: string;
}

export interface RedFlagAcknowledgedPayload {
  alertId: string;
  acknowledgedBy: string;
}

export interface ReportGeneratedPayload {
  reportId: string;
  sessionId: string;
  patientName: string;
  status: string;
}

export interface QueueUpdatedPayload {
  totalWaiting: number;
  totalInProgress: number;
  queue: Array<{
    sessionId: string;
    patientName: string;
    chiefComplaint: string;
    status: string;
    waitingSeconds: number;
  }>;
}

export interface StatsUpdatedPayload {
  sessionsToday: number;
  completed: number;
  redFlags: number;
  pendingReviews: number;
}

export type DashboardEventType =
  | 'session_created'
  | 'session_status_changed'
  | 'new_red_flag'
  | 'red_flag_acknowledged'
  | 'report_generated'
  | 'queue_updated'
  | 'stats_updated';
