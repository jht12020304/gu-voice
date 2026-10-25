// =============================================================================
// 病患 API 服務
// =============================================================================

import apiClient from './client';
import type { Patient, PaginatedResponse, Session } from '../../types';
import type { PatientListParams, SessionListParams } from '../../types/api';

const BASE = '/patients';

/** 取得病患列表 */
export async function getPatients(params?: PatientListParams): Promise<PaginatedResponse<Patient>> {
  const { data } = await apiClient.get<PaginatedResponse<Patient>>(BASE, { params });
  return data;
}

/** 取得單一病患 */
export async function getPatient(id: string): Promise<Patient> {
  const { data } = await apiClient.get<Patient>(`${BASE}/${id}`);
  return data;
}

/** 刪除病患 */
export async function deletePatient(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/${id}`);
}

/** 取得病患的場次列表 */
export async function getPatientSessions(
  id: string,
  params?: SessionListParams,
): Promise<PaginatedResponse<Session>> {
  const { data } = await apiClient.get<PaginatedResponse<Session>>(`${BASE}/${id}/sessions`, { params });
  return data;
}
