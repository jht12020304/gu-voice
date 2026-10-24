// =============================================================================
// 儀表板 API 服務
// =============================================================================

import apiClient from './client';
import type { MonthlySummaryResponse } from '../../types/api';

const BASE = '/dashboard';

/** 取得月份摘要 */
export async function getMonthlySummary(month?: string): Promise<MonthlySummaryResponse> {
  const { data } = await apiClient.get<MonthlySummaryResponse>(`${BASE}/monthly-summary`, {
    params: month ? { month } : undefined,
  });
  return data;
}
