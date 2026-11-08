// =============================================================================
// API 請求/回應型別
// =============================================================================

import type { User } from './index';
import type { UserRole } from './enums';

// ---- 認證 ----

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  user: User;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
  // 對齊後端 UserRole（patient/doctor/admin）；後端註冊預設為 patient
  role: UserRole;
  phone?: string;
  licenseNumber?: string;
  department?: string;
}

export interface RefreshTokenResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

// ---- 病患 ----

// ---- 場次 ----

// ---- 主訴 ----

// ---- 報告 ----

export interface ReviewRequest {
  reviewStatus: 'approved' | 'revision_needed';
  reviewNotes?: string;
}

export interface ReportListParams {
  cursor?: string;
  limit?: number;
  status?: string;
  reviewStatus?: string;
  sessionId?: string;
}

// ---- 警示 ----

// ---- 儀表板 ----

// ---- 通知 ----

// =============================================================================
// 研究分析（Research Analytics）— GET /research/analytics
// 後端 snake_case 由 client 攔截器自動轉 camelCase
// =============================================================================

