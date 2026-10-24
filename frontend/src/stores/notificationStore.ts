import { create } from 'zustand';
import i18n from '../i18n';
import type { Notification } from '../types';
import * as notificationsApi from '../services/api/notifications';
import { useAuthStore } from './authStore';
import { apiErrorMessage, getAuthEpoch } from '../services/api/client';

let listRequest = 0;
let countRequest = 0;
let readVersion = 0;
const pendingReads = new Set<string>();
interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  loaded: boolean;
  isLoading: boolean;
  cursor: string | null;
  hasMore: boolean;
  error: string | null;
  fetchNotifications: (reset?: boolean) => Promise<void>;
  fetchMore: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  fetchUnreadCount: () => Promise<void>;
  clearError: () => void;
}
export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [], unreadCount: 0, loaded: false, isLoading: false,
  cursor: null, hasMore: true, error: null,
  fetchNotifications: async (reset = true) => {
    const request = ++listRequest;
    const epoch = getAuthEpoch();
    const reads = readVersion;
    ++countRequest;
    set({ isLoading: true, error: null });
    try {
      const response = await notificationsApi.getNotifications({ limit: 20 });
      if (epoch !== getAuthEpoch() || request !== listRequest) return;
      const existing = get();
      const rows = response.data.map((n) => pendingReads.has(n.id)
        || (reads !== readVersion && existing.notifications.some((old) => old.id === n.id && old.isRead))
        ? { ...n, isRead: true } : n);
      const ids = new Set(rows.map((n) => n.id));
      set({
        loaded: true,
        ...(reads === readVersion && pendingReads.size === 0 ? { unreadCount: response.unreadCount } : {}),
        notifications: reset ? rows : [...rows, ...existing.notifications.filter((n) => !ids.has(n.id))],
        cursor: !reset && existing.notifications.length > 20 ? existing.cursor : response.pagination.nextCursor,
        hasMore: !reset && existing.notifications.length > 20 ? existing.hasMore : response.pagination.hasMore,
        isLoading: false,
      });
    } catch (err) {
      if (epoch === getAuthEpoch() && request === listRequest) set({ isLoading: false, error: apiErrorMessage(err, i18n.t, '無法載入通知') });
    }
  },
  fetchMore: async () => {
    const { cursor, hasMore, isLoading } = get();
    if (!hasMore || isLoading || !cursor) return;
    const request = ++listRequest;
    const epoch = getAuthEpoch();
    set({ isLoading: true });
    try {
      const response = await notificationsApi.getNotifications({ cursor, limit: 20 });
      if (epoch !== getAuthEpoch() || request !== listRequest) return;
      const current = get().notifications;
      const ids = new Set(current.map((n) => n.id));
      set({
        notifications: [...current, ...response.data.filter((n) => !ids.has(n.id)).map((n) => pendingReads.has(n.id) ? { ...n, isRead: true } : n)],
        cursor: response.pagination.nextCursor, hasMore: response.pagination.hasMore, isLoading: false,
      });
    } catch (err) {
      if (epoch === getAuthEpoch() && request === listRequest) set({ isLoading: false, error: apiErrorMessage(err, i18n.t, '無法載入更多') });
    }
  },
  markRead: async (id) => {
    const original = get().notifications.find((n) => n.id === id);
    if (!original || original.isRead || pendingReads.has(id)) return;
    const epoch = getAuthEpoch();
    const version = ++readVersion;
    ++countRequest;
    pendingReads.add(id);
    set((state) => ({
      notifications: state.notifications.map((n) => n.id === id ? { ...n, isRead: true } : n),
      unreadCount: Math.max(0, state.unreadCount - 1),
    }));
    try {
      await notificationsApi.markAsRead(id);
    } catch {
      if (epoch !== getAuthEpoch()) return;
      if (version === readVersion && original) {
        set((state) => ({ notifications: state.notifications.map((n) => n.id === id ? original : n) }));
      }
      pendingReads.delete(id);
      await get().fetchNotifications(false);
      if (epoch === getAuthEpoch()) set({ error: '標記已讀失敗' });
    } finally {
      if (epoch === getAuthEpoch()) {
        ++readVersion;
        pendingReads.delete(id);
        if (pendingReads.size === 0) void get().fetchUnreadCount();
      }
    }
  },
  markAllRead: async () => {
    const epoch = getAuthEpoch();
    ++readVersion; ++countRequest;
    try {
      await notificationsApi.markAllAsRead();
      if (epoch !== getAuthEpoch()) return;
      set((state) => ({
        notifications: state.notifications.map((n) => ({ ...n, isRead: true, readAt: n.readAt ?? new Date().toISOString() })),
        unreadCount: 0,
      }));
    } catch (err) {
      if (epoch === getAuthEpoch()) set({ error: apiErrorMessage(err, i18n.t, '標記全部已讀失敗') });
    }
  },
  fetchUnreadCount: async () => {
    const request = ++countRequest;
    const epoch = getAuthEpoch();
    try {
      const count = await notificationsApi.getUnreadCount();
      if (epoch === getAuthEpoch() && request === countRequest && pendingReads.size === 0) set({ unreadCount: count });
    } catch { /* Keep the last known count during outages. */ }
  },
  clearError: () => set({ error: null }),
}));

useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    ++listRequest; ++countRequest; ++readVersion;
    pendingReads.clear();
    useNotificationStore.setState(useNotificationStore.getInitialState());
  }
});
