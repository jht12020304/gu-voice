// =============================================================================
// WebSocket canonical payload types（TODO-E2）
// 與 backend/app/schemas/ws_message.py 的 `WSMessage` 一對一。
//
// 使用方式：
//   import type { WSLocalizedPayload } from '@/services/ws/types';
//   t(payload.code, payload.params)   // i18next 會自動綁 ns='ws'
// =============================================================================

export type WSSeverity = 'info' | 'warning' | 'error' | 'critical';

/** 可本地化的 WS 訊息 body（嵌在 WSMessage.payload 內）。 */
export interface WSLocalizedPayload {
  /** Dot-namespaced 訊息代碼，例：errors.ws.invalid_token / events.session.red_flag_triggered */
  code: string;
  /** 給 i18next t(code, params) 的插值。 */
  params?: Record<string, unknown>;
  /** 提示嚴重度（影響前端呈現樣式）。 */
  severity?: WSSeverity;
}

/**
 * Dashboard 廣播可夾帶的額外結構欄位（非本地化）。
 * 例：session_status_changed 會額外帶 sessionId / status / previousStatus。
 */
export interface WSLocalizedDashboardPayload extends WSLocalizedPayload {
  sessionId?: string;
  status?: string;
  previousStatus?: string;
  [key: string]: unknown;
}

/**
 * 判斷某 payload 是否為 canonical code 契約（避免跟舊 {message} 型別混淆）。
 * 切換期間可用來降噪/fallback：兩種 payload 都會經過 WebSocketManager。
 */
export function isWSLocalizedPayload(
  payload: unknown,
): payload is WSLocalizedPayload {
  if (!payload || typeof payload !== 'object') return false;
  const p = payload as Record<string, unknown>;
  return typeof p.code === 'string' && p.code.length > 0;
}
