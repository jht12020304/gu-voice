// =============================================================================
// SOAP 報告 API 服務
// =============================================================================

import apiClient from './client';
import type { SOAPReport, PaginatedResponse } from '../../types';
import type { ReviewRequest, ReportListParams } from '../../types/api';

const BASE = '/reports';

/** 取得報告列表 */
export async function getReports(params?: ReportListParams): Promise<PaginatedResponse<SOAPReport>> {
  const { data } = await apiClient.get<PaginatedResponse<SOAPReport>>(BASE, { params });
  return data;
}

/** 取得單一報告 */
export async function getReport(id: string): Promise<SOAPReport> {
  const { data } = await apiClient.get<SOAPReport>(`${BASE}/${id}`);
  return data;
}

/** 依場次取得報告（含完整 S/O/A/P 內容） */
export async function getReportBySession(sessionId: string): Promise<SOAPReport> {
  // 1. 從列表取得報告 ID
  const { data } = await apiClient.get<PaginatedResponse<SOAPReport>>(BASE, {
    params: { sessionId, limit: 1 },
  });
  if (data.data.length === 0) throw new Error('Report not found');
  // 2. 用 ID 取得含完整 S/O/A/P 的詳細報告
  return await getReport(data.data[0].id);
}

/** 產生報告（觸發 AI 生成） */
export async function generateReport(sessionId: string): Promise<SOAPReport> {
  const { data } = await apiClient.post<SOAPReport>(`/sessions/${sessionId}/reports/generate`);
  return data;
}

/** 審閱報告 */
export async function reviewReport(id: string, payload: ReviewRequest): Promise<SOAPReport> {
  const { data } = await apiClient.put<SOAPReport>(`${BASE}/${id}/review`, payload);
  return data;
}

/** 匯出 PDF */
export async function exportReportPDF(id: string): Promise<Blob> {
  const { data } = await apiClient.get(`${BASE}/${id}/pdf`, {
    responseType: 'blob',
  });
  return data;
}
