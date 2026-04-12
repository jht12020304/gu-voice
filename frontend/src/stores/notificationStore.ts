// =============================================================================
// 通知狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { Notification } from '../types';
import * as notificationsApi from '../services/api/notifications';

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  cursor: string | null;
  hasMore: boolean;
  error: string | null;
}

interface NotificationActions {
  fetchNotifications: (reset?: boolean) => Promise<void>;
  fetchMore: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  fetchUnreadCount: () => Promise<void>;
  clearError: () => void;
}

export const useNotificationStore = create<NotificationState & NotificationActions>((set, get) => ({
  // ---- State ----
  notifications: [],
  unreadCount: 0,
  isLoading: false,
  cursor: null,
  hasMore: true,
  error: null,

  // ---- Actions ----

  fetchNotifications: async (reset = true) => {
    set({ isLoading: true, error: null });
    if (reset) set({ cursor: null, notifications: [] });

    try {
      const response = await notificationsApi.getNotifications({ limit: 20 });
      set({
        notifications: response.data,
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入通知' });
    }
  },

  fetchMore: async () => {
    const { cursor, hasMore, isLoading, notifications } = get();
    if (!hasMore || isLoading || !cursor) return;

    set({ isLoading: true });
    try {
      const response = await notificationsApi.getNotifications({ cursor, limit: 20 });
      set({
        notifications: [...notifications, ...response.data],
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入更多' });
    }
  },

  markRead: async (id) => {
    try {
      await notificationsApi.markAsRead(id);
      set((state) => ({
        notifications: state.notifications.map((n) =>
          n.id === id ? { ...n, isRead: true, readAt: new Date().toISOString() } : n,
        ),
        unreadCount: Math.max(0, state.unreadCount - 1),
      }));
    } catch {
      // 靜默失敗
    }
  },

  markAllRead: async () => {
    try {
      await notificationsApi.markAllAsRead();
      set((state) => ({
        notifications: state.notifications.map((n) => ({
          ...n,
          isRead: true,
          readAt: n.readAt ?? new Date().toISOString(),
        })),
        unreadCount: 0,
      }));
    } catch {
      set({ error: '標記全部已讀失敗' });
    }
  },

  fetchUnreadCount: async () => {
    try {
      const count = await notificationsApi.getUnreadCount();
      set({ unreadCount: count });
    } catch {
      // 靜默失敗
    }
  },

  clearError: () => set({ error: null }),
}));
