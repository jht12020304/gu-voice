// =============================================================================
// 主訴 API 服務
// =============================================================================

import apiClient from './client';
import type { ChiefComplaint, PaginatedResponse } from '../../types';
import type { ComplaintCreateRequest, ComplaintUpdateRequest, ComplaintReorderRequest } from '../../types/api';

const BASE = '/complaints';

/** 取得主訴列表 */
export async function getComplaints(params?: {
  cursor?: string;
  limit?: number;
  category?: string;
  isActive?: boolean;
}): Promise<PaginatedResponse<ChiefComplaint>> {
  const { data } = await apiClient.get<PaginatedResponse<ChiefComplaint>>(BASE, { params });
  return data;
}

/** 取得單一主訴 */
export async function getComplaint(id: string): Promise<ChiefComplaint> {
  const { data } = await apiClient.get<ChiefComplaint>(`${BASE}/${id}`);
  return data;
}

/** 新增主訴 */
export async function createComplaint(payload: ComplaintCreateRequest): Promise<ChiefComplaint> {
  const { data } = await apiClient.post<ChiefComplaint>(BASE, payload);
  return data;
}

/** 更新主訴 */
export async function updateComplaint(id: string, payload: ComplaintUpdateRequest): Promise<ChiefComplaint> {
  const { data } = await apiClient.put<ChiefComplaint>(`${BASE}/${id}`, payload);
  return data;
}

/** 刪除主訴 */
export async function deleteComplaint(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/${id}`);
}

/** 重新排序主訴 */
export async function reorderComplaints(payload: ComplaintReorderRequest): Promise<void> {
  await apiClient.put(`${BASE}/reorder`, payload);
}
