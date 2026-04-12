// =============================================================================
// 病患 API 服務
// =============================================================================

import apiClient from './client';
import type { Patient, PaginatedResponse, Session } from '../../types';
import type { PatientCreateRequest, PatientUpdateRequest, PatientListParams, SessionListParams } from '../../types/api';

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

/** 新增病患 */
export async function createPatient(payload: PatientCreateRequest): Promise<Patient> {
  const { data } = await apiClient.post<Patient>(BASE, payload);
  return data;
}

/** 更新病患 */
export async function updatePatient(id: string, payload: PatientUpdateRequest): Promise<Patient> {
  const { data } = await apiClient.put<Patient>(`${BASE}/${id}`, payload);
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
