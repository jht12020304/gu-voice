// =============================================================================
// #4 單元測試：conversationStore 的 userPaused 狀態行為
// 直接 import zustand store（node --experimental-strip-types 可直測，
// 模式同 normalizeSupervisorGuidance.test.mts）。
// 執行方式：
//   cd frontend && node --experimental-strip-types \
//     src/stores/__tests__/userPausedStore.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { useConversationStore } from '../conversationStore.ts';

const store = useConversationStore;

// 1) 初始值：userPaused === false
assert.equal(store.getState().userPaused, false, '初始 userPaused 應為 false');

// 2) setUserPaused(true) → true
store.getState().setUserPaused(true);
assert.equal(store.getState().userPaused, true, 'setUserPaused(true) 後應為 true');

// 3) setUserPaused 不影響其他欄位
{
  store.getState().setSttProcessing(true);
  store.getState().setRecording(true);
  store.getState().setUserPaused(false);
  store.getState().setUserPaused(true);
  assert.equal(store.getState().sttProcessing, true, 'setUserPaused 不得影響 sttProcessing');
  assert.equal(store.getState().isRecording, true, 'setUserPaused 不得影響 isRecording');
  assert.equal(store.getState().userPaused, true);
}

// 4) resetSession() → userPaused 歸零（連同其他 session 狀態）
store.getState().resetSession();
assert.equal(store.getState().userPaused, false, 'resetSession 後 userPaused 應為 false');
assert.equal(store.getState().sttProcessing, false, 'resetSession 後 sttProcessing 應為 false');
assert.equal(store.getState().isRecording, false, 'resetSession 後 isRecording 應為 false');

console.log('PASS userPausedStore.test.mts (4 cases)');
