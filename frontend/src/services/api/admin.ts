// =============================================================================
// 管理員 API 服務
// =============================================================================

import apiClient from './client';
import type { User, PaginatedResponse, AuditLog, RedFlagRule } from '../../types';
import type {
  UserCreateRequest,
  UserUpdateRequest,
  UserListParams,
  AuditLogListParams,
} from '../../types/api';

const USERS_BASE = '/admin/users';
const RULES_BASE = '/alerts/rules';
const AUDIT_BASE = '/audit-logs';

// ---- 使用者管理 ----

export async function getUsers(params?: UserListParams): Promise<PaginatedResponse<User>> {
  const { data } = await apiClient.get<PaginatedResponse<User>>(USERS_BASE, { params });
  return data;
}

export async function createUser(payload: UserCreateRequest): Promise<User> {
  const { data } = await apiClient.post<User>(USERS_BASE, payload);
  return data;
}

export async function updateUser(id: string, payload: UserUpdateRequest): Promise<User> {
  const { data } = await apiClient.put<User>(`${USERS_BASE}/${id}`, payload);
  return data;
}

/** 切換啟用狀態回應（對齊後端 ToggleActiveResponse，非完整 User） */
export interface ToggleActiveResponse {
  id: string;
  isActive: boolean;
  message: string;
}

export async function toggleUserActive(id: string): Promise<ToggleActiveResponse> {
  const { data } = await apiClient.put<ToggleActiveResponse>(`${USERS_BASE}/${id}/toggle-active`);
  return data;
}

// ---- 紅旗規則管理 ----

export async function getRedFlagRules(params?: {
  cursor?: string;
  limit?: number;
  category?: string;
  isActive?: boolean;
}): Promise<PaginatedResponse<RedFlagRule>> {
  const { data } = await apiClient.get<PaginatedResponse<RedFlagRule>>(RULES_BASE, { params });
  return data;
}

export async function createRedFlagRule(payload: Partial<RedFlagRule>): Promise<RedFlagRule> {
  const { data } = await apiClient.post<RedFlagRule>(RULES_BASE, payload);
  return data;
}

export async function updateRedFlagRule(
  id: string,
  payload: Partial<RedFlagRule>,
): Promise<RedFlagRule> {
  const { data } = await apiClient.put<RedFlagRule>(`${RULES_BASE}/${id}`, payload);
  return data;
}

export async function deleteRedFlagRule(id: string): Promise<void> {
  await apiClient.delete(`${RULES_BASE}/${id}`);
}

// ---- 稽核日誌 ----

export async function getAuditLogs(params?: AuditLogListParams): Promise<PaginatedResponse<AuditLog>> {
  const { data } = await apiClient.get<PaginatedResponse<AuditLog>>(AUDIT_BASE, { params });
  return data;
}

// ---- 系統健康 ----

/**
 * 系統健康狀態回應（對齊後端 SystemHealthResponse）。
 * 後端回傳：status / database / redis / openai / version / timestamp。
 * database/redis/openai/version/timestamp 保留 optional 以維持畫面相容（避免破壞既有 fallback）。
 */
export interface SystemHealthResponse {
  status: string;
  database?: string;
  redis?: string;
  openai?: string;
  version?: string;
  timestamp?: string;
}

export async function getSystemHealth(): Promise<SystemHealthResponse> {
  const { data } = await apiClient.get<SystemHealthResponse>('/admin/system/health');
  return data;
}
