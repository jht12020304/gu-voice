// =============================================================================
// 紅旗警示列表頁
// =============================================================================

import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAlertStore } from '../../stores/alertStore';
import AlertItem from '../../components/dashboard/AlertItem';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';

const FILTER_TABS = [
  { key: 'all' as const, label: '全部' },
  { key: 'unacknowledged' as const, label: '未處理' },
  { key: 'acknowledged' as const, label: '已處理' },
];

export default function AlertListPage() {
  const navigate = useNavigate();
  const { alerts, isLoading, error, filter, fetchAlerts, setFilter, acknowledgeAlert } =
    useAlertStore();

  useEffect(() => {
    fetchAlerts(true);
  }, [fetchAlerts]);

  return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="text-h1 text-ink-heading dark:text-white">紅旗警示</h1>

      {/* 篩選標籤 */}
      <div className="flex gap-2">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.key}
            className={`rounded-btn px-4 py-2 text-body font-medium transition-colors ${
              filter === tab.key
                ? 'bg-primary-600 text-white shadow-focus-ring'
                : 'btn-secondary'
            }`}
            onClick={() => setFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 錯誤 */}
      {error && <ErrorState message={error} onRetry={() => fetchAlerts(true)} />}

      {/* 列表 */}
      {!error && !isLoading && alerts.length === 0 ? (
        <EmptyState title="無警示" message="目前沒有符合條件的紅旗警示" />
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => (
            <AlertItem
              key={alert.id}
              id={alert.id}
              title={alert.title}
              description={alert.description}
              severity={alert.severity}
              createdAt={alert.createdAt}
              isAcknowledged={!!alert.acknowledgedAt}
              onAcknowledge={() => acknowledgeAlert(alert.id)}
              onClick={() => navigate(`/alerts/${alert.id}`)}
            />
          ))}
        </div>
      )}

      {isLoading && <LoadingSpinner fullPage />}
    </div>
  );
}
