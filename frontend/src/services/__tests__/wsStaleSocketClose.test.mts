// =============================================================================
// 單元測試：WebSocketManager 舊 socket 延後補發的 onclose 不得干擾新 socket
//
// 瀏覽器的 onclose 是非同步補發的：disconnect()→connect()（StrictMode 重掛、sessionId
// 切換）或 CONNECTING 中按重試，舊 socket 的 onclose 可能在新 socket 建立之後才到。
// 修復前它會對新 socket clearTimers() + scheduleReconnect()，長出第二條活連線。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/services/__tests__/wsStaleSocketClose.test.mts
// =============================================================================

import assert from 'node:assert/strict';

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState: number = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(_data: string): void {}

  /** 模擬瀏覽器：close() 後 onclose 要等下一個 macrotask 才補發。 */
  close(code = 1000, reason = ''): void {
    this.readyState = FakeWebSocket.CLOSED;
    setTimeout(() => this.onclose?.({ code, reason }), 0);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

(globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;

const { WebSocketManager } = await import('../websocket.ts');

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// 情境 A：disconnect() 後立刻 connect()（StrictMode 重掛 / sessionId 切換），
// 舊 socket 的 onclose 晚一步才到 → 不得排程重連、不得多開第三條連線。
{
  FakeWebSocket.instances.length = 0;
  let reconnecting = 0;
  const mgr = new WebSocketManager({ initialRetryDelay: 1, maxRetryDelay: 1 });
  mgr.on('_reconnecting', () => reconnecting++);

  mgr.connect('ws://test/sessions/A/stream', 'token');
  mgr.disconnect();
  mgr.connect('ws://test/sessions/B/stream', 'token');
  assert.equal(FakeWebSocket.instances.length, 2);
  assert.equal(mgr.getConnectionState(), 'connecting');

  await sleep(10); // 舊 socket 的 onclose 在這裡補發

  assert.equal(reconnecting, 0, '舊 socket 的 onclose 不得觸發重連');
  assert.equal(FakeWebSocket.instances.length, 2, '不得長出第三條連線');
  assert.equal(mgr.getConnectionState(), 'connecting', '新 socket 狀態不得被舊 onclose 改寫');

  FakeWebSocket.instances[1].open();
  assert.equal(mgr.isConnected, true);
  mgr.disconnect();
  console.log('情境 A（disconnect→connect 後舊 onclose 補發）：無第二條連線 — 通過');
}

// 情境 B：CONNECTING 中按「重試」→ 舊 socket 被拆 handler 並關閉，其晚到的 onclose 同樣無效。
{
  FakeWebSocket.instances.length = 0;
  let reconnecting = 0;
  const mgr = new WebSocketManager({ initialRetryDelay: 1, maxRetryDelay: 1 });
  mgr.on('_reconnecting', () => reconnecting++);

  mgr.connect('ws://test/sessions/C/stream', 'token');
  const stale = FakeWebSocket.instances[0];
  const staleClose = stale.onclose;
  mgr.retry();
  await sleep(10);

  assert.equal(FakeWebSocket.instances.length, 2, 'retry 應建立恰好一條新連線');
  assert.equal(stale.readyState, FakeWebSocket.CLOSED, '舊 socket 應被關閉');
  assert.equal(stale.onclose, null, '舊 socket 的 handler 應被拆掉');
  staleClose?.({ code: 1006, reason: '' }); // 即使有人仍握著舊 handler
  await sleep(10);
  assert.equal(reconnecting, 0);
  assert.equal(FakeWebSocket.instances.length, 2);

  mgr.disconnect();
  console.log('情境 B（CONNECTING 中 retry）：舊 socket 不再影響新 socket — 通過');
}

console.log('wsStaleSocketClose.test.mts — all assertions passed');
