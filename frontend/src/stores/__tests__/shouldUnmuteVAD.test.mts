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
  // 其餘自動恢復路徑：手動暫停優先、斷線延後到 reconnected
  return !ctx.userPaused && !ctx.wsDown;
}

// 1) 全枚舉：7 trigger × 2^3 情境組合 = 56 個斷言
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
assert.equal(count, 56, 'exhaustive matrix covers 56 combinations');

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

// (d) 全 false 情境下 7 個 trigger 全部 unmute（無任何路徑會永久卡 mute）
for (const trigger of ALL_TRIGGERS) {
  assert.equal(
    shouldUnmuteVAD(trigger, { userPaused: false, aiTurnLocked: false, wsDown: false }),
    true,
    `(d) 無阻擋情境下 ${trigger} 必須恢復收音`,
  );
}

console.log('PASS shouldUnmuteVAD.test.mts (56 matrix + 3 named + 7 no-deadlock assertions)');
