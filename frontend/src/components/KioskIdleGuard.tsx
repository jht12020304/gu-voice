// =============================================================================
// Kiosk 閒置自動登出守衛（§2a 隱私）
// 院內候診 kiosk 常態是病患「講完就走」；若不登出，上一位的姓名/主訴會殘留給
// 下一位。此守衛在病患閒置逾時後自動登出並清對話狀態，RequireAuth 隨即導回 /login。
//
// 安全設計：
// - **env 開關**：`VITE_KIOSK_IDLE_TIMEOUT_MS`（毫秒）。未設或 0 → 停用（不影響
//   非 kiosk 部署）。kiosk 於 Vercel env 設如 180000（3 分）啟用。
// - **限 patient 角色**：不對醫師/管理員套用（避免審閱中被登出）。
// - **排除 /conversation**：語音模式病患可能長時間不觸控螢幕，問診閒置由後端
//   SESSION_IDLE_TIMEOUT 處理，前端不在問診中登出。
// =============================================================================

import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { useConversationStore } from '../stores/conversationStore';

const IDLE_MS = Number(import.meta.env.VITE_KIOSK_IDLE_TIMEOUT_MS) || 0;
const RESET_EVENTS = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'] as const;

export default function KioskIdleGuard() {
  const location = useLocation();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const role = useAuthStore((s) => s.user?.role);
  const logout = useAuthStore((s) => s.logout);
  const resetSession = useConversationStore((s) => s.resetSession);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onConversation = /\/conversation\//.test(location.pathname);
  const active = IDLE_MS > 0 && isAuthenticated && role === 'patient' && !onConversation;

  useEffect(() => {
    if (!active) return;

    const doLogout = () => {
      resetSession();
      void logout(); // isAuthenticated 轉 false → RequireAuth 導回 /login
    };
    const arm = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(doLogout, IDLE_MS);
    };

    RESET_EVENTS.forEach((e) => window.addEventListener(e, arm, { passive: true }));
    arm();

    return () => {
      RESET_EVENTS.forEach((e) => window.removeEventListener(e, arm));
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [active, logout, resetSession]);

  return null;
}
