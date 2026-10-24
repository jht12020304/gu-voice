// =============================================================================
// 通知 API 服務
// =============================================================================

import apiClient from './client';
import type { Notification, PaginatedResponse } from '../../types';
import type { NotificationListParams, UnreadCountResponse, MarkReadResponse } from '../../types/api';

const BASE = '/notifications';

/** 取得通知列表 */
export async function getNotifications(
  params?: NotificationListParams,
): Promise<PaginatedResponse<Notification> & { unreadCount: number }> {
  const { data } = await apiClient.get<PaginatedResponse<Notification> & { unreadCount: number }>(BASE, { params });
  return data;
}

/** 標記為已讀（後端僅回傳精簡欄位，見 MarkReadResponse） */
export async function markAsRead(id: string): Promise<MarkReadResponse> {
  const { data } = await apiClient.put<MarkReadResponse>(`${BASE}/${id}/read`);
  return data;
}

/** 全部標記為已讀 */
export async function markAllAsRead(): Promise<void> {
  await apiClient.put(`${BASE}/read-all`);
}

/** 取得未讀數量 */
export async function getUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<UnreadCountResponse>(`${BASE}/unread-count`);
  return data.count;
}
