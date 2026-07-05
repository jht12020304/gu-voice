// =============================================================================
// 研究分析 API 服務
// =============================================================================

import apiClient from './client';
import type { ResearchAnalyticsResponse } from '../../types/api';

const BASE = '/research';

/** 取得研究分析聚合指標（可選收案日期區間，含當日） */
export async function getResearchAnalytics(params?: {
  dateFrom?: string;
  dateTo?: string;
}): Promise<ResearchAnalyticsResponse> {
  const { data } = await apiClient.get<ResearchAnalyticsResponse>(`${BASE}/analytics`, {
    params: {
      ...(params?.dateFrom ? { date_from: params.dateFrom } : {}),
      ...(params?.dateTo ? { date_to: params.dateTo } : {}),
    },
  });
  return data;
}
