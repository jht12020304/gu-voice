// =============================================================================
// 通知中心
// =============================================================================

import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import { useNotificationStore } from '../../stores/notificationStore';
import { formatDate } from '../../utils/format';

function getNotificationRoute(notification: {
  type: string;
  data?: Record<string, unknown>;
}) {
  const sessionId = typeof notification.data?.sessionId === 'string' ? notification.data.sessionId : null;
  const alertId = typeof notification.data?.alertId === 'string' ? notification.data.alertId : null;

  if (alertId) return `/alerts/${alertId}`;
  if (notification.type === 'report_ready' && sessionId) return `/reports/${sessionId}`;
  if (sessionId) return `/sessions/${sessionId}`;
  return null;
}

export default function NotificationPage() {
  const navigate = useNavigate();
  const {
    notifications,
    isLoading,
    error,
    fetchNotifications,
    markRead,
    markAllRead,
  } = useNotificationStore();

  useEffect(() => {
    fetchNotifications(true);
  }, [fetchNotifications]);

  const handleOpen = async (notification: (typeof notifications)[number]) => {
    if (!notification.isRead) {
      await markRead(notification.id);
    }

    const route = getNotificationRoute(notification);
    if (route) {
      navigate(route);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-h1 text-ink-heading dark:text-white">通知中心</h1>
          <p className="mt-1 text-body text-ink-secondary">查看紅旗警示、報告完成與系統通知</p>
        </div>
        <button className="btn-secondary" onClick={() => markAllRead()}>
          全部標示已讀
        </button>
      </div>

      {error && <ErrorState message={error} onRetry={() => fetchNotifications(true)} />}

      {isLoading ? (
        <LoadingSpinner fullPage />
      ) : notifications.length === 0 ? (
        <EmptyState title="沒有通知" message="目前沒有新的系統通知" />
      ) : (
        <div className="space-y-3">
          {notifications.map((notification) => {
            const route = getNotificationRoute(notification);
            return (
              <button
                key={notification.id}
                className={`card w-full text-left transition-colors ${
                  route ? 'card-interactive' : ''
                } ${notification.isRead ? 'opacity-80' : 'ring-1 ring-primary-200 dark:ring-primary-900'}`}
                onClick={() => handleOpen(notification)}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h2 className="text-body font-medium text-ink-heading dark:text-white">
                        {notification.title}
                      </h2>
                      {!notification.isRead && (
                        <span className="rounded-pill bg-primary-600 px-2 py-0.5 text-tiny font-semibold text-white">
                          未讀
                        </span>
                      )}
                    </div>
                    {notification.body && (
                      <p className="mt-1 text-small text-ink-muted">{notification.body}</p>
                    )}
                    <p className="mt-2 text-tiny font-tnum text-ink-muted">
                      {formatDate(notification.createdAt)}
                    </p>
                  </div>
                  {route ? (
                    <span className="shrink-0 text-small font-medium text-primary-600">
                      查看詳情
                    </span>
                  ) : null}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
