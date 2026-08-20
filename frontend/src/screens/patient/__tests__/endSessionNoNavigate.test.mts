// =============================================================================
// EM-3 防回歸：`handleEndSession` 不得自行導頁（語音管線不變式 #18 的對稱條款）
//
// 守護的行為：送出 `end_session` 之後**不能**呼叫 `navigate(...)`。
//   `services/websocket.ts` 的 `send()` 在 readyState !== OPEN 時只 console.warn 就
//   return（靜默 no-op）。導頁會卸載 ConversationPage → cleanup 跑 off()/disconnect()
//   → 那筆 end_session 永遠送不出去。後端場次卡 in_progress、SOAP 不會生成，病患卻已
//   看到「問診完成」。重連中（reconnecting/closed）按下結束鍵就是這條路徑。
//   導頁一律由後端 `session_status`（`extra.status` 帶終態）事件驅動。
//
// 為什麼用「讀原始碼字面掃描」而不是 render 測試：
//   本 repo 沒有 DOM test runner（測試一律是 node --experimental-strip-types 跑的純
//   .test.mts），而這條不變式的本質就是「這個函式體裡不准出現某個呼叫」——與後端
//   `test_end_session_status_extra.py` 的 AST/字面掃描同一思路，成本低且不會被
//   mock 得過關。
//
// 執行方式（無需 test runner）：
//   cd frontend && node --experimental-strip-types \
//     src/screens/patient/__tests__/endSessionNoNavigate.test.mts
// =============================================================================

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = resolve(HERE, '../ConversationPage.tsx');
const REPORTS_API = resolve(HERE, '../../../services/api/reports.ts');

const source = readFileSync(PAGE, 'utf8');

/**
 * 從 `marker` 之後的第一個 `{` 起做大括號配對，取出該函式/區塊的主體。
 * 會跳過字串字面（含樣板字串）與註解，避免裡頭的括號干擾配對。
 */
function extractBlockAfter(src: string, marker: string): string {
  const markerIdx = src.indexOf(marker);
  assert.notEqual(markerIdx, -1, `找不到 ${marker}——函式被改名了？請同步更新本測試`);

  const open = src.indexOf('{', markerIdx);
  assert.notEqual(open, -1, `${marker} 之後找不到函式主體的 {`);

  let depth = 0;
  let i = open;
  let quote: string | null = null;

  for (; i < src.length; i++) {
    const c = src[i];
    const next = src[i + 1];

    if (quote) {
      if (c === '\\') { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }

    // 註解
    if (c === '/' && next === '/') {
      const nl = src.indexOf('\n', i);
      i = nl === -1 ? src.length : nl;
      continue;
    }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2);
      i = end === -1 ? src.length : end + 1;
      continue;
    }

    if (c === '"' || c === "'" || c === '`') { quote = c; continue; }

    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) return src.slice(open, i + 1);
    }
  }

  assert.fail(`${marker} 的大括號未配對成功`);
}

// ── 1. handleEndSession 內不得出現 navigate( ────────────────────────────────
{
  const body = extractBlockAfter(source, 'const handleEndSession');

  assert.ok(
    !/\bnavigate\s*\(/.test(body),
    'handleEndSession 內出現了 navigate(...)：不變式 #18 對稱條款——送出 end_session 後' +
      '不得自行導頁（導頁會讓 WS 在指令送達前被 disconnect，場次永遠卡 in_progress）。' +
      '導頁請交給 on(\'session_status\') 收到終態時處理。',
  );

  // 真的有把指令送出去（避免「為了讓測試過就把 send 也刪掉」）
  assert.ok(
    /send\s*\(\s*['"]control['"]\s*,\s*\{\s*action:\s*['"]end_session['"]/.test(body),
    'handleEndSession 沒有送出 end_session 控制訊息',
  );

  // send() 非 OPEN 時靜默丟棄 → 必須先擋下並給使用者可見回饋（不變式 #6）
  assert.ok(
    /connectionState\s*!==\s*['"]open['"]/.test(body),
    'handleEndSession 未檢查 connectionState：send() 在非 OPEN 時是靜默 no-op，' +
      '不擋下來病患會以為已送出（不變式 #6：不得靜默吞掉）',
  );
  assert.ok(
    /setError\s*\(/.test(body),
    'handleEndSession 的未連線分支沒有給使用者可見回饋（setError）',
  );

  // 防連點：送出後進入「結束中」disabled 狀態
  assert.ok(
    /setIsEndingSession\s*\(\s*true\s*\)/.test(body),
    'handleEndSession 沒有進入「結束中」狀態，重複點擊會送出多筆 end_session',
  );

  console.log('EM-3-1：handleEndSession 不導頁、送指令、非 OPEN 有可見回饋、有防連點 — 通過');
}

// ── 2. 導頁仍由 session_status 終態事件驅動 ─────────────────────────────────
{
  const handlerIdx = source.indexOf("on('session_status'");
  assert.notEqual(handlerIdx, -1, "找不到 on('session_status') handler");
  const body = extractBlockAfter(source.slice(handlerIdx), 'payload) =>');

  assert.ok(
    /data\.status\s*===\s*['"]completed['"]/.test(body) && /\bnavigate\s*\(/.test(body),
    "session_status handler 必須在 status === 'completed' 時導向感謝頁——" +
      'handleEndSession 已不導頁，這裡是唯一的正常結束導頁路徑',
  );

  console.log('EM-3-2：session_status 終態事件仍負責導頁 — 通過');
}

// ── 3. 結束鍵在「結束中」時 disabled ────────────────────────────────────────
{
  assert.ok(
    /onClick=\{handleEndSession\}[\s\S]{0,200}?disabled=\{isEndingSession\}/.test(source),
    '結束問診按鈕未在 isEndingSession 時 disabled（防連點）',
  );
  assert.ok(
    source.includes("t('conversation:endSessionPending')"),
    '結束中狀態沒有使用 conversation:endSessionPending 文案',
  );

  console.log('EM-3-3：結束問診按鈕於送出後 disabled 並顯示「結束中」 — 通過');
}

// ── 4. SO-2：generateReport 必須帶 { regenerate: true } body ────────────────
{
  const reportsSrc = readFileSync(REPORTS_API, 'utf8');
  const body = extractBlockAfter(reportsSrc, 'export async function generateReport');

  assert.ok(
    /reports\/generate`\s*,\s*\{/.test(body),
    'generateReport 的 POST 沒有帶 body：後端 ReportGenerateRequest 需要 body，' +
      '舊寫法完全不帶（SO-2）',
  );
  assert.ok(
    /regenerate:\s*true/.test(body),
    'generateReport 的 body 沒有 { regenerate: true }（SO-2）',
  );

  console.log('SO-2：reports API generateReport 帶 { regenerate: true } body — 通過');
}

// ── 5. SO-2：「重新產生」在 generated / failed 可用，generating 期間 disabled ──
{
  const soapPage = readFileSync(
    resolve(HERE, '../../doctor/SOAPReportPage.tsx'),
    'utf8',
  );

  const btnIdx = soapPage.indexOf('setShowRegenerateModal(true)');
  assert.notEqual(btnIdx, -1, '找不到「重新產生」按鈕的 onClick');
  // 取按鈕標籤前後一段（disabled 屬性就在 onClick 附近）
  const around = soapPage.slice(Math.max(0, btnIdx - 400), btnIdx + 400);

  assert.ok(
    /disabled=\{isRegenerating \|\| report\.status === 'generating'\}/.test(around),
    '「重新產生」的 disabled 條件不對：generating 期間必須擋（再送只會疊出第二個 Celery ' +
      '工作），而 failed 與 generated 都必須可按——failed 正是最需要重跑的狀態（SO-2）',
  );
  // 反向：不得用 status !== 'generated' 把 failed 一起擋掉
  assert.ok(
    !/disabled=\{[^}]*report\.status !== 'generated'[^}]*\}[\s\S]{0,120}setShowRegenerateModal/.test(
      soapPage,
    ),
    '「重新產生」不得以 status !== generated 為 disabled 條件（會把 failed 擋掉）',
  );

  console.log('SO-2：重新產生按鈕於 generating 期間 disabled、failed/generated 可用 — 通過');
}

console.log('endSessionNoNavigate.test.mts — all assertions passed');
