// =============================================================================
// WebSocket 管理器
// 支援自動重連 (指數退避)、心跳、事件監聽
// =============================================================================

import { v4 as uuidv4 } from 'uuid';
import type { WSMessage } from '../types/websocket';

type MessageHandler = (payload: unknown, message: WSMessage) => void;

interface WebSocketManagerOptions {
  /** 初始重連延遲 (ms) */
  initialRetryDelay?: number;
  /** 最大重連延遲 (ms) */
  maxRetryDelay?: number;
  /** 心跳間隔 (ms) */
  pingInterval?: number;
  /** 最大重連次數 (0 = 無限) */
  maxRetries?: number;
}

const DEFAULT_OPTIONS: Required<WebSocketManagerOptions> = {
  initialRetryDelay: 1000,
  maxRetryDelay: 30000,
  pingInterval: 30000,
  maxRetries: 0,
};

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private url = '';
  private token = '';
  private options: Required<WebSocketManagerOptions>;
  private listeners = new Map<string, Set<MessageHandler>>();
  private retryCount = 0;
  private retryTimeout: ReturnType<typeof setTimeout> | null = null;
  private pingTimeout: ReturnType<typeof setInterval> | null = null;
  private isManualClose = false;

  constructor(options?: WebSocketManagerOptions) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  /** 建立 WebSocket 連線 */
  connect(url: string, token: string): void {
    this.url = url;
    this.token = token;
    this.isManualClose = false;
    this.retryCount = 0;
    this.createConnection();
  }

  /** 斷開連線 */
  disconnect(): void {
    this.isManualClose = true;
    this.clearTimers();
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
  }

  /** 發送訊息 */
  send(type: string, payload: unknown = {}): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] 連線未建立，無法發送:', type);
      return;
    }

    const message: WSMessage = {
      type,
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      payload: payload as Record<string, unknown>,
    };

    this.ws.send(JSON.stringify(message));
  }

  /** 註冊事件監聽 */
  on(type: string, handler: MessageHandler): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)!.add(handler);
  }

  /** 移除事件監聽 */
  off(type: string, handler: MessageHandler): void {
    this.listeners.get(type)?.delete(handler);
  }

  /** 目前是否已連線 */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  // ---- 內部方法 ----

  private createConnection(): void {
    // P2 #15：改用 handshake message 認證；URL 不再帶 ?token=
    // 伺服器端先 `accept()`，等 client 送第一個訊息 `{type:"auth", token:...}` 才驗證。
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      // 連線建立後第一件事：送 auth handshake。
      // 注意：**不走 `this.send()`**（後者會包 WSMessage 信封 `{type,id,timestamp,payload}`），
      // 這裡需要頂層 `{type:"auth", token:...}` 才對得上後端 schema。
      try {
        this.ws?.send(JSON.stringify({ type: 'auth', token: this.token }));
      } catch (err) {
        console.error('[WS] 送 auth handshake 失敗:', err);
      }
      this.retryCount = 0;
      this.startPing();
      this.emit('_connected', {});
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const message: WSMessage = JSON.parse(event.data as string);
        this.emit(message.type, message.payload, message);
      } catch {
        console.error('[WS] 訊息解析失敗:', event.data);
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      this.clearTimers();
      this.emit('_disconnected', { code: event.code, reason: event.reason });

      if (!this.isManualClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this.emit('_error', { message: 'WebSocket error' });
    };
  }

  private scheduleReconnect(): void {
    if (this.options.maxRetries > 0 && this.retryCount >= this.options.maxRetries) {
      this.emit('_max_retries', {});
      return;
    }

    const delay = Math.min(
      this.options.initialRetryDelay * Math.pow(2, this.retryCount),
      this.options.maxRetryDelay,
    );

    this.retryCount++;
    this.emit('_reconnecting', { attempt: this.retryCount, delay });

    this.retryTimeout = setTimeout(() => {
      this.createConnection();
    }, delay);
  }

  private startPing(): void {
    this.pingTimeout = setInterval(() => {
      this.send('ping', {});
    }, this.options.pingInterval);
  }

  private clearTimers(): void {
    if (this.retryTimeout) {
      clearTimeout(this.retryTimeout);
      this.retryTimeout = null;
    }
    if (this.pingTimeout) {
      clearInterval(this.pingTimeout);
      this.pingTimeout = null;
    }
  }

  private emit(type: string, payload: unknown, message?: WSMessage): void {
    const handlers = this.listeners.get(type);
    if (handlers) {
      const msg = message ?? {
        type,
        id: '',
        timestamp: new Date().toISOString(),
        payload: payload as Record<string, unknown>,
      };
      handlers.forEach((handler) => handler(payload, msg));
    }

    // 同時發送給 wildcard 監聽器
    const wildcardHandlers = this.listeners.get('*');
    if (wildcardHandlers) {
      const msg = message ?? {
        type,
        id: '',
        timestamp: new Date().toISOString(),
        payload: payload as Record<string, unknown>,
      };
      wildcardHandlers.forEach((handler) => handler(payload, msg));
    }
  }
}

// ---- 預設實例 ----

/** 語音對話 WebSocket */
export const conversationWS = new WebSocketManager();

/** 醫師儀表板 WebSocket */
export const dashboardWS = new WebSocketManager();
