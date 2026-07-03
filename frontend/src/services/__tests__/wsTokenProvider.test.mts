// =============================================================================
// 單元測試：WebSocketManager token 來源（provider 每次重連取當下最新 token）
// 守護「帳號一直跳掉」#3 的 WS 配套：重連 handshake 不得用建構時快取的過期 token。
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/services/__tests__/wsTokenProvider.test.mts
// =============================================================================

import assert from 'node:assert/strict';

// ---- WebSocket stub：記錄 instance 與送出訊息，可手動觸發 onopen ----

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
  onmessage: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
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

  /** 模擬連線建立：設 OPEN 並觸發 onopen（manager 會在此送 auth handshake）。 */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

// 必須在 import websocket.ts 前裝好 stub（manager 的方法引用 global WebSocket）。
(globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;

const { WebSocketManager } = await import('../websocket.ts');

/** 解析某條連線 onopen 時送出的 auth handshake，回傳其 token。 */
function handshakeToken(ws: FakeWebSocket): string {
  const first = ws.sent[0];
  assert.ok(first, 'onopen 應送出 auth handshake');
  const msg = JSON.parse(first) as { type: string; token: string };
  assert.equal(msg.type, 'auth', 'handshake 頂層 type 為 auth');
  return msg.token;
}

// 1) provider 來源：初次連線 handshake 用 provider 當下回傳值
let currentToken: string | null = 'token-A';
const mgr = new WebSocketManager();
mgr.connect('ws://test/stream', () => currentToken);
const inst1 = FakeWebSocket.instances[0];
assert.ok(inst1, 'connect 應建立連線');
inst1.open();
assert.equal(handshakeToken(inst1), 'token-A', 'initial handshake uses provider value');

// 2) 重連取「當下最新」token（refresh 輪換後），非 connect 時快取
currentToken = 'token-B';
inst1.readyState = FakeWebSocket.CLOSED;
mgr.retry();
// reconnectWithResume 為 async（可能 await resume provider），讓 microtask 跑完
await new Promise((r) => setTimeout(r, 0));
const inst2 = FakeWebSocket.instances[1];
assert.ok(inst2, 'retry 應建立新連線');
inst2.open();
assert.equal(handshakeToken(inst2), 'token-B', 'reconnect handshake uses latest token');
mgr.disconnect(); // 清 ping interval，否則行程不退出

// 3) 字串來源相容（舊呼叫方式行為不變）
const mgr2 = new WebSocketManager();
mgr2.connect('ws://test/legacy', 'legacy-string');
const inst3 = FakeWebSocket.instances[2];
assert.ok(inst3, 'connect（字串）應建立連線');
inst3.open();
assert.equal(handshakeToken(inst3), 'legacy-string', 'string token source keeps old behavior');
mgr2.disconnect();

console.log('wsTokenProvider.test.mts — all assertions passed');
