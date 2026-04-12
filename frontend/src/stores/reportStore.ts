// =============================================================================
// SOAP 報告狀態管理 (Zustand)
// =============================================================================

import { create } from 'zustand';
import type { SOAPReport, Conversation } from '../types';
import * as reportsApi from '../services/api/reports';
import * as sessionsApi from '../services/api/sessions';
import type { ReportListParams, ReviewRequest } from '../types/api';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockReport: SOAPReport = {
  id: 'rpt-001',
  sessionId: 's1',
  status: 'generated',
  reviewStatus: 'pending',
  summary: '45歲男性因肉眼血尿持續三天至泌尿科就診。問診過程中，AI 助手依序詢問了血尿的發生時間、顏色變化、伴隨症狀（頻尿與輕微排尿疼痛）、過去病史（高血壓控制中）、吸菸史（已戒菸5年，曾20包年）及用藥史。病患主訴血尿為每次排尿均可見，無明顯誘因，無發燒或腰痛。根據病史與症狀組合，初步評估需排除膀胱惡性腫瘤、泌尿道感染及結石的可能性。',
  icd10Codes: ['R31.0 — 肉眼血尿', 'R30.0 — 排尿疼痛', 'N30.9 — 膀胱炎'],
  aiConfidenceScore: 0.87,
  subjective: {
    chiefComplaint: '肉眼血尿持續三天',
    hpi: { onset: '三天前', location: '泌尿道', duration: '持續三天', characteristics: '肉眼可見的血尿，小便呈紅色', severity: '中度', aggravatingFactors: ['排尿時加重'], relievingFactors: ['無'], associatedSymptoms: ['頻尿', '輕微排尿疼痛'], timing: '每次排尿均有', context: '無明顯誘因' },
    pastMedicalHistory: { conditions: ['高血壓（控制中）'], surgeries: ['無'], hospitalizations: ['無'] },
    medicationHistory: { current: ['Amlodipine 5mg QD'], past: [], otc: [] },
    systemReview: { general: '無發燒、體重減輕', urological: '頻尿、血尿、輕微排尿疼痛' },
    socialHistory: { smoking: '已戒菸5年（之前20包年）', alcohol: '偶爾', occupation: '工程師' },
  },
  objective: {
    vitalSigns: { bloodPressure: '135/85', heartRate: 78, respiratoryRate: 16, temperature: 36.5, spo2: 98 },
    physicalExam: { abdomen: '軟，無壓痛', costovertebral: '無叩擊痛', genitourinary: '無外部異常' },
    labResults: [
      { testName: '尿液分析', result: 'RBC >50/HPF, WBC 5-10/HPF', referenceRange: 'RBC 0-3, WBC 0-5', isAbnormal: true, date: '2026-04-10' },
      { testName: 'PSA', result: '2.1 ng/mL', referenceRange: '0-4.0', isAbnormal: false, date: '2026-04-10' },
    ],
  },
  assessment: {
    differentialDiagnoses: [
      { diagnosis: '膀胱腫瘤', icd10: 'C67.9', probability: 'medium', reasoning: '45歲男性，有吸菸史，持續性肉眼血尿，需排除膀胱惡性腫瘤' },
      { diagnosis: '泌尿道感染', icd10: 'N39.0', probability: 'medium', reasoning: '血尿伴頻尿及排尿疼痛，但無發燒' },
      { diagnosis: '泌尿道結石', icd10: 'N20.9', probability: 'low', reasoning: '無典型腎絞痛表現' },
    ],
    clinicalImpression: '持續性肉眼血尿，需進一步影像學及內視鏡檢查排除惡性腫瘤可能',
  },
  plan: {
    recommendedTests: [
      { testName: '膀胱鏡檢查', rationale: '排除膀胱腫瘤', urgency: 'urgent', clinicalReasoning: '患者為45歲男性，有顯著吸菸史（20包年），出現持續性肉眼血尿。根據美國泌尿科學會(AUA)微血尿評估指引，40歲以上具有血尿危險因子（吸菸、男性）的患者，應進行膀胱鏡檢查以排除膀胱惡性腫瘤。吸菸是膀胱癌最重要的可改變危險因子，即使已戒菸5年，殘餘風險仍然偏高。' },
      { testName: '腎臟超音波', rationale: '評估上泌尿道', urgency: 'urgent', clinicalReasoning: '肉眼血尿的來源可能為上泌尿道（腎臟、輸尿管）或下泌尿道（膀胱、尿道）。腎臟超音波為非侵入性檢查，可快速評估是否有腎臟腫塊、水腎、結石等上泌尿道病灶。患者無典型腎絞痛，但仍需排除無痛性腎臟腫瘤的可能。此檢查與膀胱鏡互補，共同涵蓋完整泌尿道評估。' },
      { testName: '尿液細胞學', rationale: '細胞學篩檢', urgency: 'routine', clinicalReasoning: '尿液細胞學可檢測脫落的異常尿路上皮細胞，對高級別尿路上皮癌的敏感度較高。雖然對低級別腫瘤敏感度有限，但作為非侵入性輔助檢查，可與膀胱鏡及影像學檢查互相配合，提升整體診斷準確率。建議收集晨間中段尿送檢。' },
    ],
    diagnosticReasoning: '本案為45歲男性，具有吸菸史（20包年，已戒5年），主訴持續性肉眼血尿三天，伴隨頻尿與輕微排尿疼痛。臨床思路上，首先需排除最嚴重的鑑別診斷——膀胱惡性腫瘤，因患者具備多項危險因子（年齡、性別、吸菸史）。檢查策略採用「三管齊下」：膀胱鏡直接觀察膀胱內壁（金標準）、腎臟超音波評估上泌尿道、尿液細胞學作為細胞層面的輔助篩檢。三項檢查互補，可完整涵蓋從腎臟到膀胱的整條泌尿道，確保不遺漏任何潛在病灶。同時安排泌尿道感染相關檢查（尿液分析已完成），以排除感染性血尿的可能。',
    treatments: [
      { type: '藥物', name: 'Tamsulosin 0.4mg', instruction: '每日一次，飯後服用', note: '改善排尿症狀' },
    ],
    followUp: { interval: '一週', reason: '追蹤檢查結果', additionalNotes: '若血尿加重請提前回診' },
    referrals: [],
    patientEducation: ['多喝水（每日2000ml以上）', '避免劇烈運動', '觀察尿液顏色變化並記錄'],
  },
  rawTranscript: '系統：歡迎來到泌尿科 AI 問診助手。我將協助您進行初步問診，請放心描述您的症狀。\n\nAI 助手：您好！我是泌尿科 AI 問診助手。請問您今天來就診的主要原因是什麼？\n\n病患：我小便有血，已經三天了。\n\nAI 助手：了解，小便帶血確實需要注意。請問血尿的顏色大概是什麼樣的？是淡粉色、深紅色、還是有血塊？\n\n病患：是紅色的，沒有血塊。每次尿都這樣。\n\nAI 助手：好的。請問除了血尿之外，還有其他不舒服嗎？例如排尿時疼痛、頻尿、尿急、腰痛或發燒？\n\n病患：有一點排尿的時候會痛，然後比較頻尿，大概每小時要去一次。沒有發燒，也沒有腰痛。\n\nAI 助手：了解。請問這個血尿出現之前，有沒有什麼特別的事情發生？例如劇烈運動、外傷、或近期的醫療處置？\n\n病患：沒有，就突然開始的。\n\nAI 助手：好的。接下來想了解一下您的病史。請問您過去有沒有什麼慢性疾病或重大疾病？\n\n病患：有高血壓，有在吃藥控制。\n\nAI 助手：請問目前服用什麼降壓藥物？\n\n病患：Amlodipine，每天一顆。\n\nAI 助手：了解。請問您有吸菸或喝酒的習慣嗎？\n\n病患：以前有抽菸，大概抽了20年，一天一包。五年前戒掉了。偶爾喝點酒。\n\nAI 助手：感謝您的資訊。有吸菸史對泌尿科問題的評估很重要。最後想確認，您有藥物過敏或家族中有泌尿科相關疾病嗎？\n\n病患：沒有過敏。家族也沒有特別的泌尿科問題。\n\nAI 助手：好的，謝謝您詳細的回答。根據您的描述，我為您整理了初步的症狀摘要，醫師會進一步為您評估。',
  generatedAt: '2026-04-10T14:00:00Z',
  createdAt: '2026-04-10T14:00:00Z',
  updatedAt: '2026-04-10T14:00:00Z',
};

const mockConversations = [
  { id: 'c1', sessionId: 's1', sequenceNumber: 1, role: 'system' as const, contentText: '歡迎來到泌尿科 AI 問診助手。我將協助您進行初步問診，請放心描述您的症狀。', redFlagDetected: false, createdAt: '2026-04-10T13:30:00Z' },
  { id: 'c2', sessionId: 's1', sequenceNumber: 2, role: 'assistant' as const, contentText: '您好！我是泌尿科 AI 問診助手。請問您今天來就診的主要原因是什麼？', redFlagDetected: false, createdAt: '2026-04-10T13:30:05Z' },
  { id: 'c3', sessionId: 's1', sequenceNumber: 3, role: 'patient' as const, contentText: '我小便有血，已經三天了。', redFlagDetected: false, createdAt: '2026-04-10T13:30:30Z' },
  { id: 'c4', sessionId: 's1', sequenceNumber: 4, role: 'assistant' as const, contentText: '了解，小便帶血確實需要注意。請問血尿的顏色大概是什麼樣的？是淡粉色、深紅色、還是有血塊？', redFlagDetected: false, createdAt: '2026-04-10T13:30:35Z' },
  { id: 'c5', sessionId: 's1', sequenceNumber: 5, role: 'patient' as const, contentText: '是紅色的，沒有血塊。每次尿都這樣。', redFlagDetected: false, createdAt: '2026-04-10T13:31:10Z' },
  { id: 'c6', sessionId: 's1', sequenceNumber: 6, role: 'assistant' as const, contentText: '好的。請問除了血尿之外，還有其他不舒服嗎？例如排尿時疼痛、頻尿、尿急、腰痛或發燒？', redFlagDetected: false, createdAt: '2026-04-10T13:31:15Z' },
  { id: 'c7', sessionId: 's1', sequenceNumber: 7, role: 'patient' as const, contentText: '有一點排尿的時候會痛，然後比較頻尿，大概每小時要去一次。沒有發燒，也沒有腰痛。', redFlagDetected: false, createdAt: '2026-04-10T13:31:50Z' },
  { id: 'c8', sessionId: 's1', sequenceNumber: 8, role: 'assistant' as const, contentText: '了解。請問這個血尿出現之前，有沒有什麼特別的事情發生？例如劇烈運動、外傷、或近期的醫療處置？', redFlagDetected: false, createdAt: '2026-04-10T13:31:55Z' },
  { id: 'c9', sessionId: 's1', sequenceNumber: 9, role: 'patient' as const, contentText: '沒有，就突然開始的。', redFlagDetected: false, createdAt: '2026-04-10T13:32:20Z' },
  { id: 'c10', sessionId: 's1', sequenceNumber: 10, role: 'assistant' as const, contentText: '好的。接下來想了解一下您的病史。請問您過去有沒有什麼慢性疾病或重大疾病？', redFlagDetected: false, createdAt: '2026-04-10T13:32:25Z' },
  { id: 'c11', sessionId: 's1', sequenceNumber: 11, role: 'patient' as const, contentText: '有高血壓，有在吃藥控制。', redFlagDetected: false, createdAt: '2026-04-10T13:32:50Z' },
  { id: 'c12', sessionId: 's1', sequenceNumber: 12, role: 'assistant' as const, contentText: '請問目前服用什麼降壓藥物？', redFlagDetected: false, createdAt: '2026-04-10T13:32:55Z' },
  { id: 'c13', sessionId: 's1', sequenceNumber: 13, role: 'patient' as const, contentText: 'Amlodipine，每天一顆。', redFlagDetected: false, createdAt: '2026-04-10T13:33:10Z' },
  { id: 'c14', sessionId: 's1', sequenceNumber: 14, role: 'assistant' as const, contentText: '了解。請問您有吸菸或喝酒的習慣嗎？', redFlagDetected: false, createdAt: '2026-04-10T13:33:15Z' },
  { id: 'c15', sessionId: 's1', sequenceNumber: 15, role: 'patient' as const, contentText: '以前有抽菸，大概抽了20年，一天一包。五年前戒掉了。偶爾喝點酒。', redFlagDetected: false, createdAt: '2026-04-10T13:33:50Z' },
  { id: 'c16', sessionId: 's1', sequenceNumber: 16, role: 'assistant' as const, contentText: '感謝您的資訊。有吸菸史對泌尿科問題的評估很重要。最後想確認，您有藥物過敏或家族中有泌尿科相關疾病嗎？', redFlagDetected: false, createdAt: '2026-04-10T13:33:55Z' },
  { id: 'c17', sessionId: 's1', sequenceNumber: 17, role: 'patient' as const, contentText: '沒有過敏。家族也沒有特別的泌尿科問題。', redFlagDetected: false, createdAt: '2026-04-10T13:34:20Z' },
  { id: 'c18', sessionId: 's1', sequenceNumber: 18, role: 'assistant' as const, contentText: '好的，謝謝您詳細的回答。根據您的描述，我為您整理了初步的症狀摘要，醫師會進一步為您評估。', redFlagDetected: false, createdAt: '2026-04-10T13:34:25Z' },
];

interface ReportState {
  reports: SOAPReport[];
  selectedReport: SOAPReport | null;
  conversations: Conversation[];
  isLoading: boolean;
  isLoadingConversations: boolean;
  cursor: string | null;
  hasMore: boolean;
  error: string | null;
}

interface ReportActions {
  fetchReports: (params?: ReportListParams, reset?: boolean) => Promise<void>;
  fetchMore: (params?: ReportListParams) => Promise<void>;
  fetchReport: (id: string) => Promise<void>;
  fetchReportBySession: (sessionId: string) => Promise<void>;
  fetchConversations: (sessionId: string) => Promise<void>;
  generateReport: (sessionId: string) => Promise<void>;
  reviewReport: (id: string, payload: ReviewRequest) => Promise<void>;
  clearSelectedReport: () => void;
  clearError: () => void;
}

export const useReportStore = create<ReportState & ReportActions>((set, get) => ({
  // ---- State ----
  reports: [],
  selectedReport: null,
  conversations: [],
  isLoading: false,
  isLoadingConversations: false,
  cursor: null,
  hasMore: true,
  error: null,

  // ---- Actions ----

  fetchReports: async (params, reset = true) => {
    set({ isLoading: true, error: null });
    if (reset) set({ cursor: null, reports: [] });

    try {
      const response = await reportsApi.getReports({ ...params, limit: 20 });
      set({
        reports: response.data,
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入報告列表' });
    }
  },

  fetchMore: async (params) => {
    const { cursor, hasMore, isLoading, reports } = get();
    if (!hasMore || isLoading || !cursor) return;

    set({ isLoading: true });
    try {
      const response = await reportsApi.getReports({ ...params, cursor, limit: 20 });
      set({
        reports: [...reports, ...response.data],
        cursor: response.pagination.nextCursor,
        hasMore: response.pagination.hasMore,
        isLoading: false,
      });
    } catch {
      set({ isLoading: false, error: '無法載入更多' });
    }
  },

  fetchReport: async (id) => {
    set({ isLoading: true, error: null });
    try {
      const report = await reportsApi.getReport(id);
      set({ selectedReport: report, isLoading: false });
    } catch {
      set({ isLoading: false, error: '無法載入報告' });
    }
  },

  fetchReportBySession: async (sessionId) => {
    if (IS_MOCK) {
      set({ selectedReport: { ...mockReport, sessionId }, conversations: mockConversations, isLoading: false });
      return;
    }
    set({ isLoading: true, error: null });
    try {
      const report = await reportsApi.getReportBySession(sessionId);
      set({ selectedReport: report, isLoading: false });
    } catch {
      set({ isLoading: false, error: '無法載入報告' });
    }
  },

  fetchConversations: async (sessionId) => {
    if (IS_MOCK) {
      set({ conversations: mockConversations, isLoadingConversations: false });
      return;
    }
    set({ isLoadingConversations: true });
    try {
      const allConversations: Conversation[] = [];
      let cursor: string | undefined;
      // Fetch all pages
      do {
        const response = await sessionsApi.getSessionConversations(sessionId, { cursor, limit: 200 });
        allConversations.push(...response.data);
        cursor = response.pagination.nextCursor ?? undefined;
      } while (cursor);
      set({ conversations: allConversations, isLoadingConversations: false });
    } catch {
      set({ isLoadingConversations: false });
    }
  },

  generateReport: async (sessionId) => {
    set({ isLoading: true, error: null });
    try {
      const report = await reportsApi.generateReport(sessionId);
      set({ selectedReport: report, isLoading: false });
    } catch {
      set({ isLoading: false, error: '報告生成失敗' });
    }
  },

  reviewReport: async (id, payload) => {
    set({ isLoading: true, error: null });
    try {
      const updated = await reportsApi.reviewReport(id, payload);
      set((state) => ({
        selectedReport: updated,
        reports: state.reports.map((r) => (r.id === id ? updated : r)),
        isLoading: false,
      }));
    } catch {
      set({ isLoading: false, error: '審閱失敗' });
    }
  },

  clearSelectedReport: () => set({ selectedReport: null, conversations: [] }),
  clearError: () => set({ error: null }),
}));
