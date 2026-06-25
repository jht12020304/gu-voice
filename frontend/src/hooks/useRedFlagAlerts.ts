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

    // M-17 / H-8：連線時後端送出初始快照（initial_state）。此事件 payload 為 snake_case，
    // 與 queue_updated / stats_updated（camelCase）契約不同；這裡不直接解析 snake_case 欄位，
    // 而是以「重新載入權威資料」的最穩健作法：refetch 警示列表與未確認數，使側欄徽章與
    // 警示頁在剛連上 / 重連後即與後端對齊。
    const handleInitialState = () => {
      fetchAlerts();
      fetchUnacknowledgedCount();
    };

    // H-8：統計更新（stats_updated）通常代表別處有警示被新增 / 確認 / 場次完成，
    // 與本機未確認數可能不同步 → 重抓未確認數讓側欄徽章即時校正。
    const handleStatsUpdated = () => {
      fetchUnacknowledgedCount();
    };

    on('new_red_flag', handleNewRedFlag);
    on('red_flag_acknowledged', handleAcknowledged);
    on('initial_state', handleInitialState);
    on('stats_updated', handleStatsUpdated);

    return () => {
      off('new_red_flag');
      off('red_flag_acknowledged');
      off('initial_state');
      off('stats_updated');
    };
  }, [on, off, addNewAlert, fetchAlerts, fetchUnacknowledgedCount]);

  return {
    alerts,
    unacknowledgedCount,
    unacknowledgedAlerts: alerts.filter((a) => !a.acknowledgedAt),
    criticalAlerts: alerts.filter((a) => a.severity === 'critical' && !a.acknowledgedAt),
  };
}
