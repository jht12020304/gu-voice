// =============================================================================
// 主訴管理狀態 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { ChiefComplaint } from '../types';
import * as complaintsApi from '../services/api/complaints';
import type { ComplaintCreateRequest, ComplaintUpdateRequest } from '../types/api';

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
    } catch {
      set({ isLoading: false, error: '無法載入主訴列表' });
    }
  },

  createComplaint: async (data) => {
    set({ isLoading: true });
    try {
      await complaintsApi.createComplaint(data);
      await get().fetchComplaints();
    } catch {
      set({ isLoading: false, error: '新增主訴失敗' });
    }
  },

  updateComplaint: async (id, data) => {
    set({ isLoading: true });
    try {
      await complaintsApi.updateComplaint(id, data);
      await get().fetchComplaints();
    } catch {
      set({ isLoading: false, error: '更新主訴失敗' });
    }
  },

  reorder: async (items) => {
    try {
      await complaintsApi.reorderComplaints({ items });
      // 樂觀更新本地排序
      set((state) => {
        const orderMap = new Map(items.map((i) => [i.id, i.displayOrder]));
        const updated = state.complaints
          .map((c) => (orderMap.has(c.id) ? { ...c, displayOrder: orderMap.get(c.id)! } : c))
          .sort((a, b) => a.displayOrder - b.displayOrder);
        return { complaints: updated, groupedComplaints: groupByCategory(updated) };
      });
    } catch {
      set({ error: '排序失敗' });
    }
  },

  clearError: () => set({ error: null }),
}));
