// =============================================================================
// 紅旗警示狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { RedFlagAlert } from '../types';
import * as alertsApi from '../services/api/alerts';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockAlerts: RedFlagAlert[] = [
  { id: 'a1', sessionId: 's1', conversationId: 'c1', alertType: 'combined', severity: 'critical', title: '疑似睪丸扭轉', description: '病患描述突發性單側陰囊劇痛伴噁心嘔吐，6小時內需手術介入', triggerReason: '關鍵字+語意分析', suggestedActions: ['緊急泌尿外科會診', '安排緊急超音波', '通知手術室'], createdAt: '2026-04-10T13:45:00Z' },
  { id: 'a2', sessionId: 's4', conversationId: 'c2', alertType: 'rule_based', severity: 'high', title: '疑似腎絞痛', description: '左側腰痛放射至鼠蹊部，伴隨噁心、血尿，疑似泌尿道結石', triggerReason: '關鍵字匹配', triggerKeywords: ['腰痛', '血尿', '鼠蹊部'], suggestedActions: ['安排腎臟超音波', '安排KUB X光', '止痛處置'], createdAt: '2026-04-10T13:30:00Z' },
  { id: 'a3', sessionId: 's1', conversationId: 'c3', alertType: 'semantic', severity: 'medium', title: '肉眼血尿持續', description: '血尿已持續三天，需排除膀胱腫瘤可能性', triggerReason: '語意分析', suggestedActions: ['安排膀胱鏡檢查', '尿液細胞學檢查'], createdAt: '2026-04-10T13:15:00Z' },
  { id: 'a4', sessionId: 's2', conversationId: 'c4', alertType: 'rule_based', severity: 'high', title: '反覆泌尿道感染', description: '近半年第四次泌尿道感染，需排除結構性異常', triggerReason: '關鍵字匹配', triggerKeywords: ['反覆感染', '泌尿道'], suggestedActions: ['安排影像學檢查', '尿液培養'], createdAt: '2026-04-10T12:00:00Z' },
  { id: 'a5', sessionId: 's3', conversationId: 'c5', alertType: 'semantic', severity: 'medium', title: 'PSA 指數偏高', description: 'PSA 8.5 ng/mL，需進一步評估攝護腺癌風險', triggerReason: '語意分析', suggestedActions: ['安排攝護腺切片', 'Free PSA 比值'], acknowledgedBy: 'mock-doctor-001', acknowledgedAt: '2026-04-10T12:30:00Z', acknowledgeNotes: '已安排下週切片', createdAt: '2026-04-10T11:00:00Z' },
];

interface AlertState {
  alerts: RedFlagAlert[];
  unacknowledgedCount: number;
  totalCount: number;
  allTotalCount: number;
  isLoading: boolean;
  cursor: string | null;
  hasMore: boolean;
  filter: 'all' | 'unacknowledged' | 'acknowledged';
  error: string | null;
}

interface AlertActions {
  fetchAlerts: (reset?: boolean) => Promise<void>;
  fetchMore: () => Promise<void>;
  acknowledgeAlert: (id: string, notes?: string) => Promise<void>;
  addNewAlert: (alert: RedFlagAlert) => void;
  setFilter: (filter: 'all' | 'unacknowledged' | 'acknowledged') => void;
  fetchUnacknowledgedCount: () => Promise<void>;
  clearError: () => void;
}

export const useAlertStore = create<AlertState & AlertActions>((set, get) => ({
  // ---- State ----
  alerts: [],
  unacknowledgedCount: 0,
  totalCount: 0,
  allTotalCount: 0,
  isLoading: false,
  cursor: null,
  hasMore: true,
  filter: 'all',
  error: null,

  // ---- Actions ----

  fetchAlerts: async (reset = true) => {
    if (IS_MOCK) {
      const { filter } = get();
      const filtered = filter === 'all' ? mockAlerts
        : filter === 'acknowledged' ? mockAlerts.filter((a) => !!a.acknowledgedBy)
        : mockAlerts.filter((a) => !a.acknowledgedBy);
      set({
        alerts: filtered,
        isLoading: false,
        hasMore: false,
        cursor: null,
        totalCount: filtered.length,
        allTotalCount: mockAlerts.length,
        unacknowledgedCount: mockAlerts.filter((a) => !a.acknowledgedBy).length,
      });
      return;
    }

    const { filter } = get();
    set({ isLoading: true, error: null });
    if (reset) {
      set({ cursor: null, alerts: [] });
    }

    try {
      const acknowledged = filter === 'all' ? undefined : filter === 'acknowledged';
      const response = await alertsApi.getAlerts({
        acknowledged,
        limit: 20,
      });
      set({
        alerts: response.data,
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        totalCount: response.pagination.totalCount,
        allTotalCount: filter === 'all' ? response.pagination.totalCount : get().allTotalCount,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入警示列表' });
    }
  },

  fetchMore: async () => {
    const { cursor, hasMore, isLoading, alerts, filter } = get();
    if (!hasMore || isLoading || !cursor) return;

    set({ isLoading: true });
    try {
      const acknowledged = filter === 'all' ? undefined : filter === 'acknowledged';
      const response = await alertsApi.getAlerts({
        cursor,
        acknowledged,
        limit: 20,
      });
      set({
        alerts: [...alerts, ...response.data],
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        totalCount: response.pagination.totalCount,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入更多' });
    }
  },

  acknowledgeAlert: async (id, notes) => {
    try {
      const updated = await alertsApi.acknowledgeAlert(id, notes ? { acknowledgeNotes: notes } : undefined);
      set((state) => ({
        alerts:
          state.filter === 'unacknowledged'
            ? state.alerts.filter((a) => a.id !== id)
            : state.alerts.map((a) => (a.id === id ? updated : a)),
        unacknowledgedCount: Math.max(0, state.unacknowledgedCount - 1),
        totalCount:
          state.filter === 'unacknowledged'
            ? Math.max(0, state.totalCount - 1)
            : state.totalCount,
      }));
    } catch {
      set({ error: '確認警示失敗' });
    }
  },

  addNewAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts],
      unacknowledgedCount: state.unacknowledgedCount + 1,
      totalCount: state.totalCount + 1,
      allTotalCount: state.allTotalCount + 1,
    })),

  setFilter: (filter) => {
    set({ filter });
    get().fetchAlerts(true);
  },

  fetchUnacknowledgedCount: async () => {
    if (IS_MOCK) {
      set({ unacknowledgedCount: mockAlerts.filter((a) => !a.acknowledgedBy).length });
      return;
    }
    try {
      const count = await alertsApi.getUnacknowledgedCount();
      set({ unacknowledgedCount: count });
    } catch {
      // 靜默失敗
    }
  },

  clearError: () => set({ error: null }),
}));
