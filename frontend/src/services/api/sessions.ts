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
