// =============================================================================
// WebSocket 連線 Hook
// =============================================================================

import { useEffect, useRef, useCallback, useState } from 'react';
import { WebSocketManager, conversationWS, dashboardWS } from '../services/websocket';
import type { ConnectionState } from '../services/websocket';
import { useAuthStore } from '../stores/authStore';
import { reconnectSession } from '../services/api/sessions';
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
  const token = useAuthStore((s) => s.accessToken);
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
    if (!sessionId || !token) return;

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
    conversationWS.connect(url, token);

    return () => {
      conversationWS.disconnect();
    };
  }, [sessionId, token]);

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
  const token = useAuthStore((s) => s.accessToken);
  const listenersRef = useRef<Map<string, MessageHandler>>(new Map());

  useEffect(() => {
    if (!token) return;

    const url = `${WS_BASE}/dashboard`;
    dashboardWS.connect(url, token);

    return () => {
      dashboardWS.disconnect();
    };
  }, [token]);

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
