// =============================================================================
// WebSocket 連線 Hook
// =============================================================================

import { useEffect, useRef, useCallback } from 'react';
import { dashboardWS } from '../services/websocket';
import { useAuthStore } from '../stores/authStore';
import { refreshAccessToken, isAuthRejected } from '../services/api/client';
import type { WSMessage } from '../types/websocket';

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000/api/v1/ws';

type MessageHandler = (payload: unknown, message: WSMessage) => void;

/**
 * WS 4001（認證失敗）時的共用處理：主動 refresh（client.ts 單飛去重）。
 * 回 true＝已續期可立即重連；回 false＝憑證徹底失效（呼叫端走登出）；
 * 其他例外（暫時性故障）往上拋，讓 manager 按退避重試並保留登入。
 */
async function refreshOrReject(): Promise<boolean> {
  try {
    await refreshAccessToken();
    return true;
  } catch (error) {
    if (isAuthRejected(error)) return false;
    throw error; // transient outage: reconnect with backoff, keep authentication
  }
}

/**
 * 儀表板 WebSocket Hook
 */
export function useDashboardConnection() {
  // 只以「有無 token」gating：token 值每次 refresh 後輪換，以值為 dep 會反覆拆建連線；
  // 實際 token 由 provider 取當下最新。
  const hasToken = useAuthStore((s) => !!s.accessToken);
  const accountId = useAuthStore((s) => s.user?.id);

  useEffect(() => {
    if (!hasToken || !accountId) return;

    const url = `${WS_BASE}/dashboard`;
    // F7 #3：對話 WS 靠 HTTP resume（reconnectSession）401 順帶觸發 client.ts 的
    // refresh 攔截器續期；dashboard WS 沒有對應的 HTTP 請求，token 過期後單靠
    // WS 重連會一直帶著同一顆過期 token 失敗。這裡在 manager 偵測到 4001 時
    // 主動呼叫共享的 refreshAccessToken()（內建單飛去重），成功才允許重連。
    dashboardWS.setAuthFailureHandler(refreshOrReject);

    // manager 端已限制「每次斷線至多一次 refresh 嘗試」；刷新仍失敗代表 token
    // 徹底失效（例如帳號被停用 / refresh token 也已過期），停止重連並登出
    // ——ProtectedRoute 會在 isAuthenticated 轉 false 時自動導回登入頁。
    const handleAuthExhausted = () => {
      void useAuthStore.getState().logout();
    };
    dashboardWS.on('_auth_exhausted', handleAuthExhausted);

    dashboardWS.connect(url, () =>
      useAuthStore.getState().accessToken ?? localStorage.getItem('access_token'),
    );

    return () => {
      dashboardWS.off('_auth_exhausted', handleAuthExhausted);
      dashboardWS.disconnect();
    };
  }, [hasToken, accountId]);

}

// Pages own listeners only. MainLayout owns the authenticated connection.
export function useDashboardWebSocket() {
  const listenersRef = useRef<Map<string, MessageHandler>>(new Map());

  const send = useCallback((type: string, payload?: unknown) => {
    dashboardWS.send(type, payload);
  }, []);

  const on = useCallback((type: string, handler: MessageHandler) => {
    listenersRef.current.set(type, handler);
    dashboardWS.on(type, handler);
  }, []);

  const off = useCallback((type: string) => {
    const handler = listenersRef.current.get(type);
    if (handler) {
      dashboardWS.off(type, handler);
      listenersRef.current.delete(type);
    }
  }, []);

  // 清理所有監聽器
  useEffect(() => {
    const listeners = listenersRef.current;
    return () => {
      listeners.forEach((handler, type) => {
        dashboardWS.off(type, handler);
      });
      listeners.clear();
    };
  }, []);

  return {
    send,
    on,
    off,
    isConnected: dashboardWS.isConnected,
    ws: dashboardWS,
  };
}
