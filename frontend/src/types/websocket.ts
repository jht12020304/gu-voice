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
  /**
   * STT 信心分數（0~1）：後端由 Whisper verbose_json segments 的 avg_logprob
   * 估算（幾何平均 token 機率）；segments 缺失時後端「不帶此鍵」（undefined），
   * UI 據 undefined 隱藏百分比——不要送 null（會被渲染成 0%）。
   */
  confidence?: number;
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

/**
 * 病患端 red_flag_alert payload。
 *
 * ⚠️ 刻意**不含** `description` / `suggestedActions`：那兩個欄位是 LLM 自由生成的
 * 醫師向臨床內容（真跑實測 suggestedActions 出現過「立即安排急診評估」），違反
 * 院內候診 kiosk 的措辭鐵律。後端自 2026-07-27 起在
 * `conversation_handler._persist_and_emit_alert` 就**根本不送**給病患端；醫師端
 * （dashboard 廣播）與 DB 仍保留完整內容，資訊沒有變少。
 *
 * 型別要與實際 payload 一致——先前宣告這兩欄為必填，型別在說謊，會誘導下一個人
 * 「既然型別有就讀來用」而把醫師向文字弄回病患畫面。
 */
export interface RedFlagAlertPayload {
  alertId: string;
  severity: 'critical' | 'high' | 'medium';
  title: string;
  /**
   * 後端依「這則紅旗有沒有真的建立醫師通知」二選一的在地化病患指引
   * （ws.red_flag_patient_notice_notified / _flagged）。前端不得自行拼裝這句話：
   * 有沒有通知到醫師只有後端知道，前端自己講就會對病患說謊。
   * 舊後端不送此欄，故為 optional；缺席時前端退回保守版的本地 fallback。
   */
  patientNotice?: string;
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
