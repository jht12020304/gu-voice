// =============================================================================
// #4 單元測試：shouldUnmuteVAD（VAD 自動恢復收音決策矩陣）
// 純函式測試，無 DOM / store / 網路依賴。
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/stores/__tests__/shouldUnmuteVAD.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { shouldUnmuteVAD } from '../conversationStore.ts';
import type { VadResumeTrigger, VadResumeContext } from '../conversationStore.ts';

const ALL_TRIGGERS: VadResumeTrigger[] = [
  'empty_stt',
  'ai_start_tts_muted',
  'ai_tts_done',
  'replay_end',
  'ws_error',
  'reconnected',
  'tts_mute_toggle',
  'user_resume',
];

/** 對照預期表：每個 trigger 在任意情境下的期望輸出。 */
function expected(trigger: VadResumeTrigger, ctx: VadResumeContext): boolean {
  // reconnected：斷線 mute 的唯一解鎖者，只被手動暫停擋下
  if (trigger === 'reconnected') return !ctx.userPaused;
  // user_resume：不得在 AI 出聲硬鎖 / 斷線時解鎖
  if (trigger === 'user_resume') return !ctx.aiTurnLocked && !ctx.wsDown;
  // W4-3 replay_end：重播播畢/中止，讓位給仍在進行中的 AI 回合硬鎖，並尊重暫停/斷線
  if (trigger === 'replay_end') return !ctx.userPaused && !ctx.aiTurnLocked && !ctx.wsDown;
  // 其餘自動恢復路徑：手動暫停優先、斷線延後到 reconnected
  return !ctx.userPaused && !ctx.wsDown;
}

// 1) 全枚舉：8 trigger × 2^3 情境組合 = 64 個斷言
let count = 0;
for (const trigger of ALL_TRIGGERS) {
  for (const userPaused of [false, true]) {
    for (const aiTurnLocked of [false, true]) {
      for (const wsDown of [false, true]) {
        const ctx: VadResumeContext = { userPaused, aiTurnLocked, wsDown };
        assert.equal(
          shouldUnmuteVAD(trigger, ctx),
          expected(trigger, ctx),
          `${trigger} × ${JSON.stringify(ctx)}`,
        );
        count++;
      }
    }
  }
}
assert.equal(count, 64, 'exhaustive matrix covers 64 combinations (8 triggers × 2^3 ctx)');

// 2) 關鍵不變式具名斷言

// (a) 手動暫停中 ai_tts_done 不 unmute（自動恢復不得覆蓋使用者暫停）
assert.equal(
  shouldUnmuteVAD('ai_tts_done', { userPaused: true, aiTurnLocked: false, wsDown: false }),
  false,
  '(a) 手動暫停中 AI 回合結束不得自動開麥',
);

// (b) AI 出聲硬鎖中 user_resume 不 unmute（回授不變式：手動繼續不得解除硬鎖）
assert.equal(
  shouldUnmuteVAD('user_resume', { userPaused: false, aiTurnLocked: true, wsDown: false }),
  false,
  '(b) AI 出聲期間手動繼續不得解鎖麥克風',
);

// (c) 暫停中 reconnected 不 unmute（重連後保持暫停，由 _connected 重申 pause 給後端）
assert.equal(
  shouldUnmuteVAD('reconnected', { userPaused: true, aiTurnLocked: false, wsDown: false }),
  false,
  '(c) 暫停中重連成功仍保持暫停',
);

// (d) 全 false 情境下 8 個 trigger 全部 unmute（無任何路徑會永久卡 mute）
for (const trigger of ALL_TRIGGERS) {
  assert.equal(
    shouldUnmuteVAD(trigger, { userPaused: false, aiTurnLocked: false, wsDown: false }),
    true,
    `(d) 無阻擋情境下 ${trigger} 必須恢復收音`,
  );
}

// (e) W4-3：重播打斷仍在串流的 AI 回合時，重播自己播畢不得搶先開麥
// （aiTurnLocked 此時反映呼叫端 pendingAiUnmuteRef || pendingReplayUnmuteRef 的 OR 結果；
// 重播鏈尾已把自己那份鎖清成 false，若 ctx 仍是 true 代表「真正」AI 回合鎖仍未釋放）。
assert.equal(
  shouldUnmuteVAD('replay_end', { userPaused: false, aiTurnLocked: true, wsDown: false }),
  false,
  '(e) 重播打斷仍在串流的 AI 回合時，重播播畢不得搶先開麥（留給該回合自己的鏈尾釋放）',
);

// (f) W4-3：重播播放期間使用者暫停，重播播畢不得自動開麥（手動暫停優先）
assert.equal(
  shouldUnmuteVAD('replay_end', { userPaused: true, aiTurnLocked: false, wsDown: false }),
  false,
  '(f) 重播播放期間使用者暫停，重播播畢不得自動開麥',
);

// (g) W4-3：無阻擋情境下重播播畢正常開麥（單純重聽舊訊息、無並行 AI 回合的常見情境）
assert.equal(
  shouldUnmuteVAD('replay_end', { userPaused: false, aiTurnLocked: false, wsDown: false }),
  true,
  '(g) 無阻擋情境下重播播畢必須恢復收音',
);

console.log('PASS shouldUnmuteVAD.test.mts (64 matrix + 6 named + 8 no-deadlock assertions)');
