// =============================================================================
// 即時紅旗警示 Hook
// 儀表板 WS 事件 → 合併刷新 alertStore（初始載入由頁面自己負責）
// =============================================================================

import { useEffect } from 'react';
import { useDashboardWebSocket } from './useWebSocket';
import { useAlertStore } from '../stores/alertStore';
import { coalesceRefresh } from '../utils/coalesceRefresh';

export function useRedFlagAlerts(): void {
  const { on, off } = useDashboardWebSocket();
  const fetchAlerts = useAlertStore((s) => s.fetchAlerts);

  useEffect(() => {
    // Counts belong to the shell. Re-fetch authoritative rows instead of applying
    // duplicate event arithmetic or inserting a row into the wrong active filter.
    const refresh = coalesceRefresh(() => fetchAlerts(false));
    const events = ['new_red_flag', 'red_flag_acknowledged', 'initial_state', 'stats_updated'];
    for (const event of events) on(event, refresh.schedule);
    return () => {
      refresh.dispose();
      for (const event of events) off(event);
    };
  }, [on, off, fetchAlerts]);
}
