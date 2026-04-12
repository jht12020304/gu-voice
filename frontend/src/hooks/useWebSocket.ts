// =============================================================================
// WebSocket 連線 Hook
// =============================================================================

import { useEffect, useRef, useCallback } from 'react';
import { WebSocketManager, conversationWS, dashboardWS } from '../services/websocket';
import { useAuthStore } from '../stores/authStore';
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

  useEffect(() => {
    if (!sessionId || !token) return;

    const url = `${WS_BASE}/sessions/${sessionId}/stream`;
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

  // 清理所有監聽器
  useEffect(() => {
    return () => {
      listenersRef.current.forEach((handler, type) => {
        conversationWS.off(type, handler);
      });
      listenersRef.current.clear();
    };
  }, []);

  return {
    send,
    on,
    off,
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
    return () => {
      listenersRef.current.forEach((handler, type) => {
        dashboardWS.off(type, handler);
      });
      listenersRef.current.clear();
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
