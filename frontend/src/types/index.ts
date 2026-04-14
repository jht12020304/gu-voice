// =============================================================================
// 核心資料型別 (Core Data Types)
// 所有欄位使用 camelCase，由 API 層自動轉換 snake_case
// =============================================================================

/** 使用者 */
export interface User {
  id: string;
  email: string;
  name: string;
  role: 'patient' | 'doctor' | 'admin';
  phone?: string;
  department?: string;
  licenseNumber?: string;
  isActive: boolean;
  lastLoginAt?: string;
  createdAt: string;
  updatedAt: string;
}

/** 病患 */
export interface Patient {
  id: string;
  userId: string;
  medicalRecordNumber: string;
  name: string;
  gender: 'male' | 'female' | 'other';
  dateOfBirth: string;
  phone?: string;
  emergencyContact?: EmergencyContact;
  medicalHistory?: MedicalHistoryEntry[];
  allergies?: AllergyEntry[];
  currentMedications?: MedicationEntry[];
  createdAt: string;
  updatedAt: string;
}

export interface EmergencyContact {
  name: string;
  relationship: string;
  phone: string;
}

export interface MedicalHistoryEntry {
  condition: string;
  diagnosedYear: number;
  status: 'active' | 'controlled' | 'resolved';
  notes?: string;
}

export interface AllergyEntry {
  allergen: string;
  type: 'drug' | 'food' | 'environmental' | 'other';
  reaction: string;
  severity: 'mild' | 'moderate' | 'severe';
}

export interface MedicationEntry {
  name: string;
  dose: string;
  frequency: string;
  route: string;
  indication: string;
}

export interface SessionIntakeAllergyItem {
  allergen: string;
  reaction?: string;
  severity?: string;
  hadHospitalization: boolean;
}

export interface SessionIntakeMedicationItem {
  name: string;
  frequency?: string;
}

export interface SessionIntakeMedicalHistoryItem {
  condition: string;
  yearsAgo?: string;
  stillHas: boolean;
}

export interface SessionIntakeFamilyHistoryItem {
  relation: string;
  condition: string;
}

export interface SessionIntake {
  noKnownAllergies: boolean;
  allergies: SessionIntakeAllergyItem[];
  noCurrentMedications: boolean;
  currentMedications: SessionIntakeMedicationItem[];
  noPastMedicalHistory: boolean;
  medicalHistory: SessionIntakeMedicalHistoryItem[];
  familyHistory: SessionIntakeFamilyHistoryItem[];
}

/** 主訴 */
export interface ChiefComplaint {
  id: string;
  name: string;
  nameEn?: string;
  description?: string;
  category: string;
  isDefault: boolean;
  isActive: boolean;
  displayOrder: number;
  createdBy?: string;
  createdAt: string;
  updatedAt: string;
}

/** 問診場次 */
export interface Session {
  id: string;
  patientId: string;
  doctorId?: string;
  chiefComplaintId: string;
  chiefComplaintText?: string;
  status: 'waiting' | 'in_progress' | 'completed' | 'aborted_red_flag' | 'cancelled';
  redFlag: boolean;
  redFlagReason?: string;
  language: string;
  intake?: SessionIntake;
  intakeCompletedAt?: string;
  startedAt?: string;
  completedAt?: string;
  durationSeconds?: number;
  createdAt: string;
  updatedAt: string;
  // 後端在列表/明細 API 可能直接返回病患姓名
  patientName?: string;
  // 前端擴充：API 可能包含關聯資料
  patient?: Patient;
  chiefComplaint?: ChiefComplaint;
}

/** 對話紀錄 */
export interface Conversation {
  id: string;
  sessionId: string;
  sequenceNumber: number;
  role: 'patient' | 'assistant' | 'system';
  contentText: string;
  audioUrl?: string;
  audioDurationSeconds?: number;
  sttConfidence?: number;
  redFlagDetected: boolean;
  metadata?: Record<string, unknown>;
  createdAt: string;
}

/** SOAP 報告 */
export interface SOAPReport {
  id: string;
  sessionId: string;
  status: 'generating' | 'generated' | 'failed';
  reviewStatus: 'pending' | 'approved' | 'revision_needed';
  subjective?: SOAPSubjective;
  objective?: SOAPObjective;
  assessment?: SOAPAssessment;
  plan?: SOAPPlan;
  rawTranscript?: string;
  summary?: string;
  icd10Codes?: string[];
  aiConfidenceScore?: number;
  reviewedBy?: string;
  reviewedAt?: string;
  reviewNotes?: string;
  generatedAt?: string;
  createdAt: string;
  updatedAt: string;
}

/** SOAP - Subjective */
export interface SOAPSubjective {
  chiefComplaint: string;
  hpi: {
    onset: string;
    location: string;
    duration: string;
    characteristics: string;
    severity: string;
    aggravatingFactors: string[];
    relievingFactors: string[];
    associatedSymptoms: string[];
    timing: string;
    context: string;
  };
  pastMedicalHistory: {
    conditions: string[];
    surgeries: string[];
    hospitalizations: string[];
  };
  medicationHistory: {
    current: string[];
    past: string[];
    otc: string[];
  };
  systemReview: Record<string, string>;
  socialHistory: Record<string, string>;
}

/** SOAP - Objective */
export interface SOAPObjective {
  vitalSigns?: {
    bloodPressure?: string;
    heartRate?: number;
    respiratoryRate?: number;
    temperature?: number;
    spo2?: number;
  };
  physicalExam?: Record<string, string>;
  labResults?: LabResult[];
  imagingResults?: ImagingResult[];
}

export interface LabResult {
  testName: string;
  result: string;
  referenceRange: string;
  isAbnormal: boolean;
  date: string;
}

export interface ImagingResult {
  testName: string;
  result: string;
  date: string;
}

/** SOAP - Assessment */
export interface SOAPAssessment {
  differentialDiagnoses: DifferentialDiagnosis[];
  clinicalImpression: string;
}

export interface DifferentialDiagnosis {
  diagnosis: string;
  icd10: string;
  probability: 'high' | 'medium' | 'low';
  reasoning: string;
}

/** SOAP - Plan */
export interface SOAPPlan {
  recommendedTests: RecommendedTest[];
  treatments: Treatment[];
  followUp: {
    interval: string;
    reason: string;
    additionalNotes?: string;
  };
  referrals: string[];
  patientEducation: string[];
  diagnosticReasoning?: string;
}

export interface RecommendedTest {
  testName: string;
  rationale: string;
  urgency: 'urgent' | 'routine' | 'elective';
  clinicalReasoning?: string;
}

export interface Treatment {
  type: string;
  name: string;
  instruction: string;
  note?: string;
}

/** 紅旗警示 */
export interface RedFlagAlert {
  id: string;
  sessionId: string;
  conversationId: string;
  alertType: 'rule_based' | 'semantic' | 'combined';
  severity: 'critical' | 'high' | 'medium';
  title: string;
  description?: string;
  triggerReason: string;
  triggerKeywords?: string[];
  matchedRuleId?: string;
  llmAnalysis?: Record<string, unknown>;
  suggestedActions?: string[];
  acknowledgedBy?: string;
  acknowledgedAt?: string;
  acknowledgeNotes?: string;
  createdAt: string;
}

/** 紅旗規則 */
export interface RedFlagRule {
  id: string;
  name: string;
  description?: string;
  category: string;
  keywords: string[];
  regexPattern?: string;
  severity: 'critical' | 'high' | 'medium';
  suspectedDiagnosis?: string;
  suggestedAction?: string;
  isActive: boolean;
  createdBy?: string;
  createdAt: string;
  updatedAt: string;
}

/** 通知 */
export interface Notification {
  id: string;
  userId: string;
  type: 'red_flag' | 'session_complete' | 'report_ready' | 'system';
  title: string;
  body?: string;
  data?: Record<string, unknown>;
  isRead: boolean;
  readAt?: string;
  createdAt: string;
}

/** 稽核日誌 */
export interface AuditLog {
  id: number;
  userId?: string;
  action: string;
  resourceType: string;
  resourceId?: string;
  details?: Record<string, unknown>;
  ipAddress?: string;
  userAgent?: string;
  createdAt: string;
}

/** FCM 裝置 */
export interface FCMDevice {
  id: string;
  userId: string;
  deviceToken: string;
  platform: 'ios' | 'android' | 'web';
  deviceName?: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

/** 分頁回應 */
export interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    nextCursor: string | null;
    hasMore: boolean;
    limit: number;
    totalCount: number;
  };
}

/** 錯誤回應 */
export interface ErrorResponse {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    requestId: string;
    timestamp: string;
  };
}
