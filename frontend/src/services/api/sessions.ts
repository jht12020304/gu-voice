// =============================================================================
// 場次 API 服務（網頁版只讀：報告頁取場次資訊與逐字稿）
// =============================================================================

import apiClient from './client';
import type { Session, PaginatedResponse, Conversation } from '../../types';

const BASE = '/sessions';

/** 取得單一場次 */
export async function getSession(id: string): Promise<Session> {
  const { data } = await apiClient.get<Session>(`${BASE}/${id}`);
  return data;
}

/** 取得場次對話紀錄 */
export async function getSessionConversations(
  id: string,
  params?: { cursor?: string; limit?: number },
): Promise<PaginatedResponse<Conversation>> {
  const { data } = await apiClient.get<PaginatedResponse<Conversation>>(
    `${BASE}/${id}/conversations`,
    { params },
  );
  return data;
}

// ---- 檢查醫囑（快速開單）：`/sessions/{id}/exam-orders`，與 Flutter ExamOrdersApi 同一組端點 ----

/** 一筆檢查項目，形狀對齊 SOAP `plan.recommendedTests` 的元素（快照，不是參照）。 */
export interface ExamOrderItem {
  testName: string;
  urgency?: string;
  rationale?: string;
}

export interface ExamOrder {
  id: string;
  sessionId: string;
  reportId?: string | null;
  orderedBy: string;
  items: ExamOrderItem[];
  note?: string | null;
  createdAt: string;
}

/** 這場次最新一張檢查單；還沒開過時後端回 200 + null。 */
export async function getLatestExamOrder(sessionId: string): Promise<ExamOrder | null> {
  const { data } = await apiClient.get<ExamOrder | null>(`${BASE}/${sessionId}/exam-orders/latest`);
  return data && typeof data === 'object' ? data : null;
}

/** 送出檢查單（append-only，以最新一張為準）。空 items 合法＝「看過了，這次不開檢查」。 */
export async function submitExamOrder(
  sessionId: string,
  payload: { items: ExamOrderItem[]; note?: string; reportId?: string },
): Promise<ExamOrder> {
  const { data } = await apiClient.post<ExamOrder>(`${BASE}/${sessionId}/exam-orders`, payload);
  return data;
}
