// =============================================================================
// 醫師端紅旗輪詢器（§1c 部分修，低風險版）
// 問題：紅旗 WebSocket 只綁在 AlertList/SessionList，醫師在其他頁（審 SOAP、看病患、
// 設定…）對新 critical 紅旗零信號。完整解是把 WS 提升到 app-shell 常駐，但那涉及
// 共用 singleton WS 的多消費者生命週期（off-by-name 會移除該事件所有 handler），無法
// runtime 測試、風險高。此處採低風險替代：MainLayout 常駐輪詢未處理紅旗數——
// Sidebar 徽章即時更新、數字增加即全域 toast（+ 選配音效）。近即時（≤ 輪詢間隔）、
// app-wide、零 WS 重構風險。完整 WS 常駐留作後續（需 runtime QA）。
// =============================================================================

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { useAlertStore } from '../stores/alertStore';
import { useSettingsStore } from '../stores/settingsStore';

const POLL_MS = 20000;

/** 簡易提示音（Web Audio，無需音檔）。失敗不影響視覺 toast。 */
function playBeep() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.18);
    setTimeout(() => void ctx.close(), 400);
  } catch {
    /* 音效失敗忽略 */
  }
}

export default function DoctorAlertPoller() {
  const { t } = useTranslation('dashboard');
  const fetchUnacknowledgedCount = useAlertStore((s) => s.fetchUnacknowledgedCount);
  const prevRef = useRef<number>(0);
  const initializedRef = useRef<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      await fetchUnacknowledgedCount();
      if (cancelled) return;
      const current = useAlertStore.getState().unacknowledgedCount;
      if (!initializedRef.current) {
        // 首次只記基準，不對「頁面載入時既有的未處理數」誤報。
        initializedRef.current = true;
        prevRef.current = current;
        return;
      }
      if (current > prevRef.current) {
        const delta = current - prevRef.current;
        if (useSettingsStore.getState().soundEnabled) playBeep();
        toast.error(t('alert.newAlertToast', { count: delta }), { duration: 8000 });
      }
      prevRef.current = current;
    };

    void tick();
    const id = setInterval(() => {
      if (!cancelled) void tick();
    }, POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchUnacknowledgedCount, t]);

  return null;
}
