// =============================================================================
// 認證 API 服務
// =============================================================================

import apiClient from './client';
import type { LoginRequest, LoginResponse, RegisterRequest, RefreshTokenResponse } from '../../types/api';
import type { User } from '../../types';

const AUTH_BASE = '/auth';

/** 登入 */
export async function login(email: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>(`${AUTH_BASE}/login`, {
    email,
    password,
  } satisfies LoginRequest);
  return data;
}

/** 註冊 */
export async function register(payload: RegisterRequest): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>(`${AUTH_BASE}/register`, payload);
  return data;
}

/** 刷新 Token */
export async function refreshToken(token: string): Promise<RefreshTokenResponse> {
  const { data } = await apiClient.post<RefreshTokenResponse>(`${AUTH_BASE}/refresh`, {
    refreshToken: token,
  });
  return data;
}

/** 登出 */
export async function logout(refreshToken?: string): Promise<void> {
  await apiClient.post(`${AUTH_BASE}/logout`, { refreshToken });
}

/** 變更密碼 */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiClient.post(`${AUTH_BASE}/change-password`, { currentPassword, newPassword });
}

/** 忘記密碼 */
/**
 * 忘記密碼。
 *
 * `delivery` 由後端環境有無 email transport 決定（與帳號是否存在無關）：
 * `'email'` = 信真的會寄出；`'onsite'` = 後端沒設 SENDGRID/SMTP，信不會寄出，
 * 呼叫端要改成引導使用者找現場醫護／管理員協助，別謊稱已寄信。
 */
export async function forgotPassword(
  email: string,
): Promise<{ delivery: 'email' | 'onsite' }> {
  const { data } = await apiClient.post<{ message: string; delivery?: 'email' | 'onsite' }>(
    `${AUTH_BASE}/forgot-password`,
    { email },
  );
  // 舊版後端沒有這個欄位 → 保守當成 onsite（寧可多叫人問現場，不要謊稱已寄出）
  return { delivery: data?.delivery ?? 'onsite' };
}

/** 重設密碼 */
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await apiClient.post(`${AUTH_BASE}/reset-password`, { token, newPassword });
}

/** 取得目前使用者資料 */
export async function getMe(): Promise<User> {
  const { data } = await apiClient.get<User>(`${AUTH_BASE}/me`);
  return data;
}

/** 更新目前使用者資料 */
export async function updateMe(payload: Partial<User>): Promise<User> {
  const { data } = await apiClient.put<User>(`${AUTH_BASE}/me`, payload);
  return data;
}
