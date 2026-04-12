// =============================================================================
// 即時紅旗警示 Hook
// 結合 WebSocket 事件與 alertStore
// =============================================================================

import { useEffect } from 'react';
import { useDashboardWebSocket } from './useWebSocket';
import { useAlertStore } from '../stores/alertStore';
import type { RedFlagAlert } from '../types';
import type { NewRedFlagPayload, RedFlagAcknowledgedPayload } from '../types/websocket';

export function useRedFlagAlerts() {
  const { on, off } = useDashboardWebSocket();
  const { alerts, unacknowledgedCount, addNewAlert, fetchAlerts, fetchUnacknowledgedCount } =
    useAlertStore();

  useEffect(() => {
    // 初始載入
    fetchAlerts();
    fetchUnacknowledgedCount();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // 監聽新紅旗事件
    const handleNewRedFlag = (payload: unknown) => {
      const data = payload as NewRedFlagPayload;
      const alert: RedFlagAlert = {
        id: data.alertId,
        sessionId: data.sessionId,
        conversationId: '',
        alertType: 'combined',
        severity: data.severity,
        title: data.title,
        description: data.description,
        triggerReason: data.description,
        createdAt: new Date().toISOString(),
      };
      addNewAlert(alert);
    };

    // 監聽紅旗確認事件
    const handleAcknowledged = (payload: unknown) => {
      const data = payload as RedFlagAcknowledgedPayload;
      useAlertStore.setState((state) => ({
        alerts: state.alerts.map((a) =>
          a.id === data.alertId
            ? { ...a, acknowledgedBy: data.acknowledgedBy, acknowledgedAt: new Date().toISOString() }
            : a,
        ),
        unacknowledgedCount: Math.max(0, state.unacknowledgedCount - 1),
      }));
    };

    on('new_red_flag', handleNewRedFlag);
    on('red_flag_acknowledged', handleAcknowledged);

    return () => {
      off('new_red_flag');
      off('red_flag_acknowledged');
    };
  }, [on, off, addNewAlert]);

  return {
    alerts,
    unacknowledgedCount,
    unacknowledgedAlerts: alerts.filter((a) => !a.acknowledgedAt),
    criticalAlerts: alerts.filter((a) => a.severity === 'critical' && !a.acknowledgedAt),
  };
}
