// =============================================================================
// 醫師儀表板 — 含 Mock 資料模式
// =============================================================================

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import StatCard from '../../components/dashboard/StatCard';
import QueueCard from '../../components/dashboard/QueueCard';
import AlertItem from '../../components/dashboard/AlertItem';
import StatusBadge from '../../components/medical/StatusBadge';
import SeverityBadge from '../../components/medical/SeverityBadge';
import * as dashboardApi from '../../services/api/dashboard';

const IS_MOCK = import.meta.env.VITE_ENABLE_MOCK === 'true';

// ---- Mock 資料 ----
const mockStats = {
  sessionsToday: 12,
  completed: 8,
  redFlags: 3,
  pendingReviews: 5,
};

const mockQueue = [
  { sessionId: 's1', patientName: '陳小明', chiefComplaint: '血尿持續三天', status: 'in_progress', waitingSeconds: 0, hasRedFlag: true },
  { sessionId: 's2', patientName: '林美玲', chiefComplaint: '頻尿、夜尿增加', status: 'waiting', waitingSeconds: 720, hasRedFlag: false },
  { sessionId: 's3', patientName: '張大偉', chiefComplaint: '排尿困難', status: 'waiting', waitingSeconds: 1500, hasRedFlag: false },
  { sessionId: 's4', patientName: '王志明', chiefComplaint: '左側腰痛伴噁心', status: 'waiting', waitingSeconds: 2340, hasRedFlag: true },
  { sessionId: 's5', patientName: '李淑華', chiefComplaint: '尿失禁', status: 'waiting', waitingSeconds: 3120, hasRedFlag: false },
];

const mockAlerts = [
  { id: 'a1', sessionId: 's1', conversationId: 'c1', alertType: 'combined' as const, severity: 'critical' as const, title: '疑似睪丸扭轉', description: '病患描述突發性單側陰囊劇痛伴噁心嘔吐，6小時內需手術介入', triggerReason: '關鍵字+語意分析', createdAt: '2026-04-10T13:45:00Z' },
  { id: 'a2', sessionId: 's4', conversationId: 'c2', alertType: 'rule_based' as const, severity: 'high' as const, title: '疑似腎絞痛', description: '左側腰痛放射至鼠蹊部，伴隨噁心、血尿，疑似泌尿道結石', triggerReason: '關鍵字匹配', createdAt: '2026-04-10T13:30:00Z' },
  { id: 'a3', sessionId: 's1', conversationId: 'c3', alertType: 'semantic' as const, severity: 'medium' as const, title: '肉眼血尿持續', description: '血尿已持續三天，需排除膀胱腫瘤可能性', triggerReason: '語意分析', createdAt: '2026-04-10T13:15:00Z' },
];

const mockRecentSessions = [
  { id: 'rs1', patientName: '黃美芳', complaint: '攝護腺症狀 (PSA 偏高)', status: 'completed' as const, time: '11:30' },
  { id: 'rs2', patientName: '吳建宏', complaint: '泌尿道感染 (反覆發作)', status: 'completed' as const, time: '10:45' },
  { id: 'rs3', patientName: '趙淑芬', complaint: '尿失禁 (壓力性)', status: 'completed' as const, time: '10:00' },
  { id: 'rs4', patientName: '周志豪', complaint: '勃起功能障礙', status: 'aborted_red_flag' as const, time: '09:15' },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<typeof mockStats | null>(IS_MOCK ? mockStats : null);
  const [queue, setQueue] = useState<typeof mockQueue>(IS_MOCK ? mockQueue : []);
  const [alerts, setAlerts] = useState<typeof mockAlerts>(IS_MOCK ? mockAlerts : []);
  const [recentSessions, setRecentSessions] = useState(IS_MOCK ? mockRecentSessions : mockRecentSessions);
  const [isLoading, setIsLoading] = useState(!IS_MOCK);

  useEffect(() => {
    if (IS_MOCK) return;

    async function loadDashboard() {
      try {
        const [statsRes, queueRes, alertsRes, sessionsRes] = await Promise.allSettled([
          dashboardApi.getDashboardStats(),
          dashboardApi.getDashboardQueue(),
          dashboardApi.getRecentAlerts(),
          dashboardApi.getRecentSessions(),
        ]);

        if (statsRes.status === 'fulfilled') {
          setStats(statsRes.value);
        }
        if (queueRes.status === 'fulfilled') {
          const q = queueRes.value;
          setQueue((q.queue ?? []).map((item) => ({
            sessionId: item.sessionId,
            patientName: item.patientName,
            chiefComplaint: item.chiefComplaint,
            status: item.status,
            waitingSeconds: item.waitingSeconds ?? 0,
            hasRedFlag: (item as unknown as Record<string, unknown>).hasRedFlag as boolean ?? false,
          })));
        }
        if (alertsRes.status === 'fulfilled') {
          // backend returns { data: RecentAlertItem[] }
          const raw = alertsRes.value as unknown as { data: Array<{ alertId: string; sessionId: string; title: string; severity: string; createdAt: string }> };
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          setAlerts((raw.data ?? []).map((a) => ({
            id: a.alertId,
            sessionId: a.sessionId,
            conversationId: a.sessionId,
            alertType: 'semantic' as const,
            severity: a.severity as 'medium',
            title: a.title,
            description: '',
            triggerReason: '',
            createdAt: a.createdAt,
          })) as unknown as typeof mockAlerts);
        }
        if (sessionsRes.status === 'fulfilled') {
          // backend returns { data: RecentSessionItem[] }
          const raw = sessionsRes.value as unknown as { data: Array<{ sessionId: string; patientName: string; chiefComplaint: string; status: string; completedAt?: string; createdAt: string }> };
          setRecentSessions((raw.data ?? []).map((s) => ({
            id: s.sessionId,
            patientName: s.patientName,
            complaint: s.chiefComplaint,
            status: s.status as 'completed' | 'aborted_red_flag',
            time: new Date(s.completedAt ?? s.createdAt).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }),
          })));
        }
      } catch {
        // 降級使用 mock
      } finally {
        setIsLoading(false);
      }
    }
    loadDashboard();
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 頁面標題 */}
      <div>
        <h1 className="text-h1 text-ink-heading dark:text-white">儀表板</h1>
        <p className="mt-1 text-body text-ink-secondary">今日問診概覽</p>
      </div>

      {/* 統計卡片 — 交錯入場動畫 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="animate-stagger-1">
          <StatCard
            title="今日問診"
            value={stats?.sessionsToday ?? 0}
            color="blue"
            trend={{ value: 15, label: '較昨日' }}
            loading={isLoading}
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
            }
          />
        </div>
        <div className="animate-stagger-2">
          <StatCard
            title="已完成"
            value={stats?.completed ?? 0}
            color="green"
            trend={{ value: 8, label: '完成率 67%' }}
            loading={isLoading}
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            }
          />
        </div>
        <div className="animate-stagger-3">
          <StatCard
            title="紅旗警示"
            value={stats?.redFlags ?? 0}
            color="red"
            onClick={() => navigate('/alerts')}
            loading={isLoading}
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            }
          />
        </div>
        <div className="animate-stagger-4">
          <StatCard
            title="待審閱"
            value={stats?.pendingReviews ?? 0}
            color="orange"
            loading={isLoading}
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            }
          />
        </div>
      </div>

      {/* 主要內容區 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 病患佇列 — 佔 2 欄 */}
        <div className="card lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-h3 text-ink-heading dark:text-white">等候佇列</h2>
            <span className="badge badge-in-progress">
              {queue.filter(q => q.status === 'in_progress').length} 進行中 · {queue.filter(q => q.status === 'waiting').length} 等待中
            </span>
          </div>
          <div className="space-y-2">
            {queue.map((item) => (
              <QueueCard
                key={item.sessionId}
                patientName={item.patientName}
                chiefComplaint={item.chiefComplaint}
                status={item.status}
                waitingSeconds={item.waitingSeconds}
                hasRedFlag={item.hasRedFlag}
                onClick={() => navigate(`/sessions/${item.sessionId}`)}
              />
            ))}
          </div>
        </div>

        {/* 右側面板 */}
        <div className="space-y-6">
          {/* 紅旗警示 */}
          <div className="card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-h3 text-ink-heading dark:text-white">紅旗警示</h2>
              <button
                className="text-caption text-primary-600 hover:text-primary-700 font-medium"
                onClick={() => navigate('/alerts')}
              >
                查看全部 →
              </button>
            </div>
            <div className="space-y-2">
              {alerts.map((alert) => (
                <AlertItem
                  key={alert.id}
                  id={alert.id}
                  title={alert.title}
                  description={alert.description}
                  severity={alert.severity}
                  createdAt={alert.createdAt}
                  isAcknowledged={false}
                  onClick={() => navigate(`/alerts/${alert.id}`)}
                />
              ))}
            </div>
          </div>

          {/* 最近完成的場次 */}
          <div className="card">
            <h2 className="mb-4 text-h3 text-ink-heading dark:text-white">最近完成</h2>
            <div className="space-y-3">
              {recentSessions.map((s) => (
                <div key={s.id} className="flex items-center justify-between py-2 border-b border-edge last:border-0 dark:border-dark-border">
                  <div className="min-w-0 flex-1">
                    <p className="text-body font-medium text-ink-heading dark:text-white truncate">{s.patientName}</p>
                    <p className="text-small text-ink-muted truncate">{s.complaint}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 ml-3">
                    <StatusBadge status={s.status} size="sm" />
                    <span className="text-tiny text-ink-muted font-tnum">{s.time}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 設計系統展示區 — 僅 Mock 模式顯示 */}
      {IS_MOCK && (
        <div className="card border-dashed border-2 border-primary-200 bg-primary-50/30">
          <h2 className="text-h2 text-ink-heading mb-4">設計系統展示</h2>

          {/* 狀態徽章 */}
          <div className="mb-6">
            <h3 className="text-h3 text-ink-heading mb-3">場次狀態</h3>
            <div className="flex flex-wrap gap-2">
              <StatusBadge status="waiting" />
              <StatusBadge status="in_progress" />
              <StatusBadge status="completed" />
              <StatusBadge status="aborted_red_flag" />
              <StatusBadge status="cancelled" />
            </div>
          </div>

          {/* 告警等級 */}
          <div className="mb-6">
            <h3 className="text-h3 text-ink-heading mb-3">告警嚴重度</h3>
            <div className="flex flex-wrap gap-2">
              <SeverityBadge severity="critical" />
              <SeverityBadge severity="high" />
              <SeverityBadge severity="medium" />
            </div>
          </div>

          {/* 按鈕 */}
          <div className="mb-6">
            <h3 className="text-h3 text-ink-heading mb-3">按鈕樣式</h3>
            <div className="flex flex-wrap gap-3">
              <button className="btn-primary">主要按鈕</button>
              <button className="btn-secondary">次要按鈕</button>
              <button className="btn-danger">危險按鈕</button>
              <button className="btn-ghost">幽靈按鈕</button>
              <button className="btn-primary" disabled>停用按鈕</button>
            </div>
          </div>

          {/* 輸入框 */}
          <div className="mb-6">
            <h3 className="text-h3 text-ink-heading mb-3">表單元件</h3>
            <div className="grid grid-cols-2 gap-4 max-w-xl">
              <input className="input-base" placeholder="搜尋病患..." />
              <input className="input-base" value="王大明" readOnly />
            </div>
          </div>

          {/* 字型展示 */}
          <div className="mb-6">
            <h3 className="text-h3 text-ink-heading mb-3">字型比例</h3>
            <div className="space-y-2">
              <p className="text-display text-ink-heading">Display 36px — 泌尿科 AI</p>
              <p className="text-h1 text-ink-heading">H1 28px — 儀表板標題</p>
              <p className="text-h2 text-ink-heading">H2 22px — 卡片標題</p>
              <p className="text-h3 text-ink-heading">H3 18px — 小節標題</p>
              <p className="text-body-lg text-ink-body">Body-L 16px — SOAP 報告正文</p>
              <p className="text-body text-ink-body">Body 14px — 預設正文內容</p>
              <p className="text-caption text-ink-secondary">Caption 13px — 標籤、徽章</p>
              <p className="text-small text-ink-muted">Small 12px — 輔助文字</p>
              <p className="text-tiny text-ink-muted">Tiny 11px — 時間戳、註腳</p>
            </div>
          </div>

          {/* 表格數字 */}
          <div>
            <h3 className="text-h3 text-ink-heading mb-3">表格數字 (tnum)</h3>
            <div className="font-tnum text-body text-ink-heading space-y-1 font-mono">
              <p>血壓: 135/85 mmHg</p>
              <p>心率: 78 bpm</p>
              <p>體溫: 36.8°C</p>
              <p>SpO2: 98%</p>
              <p>RBC: &gt;50/HPF (異常)</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
