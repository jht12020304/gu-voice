// =============================================================================
// 病患首頁 — 歡迎 + 開始問診 + 最近問診紀錄
// =============================================================================

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import * as sessionsApi from '../../services/api/sessions';
import { formatDate } from '../../utils/format';
import type { Session } from '../../types';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

const mockRecentSessions: Session[] = [
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
];

const statusLabels: Record<string, { text: string; cls: string }> = {
  completed: { text: '已完成', cls: 'badge-completed' },
  in_progress: { text: '進行中', cls: 'badge-in-progress' },
  waiting: { text: '等待中', cls: 'badge-waiting' },
  aborted_red_flag: { text: '紅旗中止', cls: 'badge-red-flag' },
  cancelled: { text: '已取消', cls: 'badge-red-flag' },
};

export default function PatientHomePage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function load() {
      if (IS_MOCK) {
        setRecentSessions(mockRecentSessions);
        setIsLoading(false);
        return;
      }
      try {
        const res = await sessionsApi.getSessions({ limit: 5, patientId: user?.id });
        setRecentSessions(res.data);
      } catch {
        // 靜默失敗
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [user?.id]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? '早安' : hour < 18 ? '午安' : '晚安';

  return (
    <div className="mx-auto max-w-2xl px-6 py-10 animate-fade-in">

      {/* 問候語 */}
      <div className="mb-8">
        <h1 className="text-h1 font-semibold tracking-tight text-ink-heading dark:text-white">
          {greeting}，{user?.name || '您好'}
        </h1>
        <p className="mt-1.5 text-body text-ink-muted dark:text-white/50">
          今天有什麼不適嗎？AI 助手將協助您整理症狀。
        </p>
      </div>

      {/* 開始問診 — 深色主色卡片，不需圖示 */}
      <button
        className="group w-full overflow-hidden rounded-panel bg-primary-600 px-6 pb-5 pt-6 text-left transition-colors hover:bg-primary-700 dark:bg-primary-700 dark:hover:bg-primary-600"
        onClick={() => navigate('/patient/start')}
      >
        <p className="text-tiny font-medium uppercase tracking-widest text-primary-200">
          泌尿科 AI 問診
        </p>
        <h2 className="mt-2 text-h2 font-semibold tracking-tight text-white">
          開始今天的問診
        </h2>
        <p className="mt-1 text-body text-primary-200">
          選擇症狀，填寫基本病史，與 AI 對話整理主訴
        </p>
        <div className="mt-5 flex items-center justify-end">
          <span className="flex items-center gap-1.5 text-small font-medium text-white/90 transition-colors group-hover:text-white">
            立即開始
            <svg className="h-4 w-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
          </span>
        </div>
      </button>

      {/* 最近問診紀錄 */}
      <div className="mt-10">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-tiny font-medium uppercase tracking-widest text-ink-muted dark:text-white/40">
            最近問診
          </h2>
          {recentSessions.length > 0 && (
            <button
              className="text-small font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 transition-colors"
              onClick={() => navigate('/patient/history')}
            >
              查看全部
            </button>
          )}
        </div>

        {isLoading ? (
          <div className="flex justify-center py-10">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
          </div>
        ) : recentSessions.length === 0 ? (
          <div className="py-10 text-center">
            <p className="text-body text-ink-muted dark:text-white/40">尚無問診紀錄</p>
            <p className="mt-1 text-small text-ink-placeholder dark:text-white/20">開始第一次問診吧</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-panel border border-edge bg-white dark:border-dark-border dark:bg-dark-card">
            {recentSessions.map((session, i) => {
              const sc = statusLabels[session.status] || statusLabels.completed;
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
    </div>
  );
}
