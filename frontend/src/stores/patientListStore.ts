// =============================================================================
// 病患列表狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { Patient } from '../types';
import * as patientsApi from '../services/api/patients';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';
const DEFAULT_MONTH = new Date().toISOString().slice(0, 7);

const mockPatients: Patient[] = [
  { id: 'p1', userId: 'u1', medicalRecordNumber: 'MRN-2026-0001', name: '陳小明', gender: 'male', dateOfBirth: '1985-03-15', phone: '0912-345-678', createdAt: '2026-01-15T08:00:00Z', updatedAt: '2026-04-10T10:00:00Z' },
  { id: 'p2', userId: 'u2', medicalRecordNumber: 'MRN-2026-0002', name: '林美玲', gender: 'female', dateOfBirth: '1972-08-22', phone: '0923-456-789', createdAt: '2026-02-03T09:30:00Z', updatedAt: '2026-04-10T09:00:00Z' },
  { id: 'p3', userId: 'u3', medicalRecordNumber: 'MRN-2026-0003', name: '張大偉', gender: 'male', dateOfBirth: '1990-11-08', phone: '0934-567-890', createdAt: '2026-02-10T14:00:00Z', updatedAt: '2026-04-09T16:00:00Z' },
  { id: 'p4', userId: 'u4', medicalRecordNumber: 'MRN-2026-0004', name: '王志明', gender: 'male', dateOfBirth: '1968-05-30', phone: '0945-678-901', createdAt: '2026-03-01T10:00:00Z', updatedAt: '2026-04-10T13:30:00Z' },
  { id: 'p5', userId: 'u5', medicalRecordNumber: 'MRN-2026-0005', name: '李淑華', gender: 'female', dateOfBirth: '1978-12-01', phone: '0956-789-012', createdAt: '2026-03-05T11:00:00Z', updatedAt: '2026-04-09T15:00:00Z' },
  { id: 'p6', userId: 'u6', medicalRecordNumber: 'MRN-2026-0006', name: '黃美芳', gender: 'female', dateOfBirth: '1965-07-18', phone: '0967-890-123', createdAt: '2026-03-12T08:30:00Z', updatedAt: '2026-04-10T11:30:00Z' },
  { id: 'p7', userId: 'u7', medicalRecordNumber: 'MRN-2026-0007', name: '吳建宏', gender: 'male', dateOfBirth: '1982-09-25', phone: '0978-901-234', createdAt: '2026-03-18T13:00:00Z', updatedAt: '2026-04-10T10:45:00Z' },
  { id: 'p8', userId: 'u8', medicalRecordNumber: 'MRN-2026-0008', name: '趙淑芬', gender: 'female', dateOfBirth: '1975-04-12', phone: '0989-012-345', createdAt: '2026-03-22T09:00:00Z', updatedAt: '2026-04-10T10:00:00Z' },
];

interface PatientListState {
  patients: Patient[];
  selectedPatient: Patient | null;
  isLoading: boolean;
  cursor: string | null;
  hasMore: boolean;
  totalCount: number;
  searchQuery: string;
  selectedMonth: string;
  error: string | null;
}

interface PatientListActions {
  fetchPatients: (reset?: boolean) => Promise<void>;
  fetchMore: () => Promise<void>;
  setSearch: (query: string) => void;
  setSelectedMonth: (month: string) => void;
  selectPatient: (patient: Patient | null) => void;
  clearError: () => void;
}

function getMonthDateRange(month: string): { createdFrom: string; createdTo: string } {
  const [year, monthIndex] = month.split('-').map(Number);
  const createdFrom = new Date(year, monthIndex - 1, 1, 0, 0, 0, 0).toISOString();
  const createdTo = new Date(year, monthIndex, 0, 23, 59, 59, 999).toISOString();
  return { createdFrom, createdTo };
}

export const usePatientListStore = create<PatientListState & PatientListActions>((set, get) => ({
  // ---- State ----
  patients: [],
  selectedPatient: null,
  isLoading: false,
  cursor: null,
  hasMore: true,
  totalCount: 0,
  searchQuery: '',
  selectedMonth: DEFAULT_MONTH,
  error: null,

  // ---- Actions ----

  fetchPatients: async (reset = true) => {
    if (IS_MOCK) {
      const { searchQuery, selectedMonth } = get();
      const filtered = mockPatients.filter((patient) => {
        const inSelectedMonth = patient.createdAt.slice(0, 7) === selectedMonth;
        const matchesSearch = searchQuery
          ? patient.name.includes(searchQuery) || patient.medicalRecordNumber.includes(searchQuery)
          : true;
        return inSelectedMonth && matchesSearch;
      });
      set({
        patients: filtered,
        totalCount: filtered.length,
        isLoading: false,
        hasMore: false,
        cursor: null,
      });
      return;
    }

    const { searchQuery, selectedMonth } = get();
    const { createdFrom, createdTo } = getMonthDateRange(selectedMonth);
    set({ isLoading: true, error: null });
    if (reset) {
      set({ cursor: null, patients: [], totalCount: 0 });
    }

    try {
      const response = await patientsApi.getPatients({
        search: searchQuery || undefined,
        limit: 20,
        createdFrom,
        createdTo,
      });
      set({
        patients: response.data,
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        totalCount: response.pagination.totalCount,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入病患列表' });
    }
  },

  fetchMore: async () => {
    const { cursor, hasMore, isLoading, patients, searchQuery, selectedMonth, totalCount } = get();
    if (!hasMore || isLoading || !cursor) return;

    const { createdFrom, createdTo } = getMonthDateRange(selectedMonth);
    set({ isLoading: true });
    try {
      const response = await patientsApi.getPatients({
        cursor,
        search: searchQuery || undefined,
        limit: 20,
        createdFrom,
        createdTo,
      });
      set({
        patients: [...patients, ...response.data],
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        totalCount: response.pagination.totalCount ?? totalCount,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入更多' });
    }
  },

  setSearch: (query) => set({ searchQuery: query }),

  setSelectedMonth: (month) => set({ selectedMonth: month }),

  selectPatient: (patient) => set({ selectedPatient: patient }),

  clearError: () => set({ error: null }),
}));
