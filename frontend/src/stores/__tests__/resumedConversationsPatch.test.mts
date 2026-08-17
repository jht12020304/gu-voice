// =============================================================================
// L10-7 單元測試：resumedConversationsPatch（`resume_failed` 後的逐字稿重建）
//
// 這是 ConversationPage `on('resume_failed')` 唯一的判斷邏輯——handler 本體只剩
// 「呼叫 REST → 套用這個 patch → 失敗改設 error」的編排，因此把決策抽成純函式後
// 這份測試就涵蓋了行為契約。React 端無 test runner（只有 Playwright e2e），故沿用
// 既有的純函式測試風格。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/stores/__tests__/resumedConversationsPatch.test.mts
//
// 注入式回歸（skill §測試設計 4）：把三個 streaming 暫態旗標的重設拿掉 → 案例 3 紅
// （已實測）。
//
// ⚠️ 測試層級的誠實聲明：這裡驗的是「patch 內容」。ConversationPage 裡
// `on('resume_failed') → getSessionConversations → setState(patch)` 的接線本身
// （含 off 清理）React 端沒有 test runner 可跑（只有 Playwright e2e），僅由
// type-check / lint 與讀碼把關；同一條行為的端到端斷言在 Flutter 那份
// （test/resume_failed_recovery_test.dart，注入式回歸四種都紅過）。
// =============================================================================

import assert from 'node:assert/strict';
import { resumedConversationsPatch } from '../conversationStore.ts';
import type { Conversation } from '../../types/index.ts';

function conv(over: Partial<Conversation> & Pick<Conversation, 'id' | 'contentText'>): Conversation {
  return {
    sessionId: 's1',
    sequenceNumber: 0,
    role: 'patient',
    redFlagDetected: false,
    createdAt: '2026-08-17T03:00:00Z',
    ...over,
  } as Conversation;
}

// 1) 伺服器逐字稿 → ChatMessage：欄位對映與順序都照搬，不重排、不去重
{
  const patch = resumedConversationsPatch([
    conv({ id: 'c1', role: 'assistant', contentText: '您好，請問哪裡不舒服？', sequenceNumber: 1 }),
    conv({ id: 'c2', role: 'patient', contentText: '解尿有血三天了', sequenceNumber: 2, sttConfidence: 0.91 }),
  ]);
  assert.equal(patch.conversations.length, 2);
  assert.deepEqual(
    patch.conversations.map((m) => [m.id, m.sender, m.content]),
    [
      ['c1', 'assistant', '您好，請問哪裡不舒服？'],
      ['c2', 'patient', '解尿有血三天了'],
    ],
    '順序與內容照搬伺服器版本',
  );
  assert.equal(patch.conversations[1]!.sttConfidence, 0.91);
  assert.equal(patch.conversations[0]!.timestamp, '2026-08-17T03:00:00Z');
  assert.ok(
    patch.conversations.every((m) => !m.isStreaming),
    '重建出來的訊息一律不是 streaming 狀態',
  );
}

// 2) 整批取代語意：本地的樂觀氣泡與被砍斷的 streaming 訊息不得存活
//    （這是「合併」與「取代」的分水嶺——合併會把它們永遠留在畫面上）
{
  const localBefore = [
    { id: 'c1', sessionId: 's1', sender: 'assistant', content: '您好，請問哪裡不舒服？', timestamp: 'x' },
    // 樂觀送出但後端從未收到（斷線瞬間 _ws.send 被丟棄）
    { id: 'optimistic-uuid', sessionId: 's1', sender: 'patient', content: '解尿有血三天了', timestamp: 'x' },
    // 被 _disconnected 砍斷、isStreaming 還掛著的 AI 訊息
    { id: 'stream-uuid', sessionId: 's1', sender: 'assistant', content: '請問是整泡都', timestamp: 'x', isStreaming: true },
  ];

  const patch = resumedConversationsPatch([
    conv({ id: 'c1', role: 'assistant', contentText: '您好，請問哪裡不舒服？', sequenceNumber: 1 }),
    conv({ id: 'c2', role: 'patient', contentText: '解尿有血三天了', sequenceNumber: 2 }),
  ]);
  // 模擬 `useConversationStore.setState(patch)`：patch 帶了 conversations，就整片蓋掉
  const store: { conversations: typeof localBefore } = { conversations: localBefore };
  Object.assign(store, patch);
  const next = store.conversations;

  assert.deepEqual(next.map((m) => m.id), ['c1', 'c2'], '本地列表被伺服器版本整批取代');
  assert.ok(!next.some((m) => m.id === 'optimistic-uuid'), '樂觀氣泡消失');
  assert.ok(!next.some((m) => m.id === 'stream-uuid'), '中斷的 streaming 訊息消失');
  assert.ok(!next.some((m) => m.isStreaming), '重建後沒有任何 isStreaming 殘影');
}

// 3) streaming 暫態旗標一併清掉：那一輪的 ai_response_end / stt_final 隨舊連線消失了，
//    不清就會永遠停在「AI 回應中」/「正在辨識」
{
  const patch = resumedConversationsPatch([conv({ id: 'c1', contentText: 'x' })]);
  assert.equal(patch.isAIResponding, false, 'isAIResponding 必須清掉');
  assert.equal(patch.sttProcessing, false, 'sttProcessing 必須清掉');
  assert.equal(patch.aiStreamingText, '', 'aiStreamingText 必須清掉');
}

// 4) messageId 銜接：重建後的 id 全部來自 DB（伺服器 conversation id），
//    後端 resume 失敗後續發的 ai_response_* 帶的是全新 uuid，只會 append 不會撞號
{
  const patch = resumedConversationsPatch([
    conv({ id: 'c1', role: 'assistant', contentText: 'a', sequenceNumber: 1 }),
    conv({ id: 'c2', role: 'patient', contentText: 'b', sequenceNumber: 2 }),
  ]);
  const rebuiltIds = new Set(patch.conversations.map((m) => m.id));
  const nextAiMessageId = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'; // 後端每回合現生的 uuid
  assert.ok(!rebuiltIds.has(nextAiMessageId), '新回合的 messageId 不會命中重建列表');
  const appended = [...patch.conversations, { id: nextAiMessageId, sessionId: 's1', sender: 'assistant', content: '', timestamp: 'x', isStreaming: true }];
  assert.deepEqual(appended.map((m) => m.id), ['c1', 'c2', nextAiMessageId]);
}

// 5) 伺服器回空陣列（DB 尚未落任何 turn）→ 一樣整批取代成空，不保留本地殘影
{
  const patch = resumedConversationsPatch([]);
  assert.deepEqual(patch.conversations, [], '伺服器說沒有就是沒有——伺服器是真相源');
  assert.equal(patch.isAIResponding, false);
}

console.log('PASS resumedConversationsPatch.test.mts (5 cases)');
