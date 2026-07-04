// =============================================================================
// F7 #3 驗證：dashboard WS 因 4001（認證失敗）斷線時，manager 應主動呼叫已註冊
// 的 authFailureHandler 續期（每個連線週期至多一次），成功才重連；刷新也失敗則
// 停止重連並發出 `_auth_exhausted`（由 useDashboardWebSocket 接手走登出）。
//
// 直接 import 專案真正的 src/services/websocket.ts（透過 ts-loader.mjs 讓 plain
// Node 能跑 TS 原始碼），並以最小的假 WebSocket 全域類別模擬瀏覽器行為，不重寫
// 一份邏輯來測——這樣才抓得到 WebSocketManager 本身的回歸。
//
// 執行方式（本檔案所在目錄）：
//   node --experimental-strip-types --import ./register.mjs dashboard-ws-auth-recovery.test.mjs
// =============================================================================

import assert from 'node:assert/strict';

// ── 假 WebSocket：不碰真實網路，記錄建立次數 + 讓測試手動觸發 open/close ──
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    FakeWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  close() {
    // 測試不模擬「manager 主動關閉」路徑，這裡只需存在避免 manager.disconnect() 報錯
    this.readyState = FakeWebSocket.CLOSED;
  }

  /** 測試 helper：模擬連線成功。 */
  _open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** 測試 helper：模擬伺服器以指定 close code 關閉連線（未曾 open 也可直接呼叫）。 */
  _serverClose(code, reason) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason });
  }

  /**
   * 測試 helper：模擬伺服器送出一則應用層訊息。
   *
   * 對應後端 authenticate_websocket（backend/app/websocket/auth.py）的真實協定：
   * 一律先 accept()（觸發 client onopen）才讀取 auth 訊息並驗證，驗證失敗只會
   * close(4001)、不會送任何訊息；換句話說，client 收到「任何」應用層訊息即代表
   * 本連線週期認證已通過（見 websocket.ts 的 hasAttemptedAuthRecovery 欄位註解）。
   * open() 本身只代表傳輸層 handshake 完成，不代表認證已過。
   */
  _serverMessage(payload) {
    this.onmessage?.({
      data: JSON.stringify({ type: payload.type, id: 'x', timestamp: '', payload }),
    });
  }
}
globalThis.WebSocket = FakeWebSocket;

const { WebSocketManager } = await import('../../src/services/websocket.ts');

function flush() {
  // 讓 microtask queue（authFailureHandler 的 await 鏈）跑完。
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const mgr = new WebSocketManager({ initialRetryDelay: 5, maxRetryDelay: 20 });

let refreshCalls = 0;
let nextRefreshSucceeds = true;
mgr.setAuthFailureHandler(async () => {
  refreshCalls++;
  return nextRefreshSucceeds;
});

let authExhaustedCount = 0;
mgr.on('_auth_exhausted', () => {
  authExhaustedCount++;
});

mgr.connect('ws://x/dashboard', () => 'tok');
assert.equal(FakeWebSocket.instances.length, 1, 'connect() 應立刻建立第一條連線');
const ws1 = FakeWebSocket.instances[0];

// ── 情境 1：連線成功後，伺服器以 4001 關閉（token 過期）──────────────
ws1._open();
ws1._serverClose(4001, 'errors.ws.invalid_token');
await flush();

assert.equal(refreshCalls, 1, '4001 應觸發一次 authFailureHandler（token 刷新）');
assert.equal(
  FakeWebSocket.instances.length,
  2,
  '刷新成功後應立即重連（建立第二條連線），不必等指數退避',
);
assert.equal(authExhaustedCount, 0, '刷新成功時不應發出 _auth_exhausted');

// ── 情境 2：重連後「尚未 open」就又被 4001 關閉（token 刷新後仍被拒絕，
//    例如帳號已停用）——防迴圈：不得再呼叫一次 authFailureHandler，
//    必須直接停止重連並發出 _auth_exhausted。 ──────────────────────
const ws2 = FakeWebSocket.instances[1];
ws2._serverClose(4001, 'errors.ws.invalid_token');
await flush();

assert.equal(
  refreshCalls,
  1,
  '同一連線週期已嘗試過一次刷新，即使又收到 4001 也不得再呼叫 authFailureHandler（防迴圈）',
);
assert.equal(
  FakeWebSocket.instances.length,
  2,
  '刷新已用盡仍失敗時不應再建立新連線',
);
assert.equal(authExhaustedCount, 1, '刷新用盡後應發出恰好一次 _auth_exhausted，交由呼叫端登出');

// ── 情境 3：之後使用者重新登入 / 手動重試，這次「真的」通過認證（伺服器送出
//    第一筆應用層訊息，例如 dashboard_handler 認證成功後的 initial_state）
//    → 旗標歸零；之後獨立發生的新 4001 仍應再嘗試一次刷新（不是永久性的
//    一次性開關）。注意：光 open() 傳輸層 handshake 完成**不足以**歸零旗標
//    ——後端 authenticate_websocket 一律先 accept()（觸發 client onopen）才
//    驗證，驗證失敗一樣會先 open 才 4001，若光 open 就歸零，guard 對這個真實
//    模式就完全失效（即本次要驗證修復的核心迴歸）。──────────────────────
mgr.retry();
assert.equal(FakeWebSocket.instances.length, 3, 'retry() 應建立新連線');
const ws3 = FakeWebSocket.instances[2];
ws3._open(); // 只是傳輸層 handshake 完成，尚不足以歸零 hasAttemptedAuthRecovery
ws3._serverMessage({ type: 'initial_state' }); // 真正通過認證 → 此刻才歸零
nextRefreshSucceeds = false; // 這次刷新本身也失敗，驗證「刷新失敗」分支會直接發 _auth_exhausted
ws3._serverClose(4001, 'errors.ws.invalid_token');
await flush();

assert.equal(refreshCalls, 2, '成功 open 過後，新的 4001 應該重新觸發一次刷新嘗試');
assert.equal(
  FakeWebSocket.instances.length,
  3,
  'authFailureHandler 本身回傳 false（刷新失敗）時不應再建立新連線',
);
assert.equal(authExhaustedCount, 2, '刷新失敗時應發出 _auth_exhausted 走登出流程');

console.log(
  'PASS: dashboard WS 對 4001 每連線週期至多刷新一次 token，成功即重連、失敗即停止並登出',
);
