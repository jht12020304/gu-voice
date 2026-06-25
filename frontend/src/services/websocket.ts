// =============================================================================
// WebSocket 管理器
// 支援自動重連 (指數退避)、心跳、事件監聽
// =============================================================================

import { v4 as uuidv4 } from 'uuid';
import type { WSMessage } from '../types/websocket';

type MessageHandler = (payload: unknown, message: WSMessage) => void;

/**
 * 連線狀態（供 UI 顯示連線中斷 / 重連中橫幅）。
 * - 'connecting'：初次建立連線中（尚未 open）
 * - 'open'：已連線
 * - 'reconnecting'：斷線後退避重連中
 * - 'closed'：未連線（初始 / 手動關閉 / 達重連上限）
 */
export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';

/**
 * CONV-1：重連時用來取得 resume token（checksum）的 provider。
 * 回傳的字串會以 `?resumeFrom=<token>` query param 附加到重連 URL，
 * 對齊後端 conversation_handler 讀取 `resumeFrom` query param 比對歷史 checksum 的契約。
 * 回傳空字串 / null 代表本次不帶 resume（走全新開場流程）。
 * 僅在「重連」時呼叫，初次 connect 不呼叫（初次本就無歷史可恢復）。
 */
type ResumeTokenProvider = () => Promise<string | null | undefined>;

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
  /** 目前連線狀態（供 UI 透過 _statechange 事件追蹤）。 */
  private connectionState: ConnectionState = 'closed';
  /** CONV-1：重連時取得 resume token 的 provider（僅對話 socket 設定，dashboard 不受影響） */
  private resumeTokenProvider: ResumeTokenProvider | null = null;

  constructor(options?: WebSocketManagerOptions) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  /**
   * CONV-1：註冊重連 resume token provider。
   * 設定後，每次「重連」（非初次 connect）會先呼叫 provider 取得 checksum，
   * 並以 `?resumeFrom=<checksum>` 附加到重連 URL，讓後端比對歷史連續性。
   * 傳 null 可清除（disconnect 時應清除，避免跨場次殘留）。
   */
  setResumeTokenProvider(provider: ResumeTokenProvider | null): void {
    this.resumeTokenProvider = provider;
  }

  /** 建立 WebSocket 連線 */
  connect(url: string, token: string): void {
    this.url = url;
    this.token = token;
    this.isManualClose = false;
    this.retryCount = 0;
    this.setConnectionState('connecting');
    this.createConnection();
  }

  /** 斷開連線 */
  disconnect(): void {
    this.isManualClose = true;
    this.clearTimers();
    // CONV-1：清除 resume provider，避免下一個場次沿用上一場的 checksum。
    this.resumeTokenProvider = null;
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.setConnectionState('closed');
  }

  /**
   * 手動立即重連（供 UI 的「重試」按鈕）。
   * 取消目前排定的退避重連，重設退避計數後立刻嘗試一次（會帶 resume token）。
   * 已連線時為 no-op；尚未設定過 url（從未 connect）時忽略。
   */
  retry(): void {
    if (this.isConnected || !this.url) return;
    this.clearTimers();
    this.isManualClose = false;
    this.retryCount = 0;
    this.setConnectionState('connecting');
    void this.reconnectWithResume();
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

  /** 目前連線狀態（供 UI 初始化讀取；後續變化請監聽 `_statechange`） */
  getConnectionState(): ConnectionState {
    return this.connectionState;
  }

  // ---- 內部方法 ----

  /**
   * 更新連線狀態並廣播 `_statechange` 事件（payload: { state }）。
   * 僅在狀態實際改變時才 emit，避免重複觸發 UI re-render。
   */
  private setConnectionState(state: ConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.emit('_statechange', { state });
  }

  /** 將 resume token 以 `?resumeFrom=<token>` 附加到基底 URL（已有 query 則用 &）。 */
  private buildUrl(resumeToken?: string | null): string {
    if (!resumeToken) return this.url;
    const sep = this.url.includes('?') ? '&' : '?';
    return `${this.url}${sep}resumeFrom=${encodeURIComponent(resumeToken)}`;
  }

  private createConnection(resumeToken?: string | null): void {
    // P2 #15：改用 handshake message 認證；URL 不再帶 ?token=
    // 伺服器端先 `accept()`，等 client 送第一個訊息 `{type:"auth", token:...}` 才驗證。
    // CONV-1：重連時可帶 ?resumeFrom=<checksum>，後端比對歷史連續性後跳過開場白。
    this.ws = new WebSocket(this.buildUrl(resumeToken));

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
      this.setConnectionState('open');
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
      } else {
        this.setConnectionState('closed');
      }
    };

    this.ws.onerror = () => {
      this.emit('_error', { message: 'WebSocket error' });
    };
  }

  private scheduleReconnect(): void {
    if (this.options.maxRetries > 0 && this.retryCount >= this.options.maxRetries) {
      this.setConnectionState('closed');
      this.emit('_max_retries', {});
      return;
    }

    const delay = Math.min(
      this.options.initialRetryDelay * Math.pow(2, this.retryCount),
      this.options.maxRetryDelay,
    );

    this.retryCount++;
    this.setConnectionState('reconnecting');
    this.emit('_reconnecting', { attempt: this.retryCount, delay });

    this.retryTimeout = setTimeout(() => {
      // CONV-1：重連前先取得 resume token（checksum），帶進新連線恢復狀態。
      // provider 失敗或無 token 時仍照常重連（走全新開場流程），不阻斷退避重試。
      void this.reconnectWithResume();
    }, delay);
  }

  /** 解析 resume token（若有 provider）後重新建立連線；任何錯誤都退回無 resume 重連。 */
  private async reconnectWithResume(): Promise<void> {
    // 重連途中若已被手動關閉 / 已重新連上，放棄這次重連。
    if (this.isManualClose) return;

    let resumeToken: string | null | undefined = null;
    if (this.resumeTokenProvider) {
      try {
        resumeToken = await this.resumeTokenProvider();
      } catch (err) {
        console.warn('[WS] 取得 resume token 失敗，改走全新重連:', err);
        resumeToken = null;
      }
    }

    // await 期間可能已被 disconnect()，再檢查一次避免殘留連線。
    if (this.isManualClose) return;
    this.createConnection(resumeToken);
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
