// =============================================================================
// 儀表板 API 服務
// =============================================================================

import apiClient from './client';
import type {
  DashboardQueueResponse,
  DashboardStatsResponse,
  MonthlySummaryResponse,
  RecentAlertsResponse,
  RecentSessionsResponse,
} from '../../types/api';

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

/** 取得月份摘要 */
export async function getMonthlySummary(month?: string): Promise<MonthlySummaryResponse> {
  const { data } = await apiClient.get<MonthlySummaryResponse>(`${BASE}/monthly-summary`, {
    params: month ? { month } : undefined,
  });
  return data;
}

/** 取得最近紅旗警示 */
export async function getRecentAlerts(): Promise<RecentAlertsResponse> {
  const { data } = await apiClient.get<RecentAlertsResponse>(`${BASE}/recent-alerts`);
  return data;
}

/** 取得最近場次 */
export async function getRecentSessions(): Promise<RecentSessionsResponse> {
  const { data } = await apiClient.get<RecentSessionsResponse>(`${BASE}/recent-sessions`);
  return data;
}
