// =============================================================================
// API 請求/回應型別
// =============================================================================

import type {
  PaginatedResponse,
  User,
  Patient,
  Session,
  Conversation,
  SOAPReport,
  RedFlagAlert,
  RedFlagRule,
  Notification,
  AuditLog,
  ChiefComplaint,
  SessionIntake,
} from './index';

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
  role: 'patient' | 'doctor' | 'admin';
  phone?: string;
  licenseNumber?: string;
  department?: string;
}

export interface RefreshTokenRequest {
  refreshToken: string;
}

export interface RefreshTokenResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  newPassword: string;
}

export interface ChangePasswordRequest {
  currentPassword: string;
  newPassword: string;
}

// ---- 病患 ----

export interface PatientCreateRequest {
  userId?: string;
  medicalRecordNumber: string;
  name: string;
  gender: 'male' | 'female' | 'other';
  dateOfBirth: string;
  phone?: string;
  emergencyContact?: {
    name: string;
    relationship: string;
    phone: string;
  };
  medicalHistory?: unknown[];
  allergies?: unknown[];
  currentMedications?: unknown[];
}

export interface PatientUpdateRequest {
  name?: string;
  phone?: string;
  emergencyContact?: {
    name: string;
    relationship: string;
    phone: string;
  };
  medicalHistory?: unknown[];
  allergies?: unknown[];
  currentMedications?: unknown[];
}

export interface PatientListParams {
  cursor?: string;
  limit?: number;
  search?: string;
  createdFrom?: string;
  createdTo?: string;
}

// ---- 場次 ----

export interface SessionPatientInfo {
  name: string;
  gender: 'male' | 'female' | 'other';
  dateOfBirth: string;
  phone?: string | null;
}

export interface SessionCreateRequest {
  patientId?: string;
  chiefComplaintId: string;
  chiefComplaintText?: string;
  language?: string;
  intake?: SessionIntake;
  patientInfo?: SessionPatientInfo;
}

export interface SessionStatusUpdateRequest {
  status: string;
  reason?: string;
}

export interface SessionListParams {
  cursor?: string;
  limit?: number;
  status?: string;
  patientId?: string;
  doctorId?: string;
}

export interface AssignDoctorRequest {
  doctorId: string;
}

// ---- 主訴 ----

export interface ComplaintCreateRequest {
  name: string;
  nameEn?: string;
  description?: string;
  category: string;
  isActive?: boolean;
  displayOrder?: number;
}

export interface ComplaintUpdateRequest {
  name?: string;
  nameEn?: string;
  description?: string;
  category?: string;
  isActive?: boolean;
  displayOrder?: number;
}

export interface ComplaintReorderRequest {
  items: { id: string; displayOrder: number }[];
}

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

export interface AlertAcknowledgeRequest {
  acknowledgeNotes?: string;
}

export interface AlertListParams {
  cursor?: string;
  limit?: number;
  severity?: string;
  acknowledged?: boolean;
  sessionId?: string;
}

// ---- 儀表板 ----

export interface DashboardStatsResponse {
  sessionsToday: number;
  completed: number;
  redFlags: number;
  pendingReviews: number;
  inProgress?: number;
  waiting?: number;
  averageDurationSeconds?: number | null;
  timestamp?: string;
}

export interface DashboardQueueResponse {
  totalWaiting: number;
  totalInProgress: number;
  queue: QueueItem[];
}

export interface QueueItem {
  sessionId: string;
  patientId: string;
  patientName: string;
  chiefComplaint: string;
  status: string;
  waitingSeconds: number;
  hasRedFlag: boolean;
  createdAt: string;
}

export interface RecentAlertItem {
  alertId: string;
  sessionId: string;
  patientName: string;
  severity: string;
  title: string;
  acknowledged: boolean;
  createdAt: string;
}

export interface RecentAlertsResponse {
  data: RecentAlertItem[];
}

export interface RecentSessionItem {
  sessionId: string;
  patientName: string;
  chiefComplaint: string;
  status: string;
  redFlag: boolean;
  createdAt: string;
  completedAt?: string;
}

export interface RecentSessionsResponse {
  data: RecentSessionItem[];
}

export interface SummaryBucketItem {
  key: string;
  label: string;
  count: number;
}

export interface DailyTrendItem {
  date: string;
  label: string;
  sessions: number;
  completed: number;
  redFlags: number;
}

export interface MonthlySummaryResponse {
  month: string;
  monthLabel: string;
  totalSessions: number;
  completedSessions: number;
  abortedRedFlagSessions: number;
  pendingReviews: number;
  totalRedFlagAlerts: number;
  completionRate: number;
  statusDistribution: SummaryBucketItem[];
  chiefComplaintDistribution: SummaryBucketItem[];
  alertSeverityDistribution: SummaryBucketItem[];
  dailyTrend: DailyTrendItem[];
  generatedAt: string;
}

// ---- 通知 ----

export interface NotificationListParams {
  cursor?: string;
  limit?: number;
  type?: string;
  isRead?: boolean;
}

export interface UnreadCountResponse {
  count: number;
}

/**
 * 標記已讀回應（對齊後端 MarkReadResponse，僅回傳精簡欄位）。
 * 後端 PUT /notifications/{id}/read 不回傳完整 Notification。
 */
export interface MarkReadResponse {
  id: string;
  isRead: boolean;
  readAt: string;
}

/** 通知偏好（GDPR opt-out）。red_flag 為病安關鍵，後端恆為開。 */
export interface NotificationPreference {
  userId: string;
  redFlagEnabled: boolean;
  sessionCompleteEnabled: boolean;
  reportReadyEnabled: boolean;
  systemEnabled: boolean;
  emailEnabled: boolean;
  pushEnabled: boolean;
}

/** 更新通知偏好（僅更新提供的欄位） */
export interface NotificationPreferenceUpdate {
  redFlagEnabled?: boolean;
  sessionCompleteEnabled?: boolean;
  reportReadyEnabled?: boolean;
  systemEnabled?: boolean;
  emailEnabled?: boolean;
  pushEnabled?: boolean;
}

/** 註冊 FCM 推播 Token 請求 */
export interface FcmTokenCreateRequest {
  deviceToken: string;
  platform: 'ios' | 'android' | 'web';
  deviceName?: string;
}

/** FCM Token 回應 */
export interface FcmTokenResponse {
  id: string;
  deviceToken: string;
  platform: 'ios' | 'android' | 'web';
  deviceName?: string;
  isActive: boolean;
  createdAt: string;
}

// ---- 管理員 ----

export interface UserCreateRequest {
  email: string;
  password: string;
  name: string;
  role: 'patient' | 'doctor' | 'admin';
  phone?: string;
  department?: string;
  licenseNumber?: string;
  isActive?: boolean;
}

export interface UserUpdateRequest {
  name?: string;
  email?: string;
  phone?: string;
  department?: string;
  licenseNumber?: string;
  isActive?: boolean;
  role?: 'patient' | 'doctor' | 'admin';
}

export interface UserListParams {
  cursor?: string;
  limit?: number;
  role?: string;
  search?: string;
  isActive?: boolean;
}

export interface AuditLogListParams {
  cursor?: string;
  limit?: number;
  action?: string;
  userId?: string;
  resourceType?: string;
  startDate?: string;
  endDate?: string;
}

// ---- 列表回應型別 ----

export type PatientListResponse = PaginatedResponse<Patient>;
export type SessionListResponse = PaginatedResponse<Session>;
export type ConversationListResponse = PaginatedResponse<Conversation>;
export type ReportListResponse = PaginatedResponse<SOAPReport>;
export type AlertListResponse = PaginatedResponse<RedFlagAlert>;
export type NotificationListResponse = PaginatedResponse<Notification>;
export type UserListResponse = PaginatedResponse<User>;
export type AuditLogListResponse = PaginatedResponse<AuditLog>;
export type ComplaintListResponse = PaginatedResponse<ChiefComplaint>;
export type RedFlagRuleListResponse = PaginatedResponse<RedFlagRule>;

// =============================================================================
// 研究分析（Research Analytics）— GET /research/analytics
// 後端 snake_case 由 client 攔截器自動轉 camelCase
// =============================================================================

export interface DistributionBucket {
  key: string;
  count: number;
}

export interface NumericSummary {
  n: number;
  mean: number | null;
  median: number | null;
  p25: number | null;
  p75: number | null;
  min: number | null;
  max: number | null;
}

export interface HistogramBucket {
  start: number;
  end: number;
  count: number;
}

export interface WeeklyTrendItem {
  weekStart: string;
  sessions: number;
  completed: number;
  redFlagSessions: number;
}

export interface ResearchCohortSection {
  totalSessions: number;
  completed: number;
  abortedRedFlag: number;
  cancelled: number;
  inProgressOrWaiting: number;
  completionRate: number | null;
  weeklyTrend: WeeklyTrendItem[];
}

export interface ResearchEfficiencySection {
  durationSeconds: NumericSummary;
  patientTurns: NumericSummary;
  patientTurnChars: NumericSummary;
  durationHistogram: HistogramBucket[];
  turnsHistogram: HistogramBucket[];
}

export interface HpiFieldFillRate {
  field: string;
  filled: number;
  total: number;
  rate: number | null;
}

export interface ResearchHistoryTakingSection {
  reportsAnalyzed: number;
  meanHpiCompleteness: number | null;
  hpiCompletenessSummary: NumericSummary;
  hpiFieldFillRates: HpiFieldFillRate[];
}

export interface ResearchSafetySection {
  sessionsWithAlerts: number;
  alertSessionRate: number | null;
  totalAlerts: number;
  severityDistribution: DistributionBucket[];
  layerDistribution: DistributionBucket[];
  alertTypeDistribution: DistributionBucket[];
  urgencyDistribution: DistributionBucket[];
  timeToFirstAlertSeconds: NumericSummary;
  acknowledgedRate: number | null;
  ackLatencySeconds: NumericSummary;
}

export interface SttLanguageQuality {
  language: string;
  turns: number;
  meanConfidence: number | null;
  lowConfidenceRate: number | null;
}

export interface ResearchSttQualitySection {
  turnsWithConfidence: number;
  confidenceSummary: NumericSummary;
  lowConfidenceRate: number | null;
  histogram: HistogramBucket[];
  byLanguage: SttLanguageQuality[];
  voiceTurnShare: number | null;
}

export interface ResearchDocumentationSection {
  reportsGenerated: number;
  aiConfidenceSummary: NumericSummary;
  icd10VerifiedRate: number | null;
  reviewOutcomes: DistributionBucket[];
  physicianAgreementRate: number | null;
  revisionReasonDistribution: DistributionBucket[];
}

export interface ResearchLanguageBreakdownItem {
  language: string;
  sessions: number;
  completed: number;
  medianDurationSeconds: number | null;
  meanPatientTurns: number | null;
  meanSttConfidence: number | null;
  redFlagSessionRate: number | null;
}

export interface ResearchAnalyticsResponse {
  generatedAt: string;
  dateFrom: string | null;
  dateTo: string | null;
  cohort: ResearchCohortSection;
  efficiency: ResearchEfficiencySection;
  historyTaking: ResearchHistoryTakingSection;
  safety: ResearchSafetySection;
  sttQuality: ResearchSttQualitySection;
  documentation: ResearchDocumentationSection;
  byLanguage: ResearchLanguageBreakdownItem[];
}
