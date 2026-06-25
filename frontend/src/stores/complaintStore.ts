// =============================================================================
// 主訴管理狀態 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { ChiefComplaint } from '../types';
import * as complaintsApi from '../services/api/complaints';
import type { ComplaintCreateRequest, ComplaintUpdateRequest } from '../types/api';
import i18n from '../i18n';

/**
 * 取後端錯誤訊息（已是使用者目前語言，後端 LanguageMiddleware 依 Accept-Language 回對應語系），
 * 取不到時退回 i18n fallback key。避免 catch{} 直接吞錯只丟死的中文字串。
 */
function resolveErrorMessage(error: unknown, fallbackKey: string, fallbackText: string): string {
  const backendMessage = (
    error as { response?: { data?: { error?: { message?: string } } } }
  )?.response?.data?.error?.message;
  if (backendMessage) return backendMessage;
  return i18n.t(fallbackKey, { defaultValue: fallbackText });
}

interface ComplaintState {
  complaints: ChiefComplaint[];
  /** 依分類群組 */
  groupedComplaints: Record<string, ChiefComplaint[]>;
  isLoading: boolean;
  error: string | null;
}

interface ComplaintActions {
  fetchComplaints: () => Promise<void>;
  createComplaint: (data: ComplaintCreateRequest) => Promise<void>;
  updateComplaint: (id: string, data: ComplaintUpdateRequest) => Promise<void>;
  reorder: (items: { id: string; displayOrder: number }[]) => Promise<void>;
  clearError: () => void;
}

function groupByCategory(complaints: ChiefComplaint[]): Record<string, ChiefComplaint[]> {
  return complaints.reduce<Record<string, ChiefComplaint[]>>((acc, c) => {
    const key = c.category;
    if (!acc[key]) acc[key] = [];
    acc[key].push(c);
    return acc;
  }, {});
}

export const useComplaintStore = create<ComplaintState & ComplaintActions>((set, get) => ({
  // ---- State ----
  complaints: [],
  groupedComplaints: {},
  isLoading: false,
  error: null,

  // ---- Actions ----

  fetchComplaints: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await complaintsApi.getComplaints({ limit: 100, isActive: true });
      const sorted = response.data.sort((a, b) => a.displayOrder - b.displayOrder);
      set({
        complaints: sorted,
        groupedComplaints: groupByCategory(sorted),
        isLoading: false,
      });
    } catch (error) {
      set({
        isLoading: false,
        error: resolveErrorMessage(error, 'admin:complaints.loadFailed', '無法載入主訴列表'),
      });
    }
  },

  createComplaint: async (data) => {
    set({ isLoading: true });
    try {
      await complaintsApi.createComplaint(data);
      await get().fetchComplaints();
    } catch (error) {
      set({
        isLoading: false,
        error: resolveErrorMessage(error, 'admin:complaints.saveFailed', '新增主訴失敗'),
      });
    }
  },

  updateComplaint: async (id, data) => {
    set({ isLoading: true });
    try {
      await complaintsApi.updateComplaint(id, data);
      await get().fetchComplaints();
    } catch (error) {
      set({
        isLoading: false,
        error: resolveErrorMessage(error, 'admin:complaints.saveFailed', '更新主訴失敗'),
      });
    }
  },

  reorder: async (items) => {
    // L-9：先樂觀更新本地排序（即時回饋），失敗時回滾。
    // 快照舊狀態，API 失敗時還原，避免 UI 停在後端未落地的排序而資料不一致。
    const previous = get().complaints;
    set((state) => {
      const orderMap = new Map(items.map((i) => [i.id, i.displayOrder]));
      const updated = state.complaints
        .map((c) => (orderMap.has(c.id) ? { ...c, displayOrder: orderMap.get(c.id)! } : c))
        .sort((a, b) => a.displayOrder - b.displayOrder);
      return { complaints: updated, groupedComplaints: groupByCategory(updated), error: null };
    });

    try {
      await complaintsApi.reorderComplaints({ items });
    } catch (error) {
      // 回滾樂觀更新並顯示後端訊息
      set({
        complaints: previous,
        groupedComplaints: groupByCategory(previous),
        error: resolveErrorMessage(error, 'admin:complaints.saveFailed', '排序失敗'),
      });
    }
  },

  clearError: () => set({ error: null }),
}));
