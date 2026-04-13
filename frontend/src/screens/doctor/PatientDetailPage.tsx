// =============================================================================
// 病患詳情頁
// =============================================================================

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import EmptyState from '../../components/common/EmptyState';
import type { Patient, Session } from '../../types';
import * as patientsApi from '../../services/api/patients';
import { formatDate, formatDuration } from '../../utils/format';

export default function PatientDetailPage() {
  const { patientId } = useParams<{ patientId: string }>();
  const navigate = useNavigate();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!patientId) return;
    const currentPatientId = patientId;

    async function load() {
      setIsLoading(true);
      setError('');
      try {
        const [patientData, sessionData] = await Promise.all([
          patientsApi.getPatient(currentPatientId),
          patientsApi.getPatientSessions(currentPatientId, { limit: 20 }),
        ]);
        setPatient(patientData);
        setSessions(sessionData.data);
      } catch {
        setError('無法載入病患資料');
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [patientId]);

  if (isLoading) return <LoadingSpinner fullPage message="載入病患資料..." />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!patient) return <ErrorState message="找不到病患資料" />;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center gap-4">
        <button
          className="rounded-card p-2 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate('/patients')}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 className="text-h1 text-ink-heading dark:text-white">病患詳情</h1>
          <p className="text-small font-data text-ink-muted">MRN: {patient.medicalRecordNumber}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-1">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-h3 font-semibold text-primary-700 dark:bg-primary-950 dark:text-primary-300">
              {patient.name.charAt(0)}
            </div>
            <div>
              <h2 className="text-h3 text-ink-heading dark:text-white">{patient.name}</h2>
              <p className="text-small text-ink-muted">{patient.phone || '未設定聯絡電話'}</p>
            </div>
          </div>

          <div className="space-y-3">
            <InfoRow label="性別" value={patient.gender === 'male' ? '男' : patient.gender === 'female' ? '女' : '其他'} />
            <InfoRow label="出生日期" value={formatDate(patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })} />
            <InfoRow label="建立日期" value={formatDate(patient.createdAt, { year: 'numeric', month: '2-digit', day: '2-digit' })} />
          </div>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <div className="card">
            <h2 className="mb-3 text-h3 text-ink-heading dark:text-white">病史摘要</h2>
            <InfoList
              title="過敏史"
              items={patient.allergies?.map((item) => item.allergen) ?? []}
              emptyText="未記錄"
            />
            <InfoList
              title="目前用藥"
              items={patient.currentMedications?.map((item) => item.name) ?? []}
              emptyText="未記錄"
            />
            <InfoList
              title="過去病史"
              items={patient.medicalHistory?.map((item) => item.condition) ?? []}
              emptyText="未記錄"
            />
          </div>

          <div className="card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-h3 text-ink-heading dark:text-white">最近場次</h2>
              <span className="text-small text-ink-muted">{sessions.length} 筆</span>
            </div>

            {sessions.length === 0 ? (
              <EmptyState title="無場次紀錄" message="目前沒有可顯示的問診場次" />
            ) : (
              <div className="space-y-2">
                {sessions.map((session) => (
                  <button
                    key={session.id}
                    className="card-interactive flex w-full items-center justify-between rounded-card border border-edge px-4 py-3 text-left dark:border-dark-border"
                    onClick={() => navigate(`/sessions/${session.id}`)}
                  >
                    <div>
                      <p className="text-body font-medium text-ink-heading dark:text-white">
                        {session.chiefComplaintText || session.chiefComplaint?.name || '未填寫主訴'}
                      </p>
                      <p className="mt-1 text-small text-ink-muted">
                        {formatDate(session.createdAt)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-small font-medium text-ink-secondary">{session.status}</p>
                      <p className="mt-1 text-tiny font-tnum text-ink-muted">
                        {session.durationSeconds ? formatDuration(session.durationSeconds) : '-'}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-edge py-2 last:border-b-0 dark:border-dark-border">
      <span className="text-body text-ink-secondary">{label}</span>
      <span className="text-body font-medium text-ink-heading dark:text-white">{value}</span>
    </div>
  );
}

function InfoList({
  title,
  items,
  emptyText,
}: {
  title: string;
  items: string[];
  emptyText: string;
}) {
  return (
    <div className="mb-4 last:mb-0">
      <h3 className="mb-2 text-small font-semibold text-ink-secondary">{title}</h3>
      {items.length === 0 ? (
        <p className="text-small text-ink-muted">{emptyText}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <span key={`${title}-${item}`} className="rounded-pill bg-surface-secondary px-2.5 py-1 text-small text-ink-body dark:bg-dark-surface dark:text-white/80">
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
