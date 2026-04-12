// =============================================================================
// 紅旗警示 API 服務
// =============================================================================

import apiClient from './client';
import type { RedFlagAlert, PaginatedResponse } from '../../types';
import type { AlertAcknowledgeRequest, AlertListParams } from '../../types/api';

const BASE = '/alerts';

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
  payload?: AlertAcknowledgeRequest,
): Promise<RedFlagAlert> {
  const { data } = await apiClient.post<RedFlagAlert>(`${BASE}/${id}/acknowledge`, payload ?? {});
  return data;
}

/** 取得未確認警示數量 */
export async function getUnacknowledgedCount(): Promise<number> {
  const { data } = await apiClient.get<{ count: number }>(`${BASE}/unacknowledged/count`);
  return data.count;
}
