// =============================================================================
// 儀表板 API 服務
// =============================================================================

import apiClient from './client';
import type { DashboardStatsResponse, DashboardQueueResponse } from '../../types/api';
import type { RedFlagAlert, Session } from '../../types';

const BASE = '/dashboard';

/** 取得儀表板統計 */
export async function getDashboardStats(): Promise<DashboardStatsResponse> {
  const { data } = await apiClient.get<DashboardStatsResponse>(`${BASE}/stats`);
  return data;
}

/** 取得病患排隊列表 */
export async function getDashboardQueue(): Promise<DashboardQueueResponse> {
  const { data } = await apiClient.get<DashboardQueueResponse>(`${BASE}/queue`);
  return data;
}

/** 取得最近紅旗警示 */
export async function getRecentAlerts(): Promise<RedFlagAlert[]> {
  const { data } = await apiClient.get<RedFlagAlert[]>(`${BASE}/recent-alerts`);
  return data;
}

/** 取得最近場次 */
export async function getRecentSessions(): Promise<Session[]> {
  const { data } = await apiClient.get<Session[]>(`${BASE}/recent-sessions`);
  return data;
}
