// =============================================================================
// 問診場次列表頁
// =============================================================================

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocalizedNavigate } from '../../i18n/paths';
import StatusBadge from '../../components/medical/StatusBadge';
import SearchBar from '../../components/form/SearchBar';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import type { Session } from '../../types';
import type { SessionStatus } from '../../types/enums';
import { formatDate, formatDuration } from '../../utils/format';
import * as sessionsApi from '../../services/api/sessions';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockSessions: Session[] = [
  { id: 's1', patientId: 'p1', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc1', chiefComplaintText: '血尿持續三天', status: 'in_progress', redFlag: true, redFlagReason: '肉眼血尿', language: 'zh-TW', startedAt: '2026-04-10T13:30:00Z', durationSeconds: 1200, createdAt: '2026-04-10T13:30:00Z', updatedAt: '2026-04-10T13:50:00Z', patient: { id: 'p1', userId: 'u1', medicalRecordNumber: 'MRN-2026-0001', name: '陳小明', gender: 'male', dateOfBirth: '1985-03-15', createdAt: '2026-01-15T08:00:00Z', updatedAt: '2026-04-10T10:00:00Z' } },
  { id: 's2', patientId: 'p2', chiefComplaintId: 'cc2', chiefComplaintText: '頻尿、夜尿增加', status: 'waiting', redFlag: false, language: 'zh-TW', createdAt: '2026-04-10T13:18:00Z', updatedAt: '2026-04-10T13:18:00Z', patient: { id: 'p2', userId: 'u2', medicalRecordNumber: 'MRN-2026-0002', name: '林美玲', gender: 'female', dateOfBirth: '1972-08-22', createdAt: '2026-02-03T09:30:00Z', updatedAt: '2026-04-10T09:00:00Z' } },
  { id: 's3', patientId: 'p3', chiefComplaintId: 'cc3', chiefComplaintText: '排尿困難', status: 'waiting', redFlag: false, language: 'zh-TW', createdAt: '2026-04-10T13:05:00Z', updatedAt: '2026-04-10T13:05:00Z', patient: { id: 'p3', userId: 'u3', medicalRecordNumber: 'MRN-2026-0003', name: '張大偉', gender: 'male', dateOfBirth: '1990-11-08', createdAt: '2026-02-10T14:00:00Z', updatedAt: '2026-04-09T16:00:00Z' } },
  { id: 's4', patientId: 'p4', chiefComplaintId: 'cc4', chiefComplaintText: '左側腰痛伴噁心', status: 'waiting', redFlag: true, redFlagReason: '疑似腎絞痛', language: 'zh-TW', createdAt: '2026-04-10T12:51:00Z', updatedAt: '2026-04-10T12:51:00Z', patient: { id: 'p4', userId: 'u4', medicalRecordNumber: 'MRN-2026-0004', name: '王志明', gender: 'male', dateOfBirth: '1968-05-30', createdAt: '2026-03-01T10:00:00Z', updatedAt: '2026-04-10T13:30:00Z' } },
  { id: 'rs1', patientId: 'p6', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc5', chiefComplaintText: '攝護腺症狀 (PSA 偏高)', status: 'completed', redFlag: false, language: 'zh-TW', startedAt: '2026-04-10T11:00:00Z', completedAt: '2026-04-10T11:30:00Z', durationSeconds: 1800, createdAt: '2026-04-10T11:00:00Z', updatedAt: '2026-04-10T11:30:00Z', patient: { id: 'p6', userId: 'u6', medicalRecordNumber: 'MRN-2026-0006', name: '黃美芳', gender: 'female', dateOfBirth: '1965-07-18', createdAt: '2026-03-12T08:30:00Z', updatedAt: '2026-04-10T11:30:00Z' } },
  { id: 'rs2', patientId: 'p7', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc6', chiefComplaintText: '泌尿道感染 (反覆發作)', status: 'completed', redFlag: false, language: 'zh-TW', startedAt: '2026-04-10T10:15:00Z', completedAt: '2026-04-10T10:45:00Z', durationSeconds: 1800, createdAt: '2026-04-10T10:15:00Z', updatedAt: '2026-04-10T10:45:00Z', patient: { id: 'p7', userId: 'u7', medicalRecordNumber: 'MRN-2026-0007', name: '吳建宏', gender: 'male', dateOfBirth: '1982-09-25', createdAt: '2026-03-18T13:00:00Z', updatedAt: '2026-04-10T10:45:00Z' } },
  { id: 'rs4', patientId: 'p8', doctorId: 'mock-doctor-001', chiefComplaintId: 'cc8', chiefComplaintText: '勃起功能障礙', status: 'aborted_red_flag', redFlag: true, redFlagReason: '疑似心血管風險', language: 'zh-TW', startedAt: '2026-04-10T09:00:00Z', completedAt: '2026-04-10T09:15:00Z', durationSeconds: 900, createdAt: '2026-04-10T09:00:00Z', updatedAt: '2026-04-10T09:15:00Z', patient: { id: 'p8', userId: 'u8', medicalRecordNumber: 'MRN-2026-0008', name: '周志豪', gender: 'male', dateOfBirth: '1975-04-12', createdAt: '2026-03-22T09:00:00Z', updatedAt: '2026-04-10T09:15:00Z' } },
];

export default function SessionListPage() {
  const navigate = useLocalizedNavigate();
  const { t } = useTranslation('session');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const statusTabs = useMemo(
    () => [
      { key: '', label: t('doctor.list.tabAll') },
      { key: 'in_progress', label: t('doctor.list.tabInProgress') },
      { key: 'waiting', label: t('doctor.list.tabWaiting') },
      { key: 'completed', label: t('doctor.list.tabCompleted') },
    ],
    [t]
  );

  useEffect(() => {
    if (IS_MOCK) {
      let filtered = mockSessions;
      if (statusFilter) filtered = filtered.filter((s) => s.status === statusFilter);
      if (searchQuery) filtered = filtered.filter((s) => s.patient?.name.includes(searchQuery) || s.chiefComplaintText?.includes(searchQuery));
      setSessions(filtered);
      setIsLoading(false);
      return;
    }

    async function load() {
      try {
        const response = await sessionsApi.getSessions({ limit: 50 });
        setSessions(response.data);
      } catch {
        // 靜默
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [statusFilter, searchQuery]);

  return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="text-h1 text-ink-heading dark:text-white">{t('doctor.list.title')}</h1>

      {/* 篩選 */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="w-64">
          <SearchBar value={searchQuery} onChange={setSearchQuery} placeholder={t('doctor.list.searchPlaceholder')} />
        </div>
        <div className="flex gap-2">
          {statusTabs.map((tab) => (
            <button
              key={tab.key}
              className={`rounded-btn px-3 py-1.5 text-caption font-medium transition-colors ${
                statusFilter === tab.key
                  ? 'bg-primary-600 text-white'
                  : 'btn-secondary'
              }`}
              onClick={() => setStatusFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      {isLoading ? (
        <LoadingSpinner fullPage />
      ) : sessions.length === 0 ? (
        <EmptyState title={t('doctor.list.emptyTitle')} message={t('doctor.list.emptyMessage')} />
      ) : (
        <div className="space-y-2">
          {sessions.map((session) => (
            <div
              key={session.id}
              className={`card card-interactive flex items-center gap-4 ${
                session.redFlag ? 'border-l-4 border-l-alert-critical' : ''
              }`}
              onClick={() => navigate(`/sessions/${session.id}`)}
            >
              {/* 頭像 */}
              <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-caption font-semibold ${
                session.redFlag
                  ? 'bg-alert-critical-bg text-alert-critical'
                  : 'bg-primary-50 text-primary-700 dark:bg-primary-950 dark:text-primary-300'
              }`}>
                {(session.patientName ?? session.patient?.name ?? '?').charAt(0)}
              </div>

              {/* 資訊 */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-body font-medium text-ink-heading dark:text-white">
                    {session.patientName ?? session.patient?.name ?? t('doctor.list.unknownPatient')}
                  </p>
                  {session.redFlag && (
                    <span className="badge badge-red-flag text-tiny px-1.5 py-0.5">{t('doctor.list.redFlagBadge')}</span>
                  )}
                </div>
                <p className="mt-0.5 truncate text-small text-ink-muted">
                  {session.chiefComplaintText || t('doctor.list.chiefComplaintEmpty')}
                </p>
              </div>

              {/* 時間 + 狀態 */}
              <div className="flex flex-shrink-0 flex-col items-end gap-1">
                <StatusBadge status={session.status as SessionStatus} size="sm" />
                <span className="text-tiny text-ink-muted font-tnum">
                  {session.durationSeconds ? formatDuration(session.durationSeconds) : formatDate(session.createdAt, { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
