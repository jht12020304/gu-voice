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
  /**
   * L-19：MediaRecorder 實際輸出的 MIME（webm/mp4 等）。
   * 後端不信任此欄位（以 magic bytes 嗅探實際容器格式），此處僅回報真實 MIME
   * 供除錯／記錄；切勿再硬填 'wav'，避免與實際容器不符造成誤導。
   */
  format: string;
  sampleRate: number;
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
  /** Fix 16（Option B）：後端在同一個 chunk payload 中標記 TTS 合成失敗 */
  ttsFailed?: boolean;
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

/**
 * TODO-E2: session_status 已改為 canonical code 契約。
 * 後端送 `{code, params, severity}`，前端用 `t(code, params, {ns:'ws'})` 渲染。
 * sessionId / status / previousStatus 由 `broadcast_localized_dashboard` 的 extra 帶入。
 */
export interface SessionStatusPayload {
  /** Canonical i18n code，例：events.session.ended_by_user */
  code: string;
  params?: Record<string, unknown>;
  severity?: 'info' | 'warning' | 'error' | 'critical';
  sessionId?: string;
  status?: string;
  previousStatus?: string;
}

/**
 * TODO-E2: error payload 也改為 canonical code 契約。
 * 前端收到 `{code, params, severity}` 後透過 `t(code, params, {ns:'ws'})` 渲染。
 */
export interface WSErrorPayload {
  code: string;
  params?: Record<string, unknown>;
  severity?: 'info' | 'warning' | 'error' | 'critical';
}

export interface PongPayload {
  serverTime: string;
}

export type ServerMessageType =
  | 'connection_ack'
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

/**
 * M-17：連線時後端送出的初始快照（dashboard_handler `_build_initial_state`）。
 *
 * 注意：與 `queue_updated` / `stats_updated`（camelCase）不同，此事件的 payload 為
 * **snake_case** 線格式（後端直接序列化 `_get_queue_status` / `_get_dashboard_stats`），
 * 因此這裡如實標註 snake_case 欄位，消費端負責轉成 camelCase 後再 patch 狀態。
 */
export interface InitialStatePayload {
  queue: {
    total_waiting: number;
    total_in_progress: number;
    queue: Array<{
      session_id: string;
      status: string;
      chief_complaint: string;
      created_at: string | null;
    }>;
  };
  active_alerts: Array<{
    alert_id: string;
    session_id: string | null;
    severity: 'critical' | 'high' | 'medium';
    title: string;
    description: string;
    created_at: string | null;
  }>;
  stats: {
    sessions_today: number;
    completed: number;
    red_flags: number;
    pending_reviews: number;
  };
  connected_at: string;
}

export type DashboardEventType =
  | 'initial_state'
  | 'session_created'
  | 'session_status_changed'
  | 'new_red_flag'
  | 'red_flag_acknowledged'
  | 'report_generated'
  | 'queue_updated'
  | 'stats_updated';
