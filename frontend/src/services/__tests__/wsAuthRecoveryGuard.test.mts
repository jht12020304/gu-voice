// =============================================================================
// 單元測試：WebSocketManager 4001 認證失敗「每連線週期至多一次刷新」防迴圈 guard
//
// 守護的不變式：後端 authenticate_websocket（backend/app/websocket/auth.py）
// 一律先 accept() 完成傳輸層 handshake，才讀取應用層 auth 訊息並驗證，驗證失敗
// 才 close(4001)——也就是說即使某次連線注定認證失敗，client 也必然先收到
// onopen 才會收到 4001。guard 因此不可在 onopen 就歸零（否則對「open 後才
// 4001」這個真實模式完全失效，見 websocket.ts hasAttemptedAuthRecovery 欄位
// 註解），必須改在「真正確認本連線週期認證已通過」（收到伺服器送出的第一筆
// 應用層訊息）時才歸零。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/services/__tests__/wsAuthRecoveryGuard.test.mts
// =============================================================================

import assert from 'node:assert/strict';

// ---- WebSocket stub：可手動觸發 onopen / 伺服器端 close(code) / 收訊息 ----
class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState: number = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(_code?: number, _reason?: string): void {
    this.readyState = FakeWebSocket.CLOSED;
  }

  /** 模擬傳輸層 handshake 完成（對應後端 accept()）。 */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** 模擬伺服器送出一則應用層訊息（代表本連線週期認證已通過）。 */
  serverSend(payload: Record<string, unknown>): void {
    this.onmessage?.({
      data: JSON.stringify({ type: payload.type, id: 'x', timestamp: '', payload }),
    });
  }

  /** 模擬伺服器端關閉連線（例如 authenticate_websocket 驗證失敗 close(4001)）。 */
  remoteClose(code: number, reason = ''): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason });
  }
}

(globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;

const { WebSocketManager } = await import('../websocket.ts');

const tick = () => new Promise((r) => setTimeout(r, 0));

// ─────────────────────────────────────────────────────────────────────────
// 情境 A（finding 的核心重現）：refresh 呼叫本身持續「成功」，但新 token
// 在 WS 端持續被拒絕（例如 rolling deploy 期間跨副本驗證不一致）。
// 修復後：只應該嘗試刷新一次，第二次 4001 就必須直接 _auth_exhausted，
// 不可無限 open→4001→refresh→reconnect。
// ─────────────────────────────────────────────────────────────────────────
{
  FakeWebSocket.instances.length = 0;
  let refreshCalls = 0;
  let authExhaustedCount = 0;

  const mgr = new WebSocketManager();
  mgr.setAuthFailureHandler(async () => {
    refreshCalls++;
    return true; // refresh 本身成功，但新 token 仍會被拒絕
  });
  mgr.on('_auth_exhausted', () => {
    authExhaustedCount++;
  });

  mgr.connect('ws://test/dashboard', () => 'token-X');

  // 第 1 次連線：open（傳輸層成功）後才 4001（應用層認證失敗）。
  const inst0 = FakeWebSocket.instances[0];
  assert.ok(inst0, '應建立第 1 次連線');
  inst0.open();
  inst0.remoteClose(4001, 'errors.ws.invalid_token');
  await tick();

  assert.equal(refreshCalls, 1, '第 1 次 4001 應觸發一次 refresh');
  assert.equal(
    FakeWebSocket.instances.length,
    2,
    'refresh 成功後應立即建立第 2 次連線（不經指數退避）',
  );

  // 第 2 次連線：同樣 open 後才 4001（新 token 依然被拒絕）。
  const inst1 = FakeWebSocket.instances[1];
  inst1.open();
  inst1.remoteClose(4001, 'errors.ws.invalid_token');
  await tick();

  assert.equal(
    refreshCalls,
    1,
    '同一連線週期第 2 次 4001 不可再觸發 refresh（防迴圈核心斷言——' +
      '修復前此處會變成 2，因為 onopen 會誤將 guard 歸零）',
  );
  assert.equal(authExhaustedCount, 1, '應該 emit 一次 _auth_exhausted 並停止重連');
  assert.equal(
    FakeWebSocket.instances.length,
    2,
    '_auth_exhausted 後不應再建立新連線',
  );

  mgr.disconnect();
  console.log('情境 A（refresh 持續成功但 token 持續被拒）：guard 正確防迴圈 — 通過');
}

// ─────────────────────────────────────────────────────────────────────────
// 情境 B：refresh 後這次真的認證成功（伺服器送出應用層訊息），之後隔了
// 一段時間才「獨立」再發生一次 4001（例如 token 自然到期）。guard 不應該
// 變成永久性的一次性開關——這次應該仍可再嘗試一次刷新。
// ─────────────────────────────────────────────────────────────────────────
{
  FakeWebSocket.instances.length = 0;
  let refreshCalls = 0;
  let authExhaustedCount = 0;

  const mgr = new WebSocketManager();
  mgr.setAuthFailureHandler(async () => {
    refreshCalls++;
    return true;
  });
  mgr.on('_auth_exhausted', () => {
    authExhaustedCount++;
  });

  mgr.connect('ws://test/dashboard2', () => 'token-Y');

  const inst0 = FakeWebSocket.instances[0];
  inst0.open();
  inst0.remoteClose(4001, 'errors.ws.invalid_token');
  await tick();
  assert.equal(refreshCalls, 1);

  const inst1 = FakeWebSocket.instances[1];
  inst1.open();
  // 這次認證真的成功：伺服器送出 initial_state（dashboard_handler 認證通過後
  // 的第一筆應用層訊息）——guard 應在此歸零。
  inst1.serverSend({ type: 'initial_state' });
  // 連線正常運作一段時間後，因獨立原因（例如 token 自然到期）再度收到 4001。
  inst1.remoteClose(4001, 'errors.ws.invalid_token');
  await tick();

  assert.equal(
    refreshCalls,
    2,
    '曾經真正驗證成功過一次後，未來獨立發生的 4001 仍應再嘗試一次刷新（非永久一次性開關）',
  );
  assert.equal(authExhaustedCount, 0, '此情境不應該 emit _auth_exhausted');

  mgr.disconnect();
  console.log('情境 B（成功驗證過一次後獨立再發生 4001）：guard 正確重新允許一次刷新 — 通過');
}

console.log('wsAuthRecoveryGuard.test.mts — all assertions passed');
