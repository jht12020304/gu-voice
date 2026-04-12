// =============================================================================
// 通知 API 服務
// =============================================================================

import apiClient from './client';
import type { Notification, PaginatedResponse } from '../../types';
import type { NotificationListParams, UnreadCountResponse } from '../../types/api';

const BASE = '/notifications';

/** 取得通知列表 */
export async function getNotifications(
  params?: NotificationListParams,
): Promise<PaginatedResponse<Notification>> {
  const { data } = await apiClient.get<PaginatedResponse<Notification>>(BASE, { params });
  return data;
}

/** 標記為已讀 */
export async function markAsRead(id: string): Promise<Notification> {
  const { data } = await apiClient.put<Notification>(`${BASE}/${id}/read`);
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
