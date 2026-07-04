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

/** 每次（重）連線當下解析 access token 的 provider —— 不快取，杜絕過期 token 無限重連。 */
type TokenProvider = () => string | null;

/**
 * F7 #3：WS 因認證失敗（close code 4001）斷線時的處理 provider。
 * 對話 WS 靠 HTTP resume（POST /sessions/{id}/reconnect）401 順帶觸發 client.ts 的
 * refresh 攔截器續期；dashboard WS 沒有對應的 HTTP 請求可以「順帶」續期，故需要
 * manager 層主動偵測 4001 並呼叫此 provider（通常是呼叫 client.ts 的
 * refreshAccessToken()）。回傳 `true` 代表已成功刷新，可以立即重連；`false` 代表
 * 刷新也失敗（token 徹底失效），呼叫端應停止重連並走登出流程。
 */
type AuthFailureHandler = () => Promise<boolean>;

/** 後端 `authenticate_websocket` 所有驗證失敗情境統一使用的 close code（見
 * backend/app/websocket/auth.py）。handshake 逾時 / 格式錯誤 / token 無效皆用此碼；
 * 對 handshake 逾時之類的情境嘗試 refresh 亦無害（token 若仍有效，重連會直接成功）。
 */
const WS_AUTH_FAILURE_CLOSE_CODE = 4001;

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
  private tokenSource: string | TokenProvider = '';
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
  /** F7 #3：WS 認證失敗（4001）時的處理 provider（目前僅 dashboard socket 設定） */
  private authFailureHandler: AuthFailureHandler | null = null;
  /**
   * 本次連線週期是否已嘗試過一次「認證失敗 → 刷新 token」。
   *
   * 注意：**不可**在 `onopen` 歸零。後端 `authenticate_websocket`
   * （backend/app/websocket/auth.py）一律先 `accept()` 完成傳輸層 handshake，
   * 才讀取應用層 `{type:"auth",token}` 訊息並驗證，驗證失敗才 `close(4001)`——
   * 也就是說，就算這次連線注定認證失敗，client 也必然先收到 `onopen` 才會
   * 收到 4001。若在 `onopen` 就歸零，guard 對「open 後才 4001」這個真實模式
   * 完全失效：每次重連都會被誤判成「新週期」，導致 refresh+reconnect 無限迴圈、
   * `_auth_exhausted` 永遠不會 emit（見 onmessage 的歸零時機說明）。
   */
  private hasAttemptedAuthRecovery = false;

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

  /**
   * F7 #3：註冊 WS 認證失敗（close code 4001）時的處理 provider。
   * 設定後，收到 4001 關閉會（每個連線週期至多一次）呼叫它；成功則立即重連
   * （不走指數退避），失敗則停止重連並發出 `_auth_exhausted` 事件。
   * 傳 null 可清除（disconnect 時應清除，避免跨場次殘留）。
   */
  setAuthFailureHandler(handler: AuthFailureHandler | null): void {
    this.authFailureHandler = handler;
  }

  /** 建立 WebSocket 連線；token 可傳字串（舊行為）或 provider（每次重連重新解析）。 */
  connect(url: string, token: string | TokenProvider): void {
    this.url = url;
    this.tokenSource = token;
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
    // F7 #3：同理清除認證失敗 provider 與嘗試旗標，避免跨場次殘留。
    this.authFailureHandler = null;
    this.hasAttemptedAuthRecovery = false;
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

  /** 取「當下最新」token：provider 每次呼叫重新解析；字串來源維持舊行為。 */
  private resolveToken(): string {
    const t = typeof this.tokenSource === 'function' ? this.tokenSource() : this.tokenSource;
    return t ?? '';
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
        this.ws?.send(JSON.stringify({ type: 'auth', token: this.resolveToken() }));
      } catch (err) {
        console.error('[WS] 送 auth handshake 失敗:', err);
      }
      this.retryCount = 0;
      // 注意：**不在這裡**歸零 hasAttemptedAuthRecovery——onopen 只代表傳輸層
      // handshake 完成，後端仍可能在收到剛送出的 auth 訊息後判定失敗並 4001
      // 關閉（見欄位註解）。真正的「認證已成功」訊號改在 onmessage 判斷。
      this.startPing();
      this.setConnectionState('open');
      this.emit('_connected', {});
    };

    this.ws.onmessage = (event: MessageEvent) => {
      // F7 #3：後端 authenticate_websocket 必定「先驗證成功、才可能送出任何
      // 應用層訊息」（驗證失敗只會 close(4001)，不會送訊息）。因此收到第一筆
      // 訊息即是本連線週期認證已通過的確實訊號，才在此歸零「已嘗試過 auth
      // 刷新」旗標——讓未來獨立發生的 4001 仍可再嘗試一次刷新（不是永久性的
      // 一次性開關），同時不會被「open 後才 4001」的情境誤判成新週期。
      this.hasAttemptedAuthRecovery = false;
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

      if (this.isManualClose) {
        this.setConnectionState('closed');
        return;
      }

      // F7 #3：認證失敗（4001）且本連線週期尚未嘗試過刷新 → 交給
      // recoverFromAuthFailure() 處理（成功則立即重連，失敗則停止並登出），
      // 不落入下方一般的指數退避重連。
      if (event.code === WS_AUTH_FAILURE_CLOSE_CODE && this.authFailureHandler) {
        if (!this.hasAttemptedAuthRecovery) {
          this.hasAttemptedAuthRecovery = true;
          this.setConnectionState('reconnecting');
          void this.recoverFromAuthFailure();
          return;
        }
        // 已經刷新過一次仍被拒絕：token 刷新後依然無效（例如帳號被停用），
        // 防迴圈——不再重連，交給呼叫端監聽 `_auth_exhausted` 走登出流程。
        this.setConnectionState('closed');
        this.emit('_auth_exhausted', {});
        return;
      }

      this.scheduleReconnect();
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

  /**
   * F7 #3：處理 4001 認證失敗——呼叫 `authFailureHandler` 嘗試刷新 token。
   * 成功：重設退避計數並立即重連（token 已是新的，不需要再等退避延遲）。
   * 失敗 / 拋例外：視為刷新也救不回來，停止重連並發 `_auth_exhausted`
   * （由呼叫端決定登出流程），避免對已徹底失效的 token 無窮重試。
   */
  private async recoverFromAuthFailure(): Promise<void> {
    if (this.isManualClose || !this.authFailureHandler) return;

    let recovered = false;
    try {
      recovered = await this.authFailureHandler();
    } catch (err) {
      console.warn('[WS] 認證失敗後刷新 token 失敗:', err);
      recovered = false;
    }

    // 刷新期間可能已被手動 disconnect()，放棄本次重連。
    if (this.isManualClose) return;

    if (!recovered) {
      this.setConnectionState('closed');
      this.emit('_auth_exhausted', {});
      return;
    }

    this.retryCount = 0;
    this.createConnection();
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
