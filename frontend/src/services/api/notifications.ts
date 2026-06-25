// =============================================================================
// 通知 API 服務
// =============================================================================

import apiClient from './client';
import type { Notification, PaginatedResponse } from '../../types';
import type {
  NotificationListParams,
  UnreadCountResponse,
  MarkReadResponse,
  NotificationPreference,
  NotificationPreferenceUpdate,
  FcmTokenCreateRequest,
  FcmTokenResponse,
} from '../../types/api';

const BASE = '/notifications';

/** 取得通知列表 */
export async function getNotifications(
  params?: NotificationListParams,
): Promise<PaginatedResponse<Notification>> {
  const { data } = await apiClient.get<PaginatedResponse<Notification>>(BASE, { params });
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

// ---- 通知偏好（GDPR opt-out）----

/** 取得通知偏好 */
export async function getNotificationPreferences(): Promise<NotificationPreference> {
  const { data } = await apiClient.get<NotificationPreference>(`${BASE}/preferences`);
  return data;
}

/** 更新通知偏好（red_flag 為病安關鍵，後端恆為開） */
export async function updateNotificationPreferences(
  payload: NotificationPreferenceUpdate,
): Promise<NotificationPreference> {
  const { data } = await apiClient.put<NotificationPreference>(`${BASE}/preferences`, payload);
  return data;
}

// ---- FCM 推播 Token ----

/** 註冊或更新 FCM 裝置 Token */
export async function registerFcmToken(
  payload: FcmTokenCreateRequest,
): Promise<FcmTokenResponse> {
  const { data } = await apiClient.post<FcmTokenResponse>(`${BASE}/fcm-token`, payload);
  return data;
}

/** 移除 FCM 裝置 Token（token 置於路徑） */
export async function deleteFcmToken(token: string): Promise<void> {
  await apiClient.delete(`${BASE}/fcm-token/${encodeURIComponent(token)}`);
}
