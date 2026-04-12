// =============================================================================
// Enum 常數定義
// 值保持 snake_case 以對齊後端，避免額外映射
// =============================================================================

export const UserRole = {
  PATIENT: 'patient',
  DOCTOR: 'doctor',
  ADMIN: 'admin',
} as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

export const SessionStatus = {
  WAITING: 'waiting',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  ABORTED_RED_FLAG: 'aborted_red_flag',
  CANCELLED: 'cancelled',
} as const;
export type SessionStatus = (typeof SessionStatus)[keyof typeof SessionStatus];

export const ConversationRole = {
  PATIENT: 'patient',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
} as const;
export type ConversationRole = (typeof ConversationRole)[keyof typeof ConversationRole];

export const AlertSeverity = {
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'medium',
} as const;
export type AlertSeverity = (typeof AlertSeverity)[keyof typeof AlertSeverity];

export const AlertType = {
  RULE_BASED: 'rule_based',
  SEMANTIC: 'semantic',
  COMBINED: 'combined',
} as const;
export type AlertType = (typeof AlertType)[keyof typeof AlertType];

export const ReportStatus = {
  GENERATING: 'generating',
  GENERATED: 'generated',
  FAILED: 'failed',
} as const;
export type ReportStatus = (typeof ReportStatus)[keyof typeof ReportStatus];

export const ReviewStatus = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REVISION_NEEDED: 'revision_needed',
} as const;
export type ReviewStatus = (typeof ReviewStatus)[keyof typeof ReviewStatus];

export const NotificationType = {
  RED_FLAG: 'red_flag',
  SESSION_COMPLETE: 'session_complete',
  REPORT_READY: 'report_ready',
  SYSTEM: 'system',
} as const;
export type NotificationType = (typeof NotificationType)[keyof typeof NotificationType];

export const AuditAction = {
  CREATE: 'create',
  READ: 'read',
  UPDATE: 'update',
  DELETE: 'delete',
  LOGIN: 'login',
  LOGOUT: 'logout',
  EXPORT: 'export',
  REVIEW: 'review',
  ACKNOWLEDGE: 'acknowledge',
  SESSION_START: 'session_start',
  SESSION_END: 'session_end',
} as const;
export type AuditAction = (typeof AuditAction)[keyof typeof AuditAction];

export const DevicePlatform = {
  IOS: 'ios',
  ANDROID: 'android',
  WEB: 'web',
} as const;
export type DevicePlatform = (typeof DevicePlatform)[keyof typeof DevicePlatform];

export const Gender = {
  MALE: 'male',
  FEMALE: 'female',
  OTHER: 'other',
} as const;
export type Gender = (typeof Gender)[keyof typeof Gender];

// =============================================================================
// UI 狀態映射（衍生自後端 Enum）
// =============================================================================

export const sessionStatusDisplay: Record<SessionStatus, { label: string; color: string }> = {
  waiting: { label: '等待中', color: 'gray' },
  in_progress: { label: '對話中', color: 'blue' },
  completed: { label: '已完成', color: 'green' },
  aborted_red_flag: { label: '紅旗中止', color: 'red' },
  cancelled: { label: '已取消', color: 'gray' },
};

export const alertSeverityDisplay: Record<AlertSeverity, { label: string; color: string }> = {
  critical: { label: '危急', color: 'red-600' },
  high: { label: '高', color: 'orange-500' },
  medium: { label: '中', color: 'yellow-500' },
};
