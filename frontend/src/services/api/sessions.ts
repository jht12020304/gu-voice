// =============================================================================
// 場次 API 服務
// =============================================================================

import apiClient from './client';
import type { Session, PaginatedResponse, Conversation } from '../../types';
import type { SessionCreateRequest, SessionStatusUpdateRequest, SessionListParams } from '../../types/api';

const BASE = '/sessions';

/** 取得場次列表 */
export async function getSessions(params?: SessionListParams): Promise<PaginatedResponse<Session>> {
  const { data } = await apiClient.get<PaginatedResponse<Session>>(BASE, { params });
  return data;
}

/** 取得單一場次 */
export async function getSession(id: string): Promise<Session> {
  const { data } = await apiClient.get<Session>(`${BASE}/${id}`);
  return data;
}

/** 建立場次 */
export async function createSession(payload: SessionCreateRequest): Promise<Session> {
  const { data } = await apiClient.post<Session>(BASE, payload);
  return data;
}

/** 更新場次狀態 */
export async function updateSessionStatus(
  id: string,
  status: string,
  reason?: string,
): Promise<Session> {
  const { data } = await apiClient.put<Session>(`${BASE}/${id}/status`, {
    status,
    reason,
  } satisfies SessionStatusUpdateRequest);
  return data;
}

/** 取得場次對話紀錄 */
export async function getSessionConversations(
  id: string,
  params?: { cursor?: string; limit?: number },
): Promise<PaginatedResponse<Conversation>> {
  const { data } = await apiClient.get<PaginatedResponse<Conversation>>(
    `${BASE}/${id}/conversations`,
    { params },
  );
  return data;
}

/** 指派醫師 */
export async function assignDoctor(id: string, doctorId: string): Promise<Session> {
  const { data } = await apiClient.post<Session>(`${BASE}/${id}/assign`, { doctorId });
  return data;
}

/** 場次重連恢復回應（對應後端 POST /sessions/{id}/reconnect） */
export interface SessionReconnectResponse {
  sessionId: string;
  status: string;
  /** Redis 內的對話歷史（role + content 等原始 entry） */
  conversationHistory: Array<{ role: string; content: string; [key: string]: unknown }>;
  /** 歷史最後一則的索引；無歷史為 -1 */
  lastMessageIndex: number;
  /** 歷史的 sha256 checksum（== resumeToken），供 WebSocket 重連比對連續性 */
  checksum: string;
  resumeToken: string;
}

/**
 * 場次重連：重新整理／斷線後呼叫，取回 Redis 內的對話歷史與 checksum，
 * 供前端帶著 resumeToken 重建 WebSocket 連線時比對連續性。
 */
export async function reconnectSession(sessionId: string): Promise<SessionReconnectResponse> {
  const { data } = await apiClient.post<SessionReconnectResponse>(`${BASE}/${sessionId}/reconnect`);
  return data;
}

/**
 * M16：對話中切語言 → 結束當前 session，同時把使用者偏好語言更新為 toLanguage。
 * 後端會寫 audit_log (action=language_switch_end_session)。
 * 非 active（waiting/in_progress）狀態會回 409。
 */
export async function endSessionForLanguageSwitch(
  id: string,
  toLanguage: string,
): Promise<{ id: string; status: string; previousStatus?: string; updatedAt: string }> {
  const { data } = await apiClient.post(`${BASE}/${id}/end-for-language-switch`, {
    toLanguage,
  });
  return data;
}
