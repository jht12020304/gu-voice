// =============================================================================
// 紅旗警示 API 服務
// =============================================================================

import apiClient from './client';
import type { RedFlagAlert, PaginatedResponse } from '../../types';
import type { AlertAcknowledgeRequest, AlertListParams } from '../../types/api';

const BASE = '/alerts';

/**
 * 確認警示請求 payload。
 * 後端 `AlertAcknowledgeRequest` 同時接受 `acknowledge_notes`（備註）與
 * `action_taken`（醫師實際處置，稽核軌跡，會持久化到 red_flag_alerts.action_taken）。
 * client 攔截器會把 camelCase 自動轉成 snake_case，故此處用 camelCase 欄位即可。
 */
export interface AcknowledgeAlertPayload extends AlertAcknowledgeRequest {
  /** 醫師對此警示採取的實際處置 */
  actionTaken?: string;
}

/** 取得警示列表 */
export async function getAlerts(params?: AlertListParams): Promise<PaginatedResponse<RedFlagAlert>> {
  const { data } = await apiClient.get<PaginatedResponse<RedFlagAlert>>(BASE, { params });
  return data;
}

/** 取得單一警示 */
export async function getAlert(id: string): Promise<RedFlagAlert> {
  const { data } = await apiClient.get<RedFlagAlert>(`${BASE}/${id}`);
  return data;
}

/** 確認警示 */
export async function acknowledgeAlert(
  id: string,
  payload?: AcknowledgeAlertPayload,
): Promise<RedFlagAlert> {
  const { data } = await apiClient.post<RedFlagAlert>(`${BASE}/${id}/acknowledge`, payload ?? {});
  return data;
}

/** 取得未確認警示數量 */
export async function getUnacknowledgedCount(): Promise<number> {
  const { data } = await apiClient.get<{ count: number }>(`${BASE}/unacknowledged/count`);
  return data.count;
}
