// =============================================================================
// WebSocket 連線 Hook
// =============================================================================

import { useEffect, useRef, useCallback, useState } from 'react';
import { WebSocketManager, conversationWS, dashboardWS } from '../services/websocket';
import type { ConnectionState } from '../services/websocket';
import { useAuthStore } from '../stores/authStore';
import { reconnectSession } from '../services/api/sessions';
import { refreshAccessToken } from '../services/api/client';
import type { WSMessage } from '../types/websocket';

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000/api/v1/ws';

type MessageHandler = (payload: unknown, message: WSMessage) => void;

interface UseWebSocketOptions {
  /** 使用 'conversation' 或 'dashboard' 預設實例 */
  instance?: 'conversation' | 'dashboard';
  /** 自訂 WebSocket manager（不使用預設實例時） */
  manager?: WebSocketManager;
}

/**
 * 語音對話 WebSocket Hook
 */
export function useConversationWebSocket(sessionId: string | null) {
  // 只以「有無 token」gating：token 值會在每次 refresh 後輪換，若以值為 dep，
  // 問診中每次續期都會拆掉重建 WS（對話中斷）。實際 token 由 provider 取當下最新。
  const hasToken = useAuthStore((s) => !!s.accessToken);
  const listenersRef = useRef<Map<string, MessageHandler>>(new Map());
  // 連線狀態（供 ConversationPage 顯示「連線中斷／重連中」橫幅）。
  // 直接掛在 manager 上監聽 _statechange，與頁面自己的 on/off 監聽表互不干擾。
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    () => conversationWS.getConnectionState(),
  );

  useEffect(() => {
    // 同步初始狀態（避免在 effect 註冊前狀態已變動而漏掉）。
    setConnectionState(conversationWS.getConnectionState());
    const handler: MessageHandler = (payload) => {
      const next = (payload as { state?: ConnectionState })?.state;
      if (next) setConnectionState(next);
    };
    conversationWS.on('_statechange', handler);
    return () => {
      conversationWS.off('_statechange', handler);
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !hasToken) return;

    const url = `${WS_BASE}/sessions/${sessionId}/stream`;
    // CONV-1：重連時呼叫 POST /sessions/{id}/reconnect 取回歷史 checksum，
    // 當作 resume token（resumeFrom）帶進重連 URL，讓後端比對歷史連續性後跳過重複開場白。
    // 僅對話 socket 設定此 provider；dashboard / 通用 socket 不受影響。
    conversationWS.setResumeTokenProvider(async () => {
      try {
        const { checksum } = await reconnectSession(sessionId);
        return checksum || null;
      } catch (err) {
        // 取不到歷史（例如場次已結束）→ 不帶 resume，照常重連走全新流程。
        console.warn('[WS] reconnectSession 失敗，重連不帶 resume token:', err);
        return null;
      }
    });
    // §2b：對話 WS 靠 reconnectSession 的 401 觸發 client.ts refresh 續期，但若
    // refresh token 也失效，WS 會一直帶同一顆過期 token 撞 4001 無限重連、UI 永遠
    // 停在「連線中斷，重新連線中…」。比照 dashboardWS：4001 時主動 refresh（單飛去重），
    // 徹底失敗 → _auth_exhausted → logout（RequireAuth 導回 /login，停止無限重連）。
    conversationWS.setAuthFailureHandler(async () => {
      try {
        await refreshAccessToken();
        return true;
      } catch {
        return false;
      }
    });
    const handleAuthExhausted = () => {
      void useAuthStore.getState().logout();
    };
    conversationWS.on('_auth_exhausted', handleAuthExhausted);

    // token 用 provider 而非快取值：refresh 後重連 handshake 永遠拿當下最新
    // access token；token 輪換不觸發本 effect（避免問診中無謂斷線重連）。
    conversationWS.connect(url, () =>
      useAuthStore.getState().accessToken ?? localStorage.getItem('access_token'),
    );

    return () => {
      conversationWS.off('_auth_exhausted', handleAuthExhausted);
      conversationWS.disconnect();
    };
  }, [sessionId, hasToken]);

  const send = useCallback((type: string, payload?: unknown) => {
    conversationWS.send(type, payload);
  }, []);

  const on = useCallback((type: string, handler: MessageHandler) => {
    listenersRef.current.set(type, handler);
    conversationWS.on(type, handler);
  }, []);

  const off = useCallback((type: string) => {
    const handler = listenersRef.current.get(type);
    if (handler) {
      conversationWS.off(type, handler);
      listenersRef.current.delete(type);
    }
  }, []);

  // 手動立即重連（供「重試」按鈕）。
  const retry = useCallback(() => {
    conversationWS.retry();
  }, []);

  // 清理所有監聽器
  useEffect(() => {
    const listeners = listenersRef.current;
    return () => {
      listeners.forEach((handler, type) => {
        conversationWS.off(type, handler);
      });
      listeners.clear();
    };
  }, []);

  return {
    send,
    on,
    off,
    retry,
    connectionState,
    isConnected: conversationWS.isConnected,
    ws: conversationWS,
  };
}

/**
 * 儀表板 WebSocket Hook
 */
export function useDashboardWebSocket() {
  // 同 useConversationWebSocket：以「有無 token」gating + provider 取當下最新，
  // token 輪換不重建連線。
  const hasToken = useAuthStore((s) => !!s.accessToken);
  const listenersRef = useRef<Map<string, MessageHandler>>(new Map());

  useEffect(() => {
    if (!hasToken) return;

    const url = `${WS_BASE}/dashboard`;
    // F7 #3：對話 WS 靠 HTTP resume（reconnectSession）401 順帶觸發 client.ts 的
    // refresh 攔截器續期；dashboard WS 沒有對應的 HTTP 請求，token 過期後單靠
    // WS 重連會一直帶著同一顆過期 token 失敗。這裡在 manager 偵測到 4001 時
    // 主動呼叫共享的 refreshAccessToken()（內建單飛去重），成功才允許重連。
    dashboardWS.setAuthFailureHandler(async () => {
      try {
        await refreshAccessToken();
        return true;
      } catch {
        return false;
      }
    });

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
  }, [hasToken]);

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

/**
 * 通用 WebSocket Hook
 */
export function useWebSocket(options?: UseWebSocketOptions) {
  const instance = options?.instance;
  if (instance === 'conversation') {
    return { ws: conversationWS };
  }
  if (instance === 'dashboard') {
    return { ws: dashboardWS };
  }
  return { ws: options?.manager ?? null };
}
