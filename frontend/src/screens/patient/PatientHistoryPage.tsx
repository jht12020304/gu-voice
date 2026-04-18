// =============================================================================
// 病患問診紀錄頁 — 列表 + 篩選
// =============================================================================

import { useEffect, useState } from 'react';
import { useAuthStore } from '../../stores/authStore';
import { useLocalizedNavigate } from '../../i18n/paths';
import * as sessionsApi from '../../services/api/sessions';
import { formatDate } from '../../utils/format';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import type { Session } from '../../types';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockSessions: Session[] = [
  {
    id: 'mock-session-001',
    patientId: 'mock-patient-001',
    doctorId: 'mock-doctor-001',
    chiefComplaintId: 'cc1',
    chiefComplaintText: '血尿持續三天',
    status: 'completed',
    redFlag: true,
    redFlagReason: '肉眼血尿持續超過 48 小時',
    language: 'zh-TW',
    startedAt: '2026-04-10T13:30:00Z',
    completedAt: '2026-04-10T13:45:00Z',
    durationSeconds: 900,
    createdAt: '2026-04-10T13:30:00Z',
    updatedAt: '2026-04-10T13:45:00Z',
  },
  {
    id: 'mock-session-002',
    patientId: 'mock-patient-001',
    chiefComplaintId: 'cc2',
    chiefComplaintText: '頻尿',
    status: 'completed',
    redFlag: false,
    language: 'zh-TW',
    startedAt: '2026-04-03T10:00:00Z',
    completedAt: '2026-04-03T10:12:00Z',
    durationSeconds: 720,
    createdAt: '2026-04-03T10:00:00Z',
    updatedAt: '2026-04-03T10:12:00Z',
  },
  {
    id: 'mock-session-003',
    patientId: 'mock-patient-001',
    chiefComplaintId: 'cc5',
    chiefComplaintText: '腰痛',
    status: 'completed',
    redFlag: false,
    language: 'zh-TW',
    startedAt: '2026-03-20T09:00:00Z',
    completedAt: '2026-03-20T09:10:00Z',
    durationSeconds: 600,
    createdAt: '2026-03-20T09:00:00Z',
    updatedAt: '2026-03-20T09:10:00Z',
  },
  {
    id: 'mock-session-004',
    patientId: 'mock-patient-001',
    chiefComplaintId: 'cc3',
    chiefComplaintText: '排尿疼痛',
    status: 'cancelled',
    redFlag: false,
    language: 'zh-TW',
    startedAt: '2026-03-15T14:00:00Z',
    durationSeconds: 120,
    createdAt: '2026-03-15T14:00:00Z',
    updatedAt: '2026-03-15T14:02:00Z',
  },
];

type FilterStatus = 'all' | 'completed' | 'in_progress' | 'cancelled';

const statusConfig: Record<string, { text: string; cls: string }> = {
  completed: { text: '已完成', cls: 'badge-completed' },
  in_progress: { text: '進行中', cls: 'badge-in-progress' },
  waiting: { text: '等待中', cls: 'badge-waiting' },
  aborted_red_flag: { text: '紅旗中止', cls: 'badge-red-flag' },
  cancelled: { text: '已取消', cls: 'badge-red-flag' },
};

const filters: { value: FilterStatus; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'completed', label: '已完成' },
  { value: 'in_progress', label: '進行中' },
  { value: 'cancelled', label: '已取消' },
];

export default function PatientHistoryPage() {
  const navigate = useLocalizedNavigate();
  const user = useAuthStore((s) => s.user);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<FilterStatus>('all');

  useEffect(() => {
    async function load() {
      if (IS_MOCK) {
        setSessions(mockSessions);
        setIsLoading(false);
        return;
      }
      try {
        const res = await sessionsApi.getSessions({ limit: 50, patientId: user?.id });
        setSessions(res.data);
      } catch {
        // 靜默
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [user?.id]);

  const filtered = filter === 'all'
    ? sessions
    : sessions.filter((s) => s.status === filter);

  return (
    <div className="mx-auto max-w-2xl px-6 py-8 animate-fade-in">

      {/* Header */}
      <div className="mb-8 flex items-center gap-3">
        <button
          className="rounded-card p-1.5 text-ink-placeholder hover:bg-surface-tertiary hover:text-ink-secondary transition-colors"
          onClick={() => navigate('/patient')}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 className="text-h2 font-semibold tracking-tight text-ink-heading dark:text-white">問診紀錄</h1>
          <p className="mt-0.5 text-small text-ink-muted dark:text-white/50">共 {sessions.length} 次問診</p>
        </div>
      </div>

      {/* 篩選 */}
      <div className="mb-5 flex gap-1 rounded-card bg-surface-secondary p-1 dark:bg-dark-surface">
        {filters.map((f) => (
          <button
            key={f.value}
            className={`flex-1 rounded-card px-3 py-1.5 text-small font-medium transition-colors ${
              filter === f.value
                ? 'bg-white text-ink-heading shadow-sm dark:bg-dark-bg dark:text-white'
                : 'text-ink-muted hover:text-ink-secondary dark:text-white/40 dark:hover:text-white/70'
            }`}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 列表 */}
      {isLoading ? (
        <LoadingSpinner message="載入紀錄..." />
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-body text-ink-muted dark:text-white/40">
            {filter === 'all' ? '尚無問診紀錄' : '無符合條件的紀錄'}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
          {filtered.map((session, i) => {
            const sc = statusConfig[session.status] || statusConfig.completed;
            return (
              <button
                key={session.id}
                className={`relative flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-surface-secondary dark:hover:bg-dark-hover ${
                  i > 0 ? 'border-t border-edge/60 dark:border-dark-border' : ''
                }`}
                onClick={() => {
                  if (session.status === 'completed' || session.status === 'aborted_red_flag') {
                    navigate(`/patient/session/${session.id}/complete`);
                  } else if (session.status === 'in_progress' || session.status === 'waiting') {
                    navigate(`/conversation/${session.id}`);
                  }
                }}
              >
                {session.redFlag && (
                  <span className="absolute inset-y-0 left-0 w-[3px] bg-red-500" />
                )}
                <div className="min-w-0 flex-1 pl-1">
                  <p className="text-body font-medium text-ink-heading dark:text-white">
                    {session.chiefComplaintText || '問診'}
                  </p>
                  <p className="mt-0.5 text-small text-ink-muted dark:text-white/40">
                    {formatDate(session.createdAt)}
                    {session.durationSeconds ? ` · ${Math.round(session.durationSeconds / 60)} 分鐘` : ''}
                  </p>
                </div>
                <span className={`badge shrink-0 ${sc.cls}`}>{sc.text}</span>
                <svg className="h-4 w-4 shrink-0 text-ink-placeholder dark:text-white/25" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
