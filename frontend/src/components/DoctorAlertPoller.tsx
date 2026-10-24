import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { useAlertStore } from '../stores/alertStore';
import { useSettingsStore } from '../stores/settingsStore';
import { useNotificationStore } from '../stores/notificationStore';
import { useAuthStore } from '../stores/authStore';
import { useDashboardWebSocket } from '../hooks/useWebSocket';
import { coalesceRefresh } from '../utils/coalesceRefresh';
import { dashboardWS } from '../services/websocket';

const POLL_MS = 20000;

const SEEN_MAX = 500;

/** 簡易提示音（Web Audio，無需音檔）。失敗不影響視覺 toast。整個 shell 共用一顆 AudioContext。 */
let beepCtx: AudioContext | null = null;
function playBeep() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    if (!beepCtx || beepCtx.state === 'closed') beepCtx = new Ctx();
    const ctx = beepCtx;
    if (ctx.state === 'suspended') void ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.18);
    osc.onended = () => { osc.disconnect(); gain.disconnect(); };
  } catch {
    /* 音效失敗忽略 */
  }
}

// Shell-scoped realtime updates; polling is only a disconnected-socket fallback.
export default function DoctorAlertPoller() {
  const { t } = useTranslation('dashboard');
  const { on, off } = useDashboardWebSocket();
  const accountId = useAuthStore((s) => s.user?.id);
  useEffect(() => {
    let active = true;
    let lastCount: number | null = null;
    const notify = (count: number) => {
      if (useSettingsStore.getState().soundEnabled) playBeep();
      toast.error(t('alert.newAlertToast', { count }), { duration: 8000 });
    };
    const refresh = coalesceRefresh(async () => {
      await Promise.all([
        useAlertStore.getState().fetchUnacknowledgedCount(),
        useNotificationStore.getState().loaded
          ? useNotificationStore.getState().fetchNotifications(false)
          : useNotificationStore.getState().fetchUnreadCount(),
      ]);
      if (!active) return;
      const count = useAlertStore.getState().unacknowledgedCount;
      if (!dashboardWS.isConnected && lastCount !== null && count > lastCount) notify(count - lastCount);
      lastCount = count;
    });
    const events = ['initial_state', 'stats_updated', 'session_status_changed',
      'report_generated', 'red_flag_acknowledged'];
    for (const event of events) on(event, refresh.schedule);
    const seen = new Set<string>();
    on('new_red_flag', (payload) => {
      const id = (payload as { alertId?: string }).alertId;
      if (id && !seen.has(id)) {
        seen.add(id);
        // 只留最近 SEEN_MAX 筆（Set 保插入順序），避免長開的醫師端無上限成長
        if (seen.size > SEEN_MAX) seen.delete(seen.values().next().value as string);
        notify(1);
      }
      refresh.schedule();
    });
    refresh.schedule();
    const id = setInterval(() => {
      if (!dashboardWS.isConnected) refresh.schedule();
    }, POLL_MS);
    return () => {
      active = false;
      refresh.dispose();
      clearInterval(id);
      for (const event of [...events, 'new_red_flag']) off(event);
    };
  }, [accountId, on, off, t]);
  return null;
}
