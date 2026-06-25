// =============================================================================
// 病患詳情頁
// =============================================================================

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { useLocalizedNavigate } from '../../i18n/paths';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import ErrorState from '../../components/common/ErrorState';
import EmptyState from '../../components/common/EmptyState';
import Modal from '../../components/common/Modal';
import type { Patient, Session } from '../../types';
import * as patientsApi from '../../services/api/patients';
import { formatDate, formatDuration } from '../../utils/format';

export default function PatientDetailPage() {
  const { t } = useTranslation('common');
  const { patientId } = useParams<{ patientId: string }>();
  const navigate = useLocalizedNavigate();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  // 刪除病患（軟刪除）— 走確認 Modal
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

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
        setSessions(Array.isArray(sessionData.data) ? sessionData.data : []);
      } catch {
        setError(t('doctor.patient.loadError', '無法載入病患資料'));
      } finally {
        setIsLoading(false);
      }
    }

    load();
  }, [patientId, t]);

  const handleDelete = async () => {
    if (!patientId) return;
    setIsDeleting(true);
    try {
      await patientsApi.deletePatient(patientId);
      toast.success(t('doctor.patient.deleteSuccess', '已刪除病患'));
      setShowDeleteModal(false);
      navigate('/patients');
    } catch {
      toast.error(t('doctor.patient.deleteError', '刪除病患失敗，請稍後再試'));
    } finally {
      setIsDeleting(false);
    }
  };

  if (isLoading) return <LoadingSpinner fullPage message={t('doctor.patient.loading', '載入病患資料...')} />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!patient) return <ErrorState message={t('doctor.patient.notFound', '找不到病患資料')} />;

  const patientName = patient.name || t('doctor.patient.unnamed', '未命名病患');
  const patientInitial = patientName.trim().charAt(0) || '?';
  const allergies = Array.isArray(patient.allergies) ? patient.allergies : [];
  const currentMedications = Array.isArray(patient.currentMedications) ? patient.currentMedications : [];
  const medicalHistory = Array.isArray(patient.medicalHistory) ? patient.medicalHistory : [];

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
        <div className="flex-1">
          <h1 className="text-h1 text-ink-heading dark:text-white">{t('doctor.patient.title', '病患詳情')}</h1>
          <p className="text-small font-data text-ink-muted">MRN: {patient.medicalRecordNumber}</p>
        </div>
        <button
          className="btn-secondary text-alert-critical hover:bg-red-50 dark:hover:bg-red-950/30"
          onClick={() => setShowDeleteModal(true)}
          disabled={isDeleting}
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
          {t('doctor.patient.delete', '刪除病患')}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-1">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-h3 font-semibold text-primary-700 dark:bg-primary-950 dark:text-primary-300">
              {patientInitial}
            </div>
            <div>
              <h2 className="text-h3 text-ink-heading dark:text-white">{patientName}</h2>
              <p className="text-small text-ink-muted">{patient.phone || t('doctor.patient.noPhone')}</p>
            </div>
          </div>

          <div className="space-y-3">
            <InfoRow
              label={t('doctor.patient.labels.gender')}
              value={
                patient.gender === 'male'
                  ? t('gender.male')
                  : patient.gender === 'female'
                    ? t('gender.female')
                    : t('gender.other')
              }
            />
            <InfoRow label={t('doctor.patient.labels.dateOfBirth')} value={formatDate(patient.dateOfBirth, { year: 'numeric', month: '2-digit', day: '2-digit' })} />
            <InfoRow label={t('doctor.patient.labels.createdAt')} value={formatDate(patient.createdAt, { year: 'numeric', month: '2-digit', day: '2-digit' })} />
          </div>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <div className="card">
            <h2 className="mb-3 text-h3 text-ink-heading dark:text-white">{t('doctor.patient.historyTitle', '病史摘要')}</h2>
            <InfoList
              title={t('doctor.patient.allergies', '過敏史')}
              items={allergies.map((item) => item.allergen)}
              emptyText={t('doctor.patient.notRecorded', '未記錄')}
            />
            <InfoList
              title={t('doctor.patient.currentMedications', '目前用藥')}
              items={currentMedications.map((item) => item.name)}
              emptyText={t('doctor.patient.notRecorded', '未記錄')}
            />
            <InfoList
              title={t('doctor.patient.medicalHistory', '過去病史')}
              items={medicalHistory.map((item) => item.condition)}
              emptyText={t('doctor.patient.notRecorded', '未記錄')}
            />
          </div>

          <div className="card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-h3 text-ink-heading dark:text-white">{t('doctor.patient.recentSessions', '最近場次')}</h2>
              <span className="text-small text-ink-muted">{t('doctor.patient.sessionCount', '{{count}} 筆', { count: sessions.length })}</span>
            </div>

            {sessions.length === 0 ? (
              <EmptyState title={t('doctor.patient.noSessions', '無場次紀錄')} message={t('doctor.patient.noSessionsHint', '目前沒有可顯示的問診場次')} />
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
                        {session.chiefComplaintText || session.chiefComplaint?.name || t('doctor.patient.noComplaint', '未填寫主訴')}
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

      {/* 刪除病患確認 Modal */}
      <Modal
        visible={showDeleteModal}
        onClose={() => {
          if (!isDeleting) setShowDeleteModal(false);
        }}
        title={t('doctor.patient.deleteTitle', '刪除病患')}
        closable={!isDeleting}
        footer={
          <>
            <button
              className="btn-secondary"
              onClick={() => setShowDeleteModal(false)}
              disabled={isDeleting}
            >
              {t('doctor.patient.cancelAction', '取消')}
            </button>
            <button
              className="btn-primary bg-alert-critical hover:bg-red-700"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting && (
                <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {isDeleting
                ? t('doctor.patient.deleting', '刪除中...')
                : t('doctor.patient.confirmDelete', '確認刪除')}
            </button>
          </>
        }
      >
        <p className="text-body text-ink-body dark:text-white/85">
          {t('doctor.patient.deleteConfirm', '確認刪除病患「{{name}}」？此操作將移除該病患資料。', { name: patientName })}
        </p>
      </Modal>
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
