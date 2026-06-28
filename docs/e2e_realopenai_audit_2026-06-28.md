# GU-Voice 真 OpenAI 本機 E2E 稽核與系統性修復計畫

> 盤點日期：2026-06-28
> 方法：本機起 docker postgres+redis、alembic migrate、uvicorn 接**真 OpenAI**（HS256、不碰生產 Supabase），
> 以 OpenAI 模擬病患（依 AI 動態提問即時作答）跑 **8 個文字問診情境**（中/英/日、良性/急症/寡言），
> 再以 12-agent workflow 對抗式驗證逐字稿 + SOAP，並對 DB ground truth 核實。
> 相關：[app_architecture.md §2.2.1](./app_architecture.md)、[system_issues_and_risks.md](./system_issues_and_risks.md)、[TODO.md](./TODO.md)
> 嚴重度：🔴 嚴重（功能失效/醫療安全） 🟡 警告（資料品質/UX） 🟢 建議

---

## 一、E2E 情境結果（8 場）

| 情境 | 語言 | 結果 | 病患回合 | SOAP | ICD-10 |
|---|---|---|---|---|---|
| dysuria（UTI） | en-US | ✅ completed | 15 | generated | N39.0, N34.1 |
| ED（良性） | zh-TW | ✅ completed | 15 | generated | —（缺漏） |
| 腎結石+血尿 | ja-JP | ✅ completed | 15 | generated | N20.0, N39.0 |
| 頻尿（寡言病患） | zh-TW | ✅ completed | 15 | generated | N40.1, N32.81 |
| PSA 篩檢 | zh-TW | ✅ completed | 15 | generated | —（缺漏） |
| 睪丸扭轉（急症） | zh-TW | ✅ aborted_red_flag | 1 | generated | N44.00 |
| 急性尿滯留（急症） | en-US | ✅ aborted_red_flag | 1 | generated | R33.8, N40.1 |
| **肉眼血尿** | en-US | ❌ **未結束（in_progress）** | **18（撞客戶端上限仍沒收尾）** | **無** | — |

**運作良好（已驗證）**：critical 急症第 1 輪即 abort 且仍產 SOAP；良性主訴收斂出 SOAP；多語內文正確在地化；
紅旗臨床判斷 8/8 合理；史taking 品質佳。

---

## 二、確認的缺陷（已對程式碼 + DB 實況核實）

### 🔴 D1 — 自動結束硬上限被紅旗 deferral 打穿 → 持續 high 紅旗的主訴問診永不結束
- **位置**：`backend/app/websocket/conversation_handler.py:1702`（收尾閘門
  `if should_conclude and not serious_red_flag_this_turn and not red_flag_drain_in_flight:`）、
  `:1698-1701`（`serious_red_flag_this_turn` 對 critical **與 high** 皆為真）、
  `:1649-1652`（critical-abort 只在 `critical`）、`:289-290`（`_should_auto_conclude` 把軟/硬合成一個 bool）、
  `app/pipelines/prompts/shared.py:298-304`（`gross_hematuria/肉眼血尿` severity=`high`，每輪再觸發、不升 critical）
- **根因**：「本輪有嚴重紅旗就延後一輪收尾」的 deferral，對「每輪都再觸發 high」的主訴（肉眼血尿最典型）變成**永久延後**；
  high 又不 abort → 軟門檻與硬上限都打不出去。`red_flag_drain_in_flight`（偵測逾時 >3.5s）也會每輪否決 → 雙重否決。
- **實證**：`hematuria_coop_en` 18 輪、18 個 high `肉眼血尿`、`final_status=null`、`session=in_progress`、**無 SOAP**，
  病患已道別兩次仍卡在客套迴圈。**3/3 對抗 reviewer 無法反駁**（信心 0.94–0.97）。這正是 #3「問不停/等不到結果」的殘留根因。
- **修法**：見 §三 A 群（A1/A2/A3）——硬上限抽成獨立旗標、閘門改純函式 `_should_conclude_now`、硬上限時對 drain 做有界 inline 解析 + 絕對 backstop。

### 🔴 D2 — `sessions.red_flag` / `red_flag_reason` 從不被對話紅旗或 aborted_red_flag 更新
- **位置**：WS 路徑用**模組級** `_update_session_status`（`conversation_handler.py:1985`，`.values(status=...)` only @`:2017`），
  critical-abort 呼叫於 `:1656`、late-drain abort 於 `:1628`；正確版 `SessionService._update_session_status`（`session_service.py:446-448`）有設 `red_flag=True` 但 WS 路徑不走它。dashboard 讀 `session.red_flag`（`dashboard_service.py:359,444`）。
- **實證（DB）**：8/8 場 `red_flag=f`，**連扭轉/尿滯留的 aborted_red_flag 也是 f** → 醫師端會漏掉對話中偵測到的急症。
- **修法**：§三 A4——compare-and-set 在轉 `aborted_red_flag` 時補 `red_flag=True, red_flag_reason=<critical title>`；WHERE 不動。
- **語意建議**：`session.red_flag` 維持「＝因紅旗中止」；high-only completed 不設 true，「曾有紅旗」改查 `red_flag_alerts` 表。

### 🔴 D3 — 紅旗非冪等：同一紅旗每輪重複偵測/持久化/廣播
- **位置**：`conversation_handler.py:1257`（每輪 detect）、`_persist_and_emit_alert`（`:1410-1503`，無任何去重）；
  `red_flag_detector.py` 的 `canonical_id`（`:280` 等）只做**單輪內**合併（`_dedup_key` `:540-545`），無跨輪去重。`red_flag_alerts.canonical_id` 欄位已存在（migration `e5f6a7b8c9d0`）。
- **實證**：肉眼血尿 18×、PSA 2× 同一 alert 重複。違反紅旗冪等不變式。
- **修法**：§三 A5——`_persist_and_emit_alert` 加跨輪去重（Redis hash `session:{id}:emitted_red_flags` 存 `canonical_id→severity`，
  **record-on-success**、**升級放行**：high→critical 必過並觸發 abort，同 severity 以下抑制）。

### 🟡 D4 — `soap_reports.language` 恆 `zh-TW`（與 session 語言不符）
- **位置**：`conversation_handler.py:1819-1832` 的 `SOAPReport(...)` 建構子**漏設** `language` 與 `icd10_verified`
  → 落到欄位 server_default `zh-TW`；Celery 參考路徑 `report_queue.py:217-218` 有設。
- **實證（DB）**：8/8 皆 `zh-TW`，連 en-US/ja-JP（內文已正確在地化）也是。
- **修法**：§三 B3——補 `language=session_context.get('language') or settings.DEFAULT_LANGUAGE`（`or DEFAULT` 是承重：
  欄位 `nullable=False`，傳 None 會 IntegrityError 被 `:1842` 誤當冪等→SOAP 靜默掉）、`icd10_verified=...`。

### 🟡 D5 — 空 AI 回應 turn（LLM 產出空字串仍送空泡泡，病患需「請再說一次」）
- **位置**：`conversation_handler.py` LLM stream 迴圈後（`:1261-1304`）未守衛空 `full_response`；
  `_SENTENCE_BOUNDARY_CHARS="。！？\n"`（`:44`）為 **CJK-only**（英/韓/越 `?` 不會被切句→空 chunk→空泡泡）。
- **實證**：肉眼血尿逐字稿出現空 assistant 訊息，病患回「I didn't hear the question」。
- **修法**：§三 A1——空回應守衛（**包 try/except** 的單次 retry，仍空就送在地化 fallback 並**直接 `_spawn_tts_task`**）。

### 🟢 D6 — ICD-10 偶發缺漏（良性主訴空陣列）
- **位置**：`icd10_validator.py`（白名單缺 `N52`/`R97`）、`icd10_symptom_map.py`（缺 ED/PSA 對應）；且 WS 路徑
  `_generate_soap_report_async` 呼叫 `generate()`（`:1793`）**沒帶 `symptom_id`** → `validate_icd10_codes` 於 `:202` short-circuit `verified=False`。
- **實證**：ED `icd10_codes=[]`（應 N52.9）、PSA `[]`（應 R97.20）。
- **修法**：§三 B1+B2——白名單/對應表加 N52/R97 + 抽共用 `resolve_symptom_id`（讀 `chief_complaint.name_en`）傳進 `generate()`。

---

## 三、系統性修復計畫（依賴排序、已對抗式審查）

> 對抗式審查修正了 3 個「原本錯誤」的假設：① WS 路徑 `verified=True` 結構上不可能（缺 `symptom_id`）；
> ② D1「硬上限一定收尾」其實假的（drain 也否決）；③ D5 retry 沒包 try/except 會跳過 `ai_response_end` → VAD 卡死。

### A 群｜紅旗/結束流程（全在 `conversation_handler.py` 同一區塊，需協調）
- **A1 [D5]** 空回應守衛：偵測 `not full_response.strip()` → 先清 in-flight TTS + reset → **包 try/except** 單次 retry
  → 仍空送 `ws.ai_empty_retry_fallback`（5 語）並**直接 `_spawn_tts_task(full_response)`**；不可 early-return（保紅旗 gate）。工：M
- **A2 [D1+D5]** `hard_cap_reached` 抽成獨立於 `should_conclude` 的旗標；閘門改純函式
  `_should_conclude_now(should_conclude, hard_cap_reached, soft_defer, drain_unresolved)`，
  `soft_defer = serious_red_flag_this_turn or used_empty_fallback`；**硬上限不被 soft_defer 否決**。工：M
- **A3 [D1]** 硬上限時對 late drain 做**有界 inline 解析**（`await wait_for(red_flag_task, HARD_CAP_DRAIN_AWAIT_SECONDS)`，
  late-critical 先 `aborted_red_flag` compare-and-set 再 conclude）；真卡死則 `MAX_HARD_CAP_DRAIN_DEFERS` 輪後強制收尾（絕對保命線）。工：L
- **A4 [D2]** 模組級 `_update_session_status` 轉 `aborted_red_flag` 時 `.values(..., red_flag=True, red_flag_reason=<title>)`；WHERE 不動。工：S
- **A5 [D3]** `_persist_and_emit_alert` 加跨輪去重（Redis hash、record-on-success、升級放行）；**不可過濾 abort 用的 `red_flag_alerts` list**。工：M

### B 群｜SOAP 持久化 / ICD-10
- **B1 [D6]** `icd10_validator` 白名單加 `N52`/`R97` + `icd10_symptom_map` 加 `erectile_dysfunction→N52`/`elevated_psa→R97`（同一 commit）。工：S
- **B2 [D6+D4]** 抽共用 `resolve_symptom_id(session_obj)`（讀 `name_en`）；`_generate_soap_report_async` 在 early-check session 內 `selectinload(chief_complaint)`，把 `symptom_id` 傳進 `generate()`。**無此步則 B1 形同死碼、verified 永遠 False**。工：M（依賴 B1）
- **B3 [D4]** `SOAPReport(...)` 補 `language=... or settings.DEFAULT_LANGUAGE`、`icd10_verified=...`。工：S（依賴 B2）

### 必守不變式（已逐條確認保住）
紅旗優先（收尾在 critical-abort 之後、硬上限 conclude 是 `in_progress→completed` compare-and-set，永不覆寫 `aborted_red_flag`）；
SOAP 冪等（只加欄位值，不新增無條件 SOAP 路徑）；VAD 不卡死（每分支保證唯一 `ai_response_end`，retry 全程吞例外）；
靜音只擋自動播放（high banner 每輪照送）；打字與語音同走 `_handle_text_message`。

### 驗證
- **單元**：`test_auto_conclude`（`_should_conclude_now` + drain 解析）、新增 `test_empty_response_fallback`（含 retry-raises / ASCII-`?` 非空 chunk）、
  `test_soap_persist_fields`（language/verified/symptom_id）、`test_icd10_validator`（N52/R97）、新增 `test_update_session_status`（aborted 才寫 red_flag）。
- **E2E（現成 driver 重跑）**：`hematuria_coop_en`（D1 證明：~15 輪 completed 出 1 份 SOAP）、慢偵測器變體（A3）、
  `torsion_critical_zh`（仍 abort + `red_flag=true`）、en/ja 場次（`soap.language` 正確）、ED/PSA（icd10 非空 + verified）。

### 新增 kill-switch（無 migration）
`HARD_CAP_DRAIN_AWAIT_SECONDS`(5.0)、`MAX_HARD_CAP_DRAIN_DEFERS`(2)、`LLM_EMPTY_RESPONSE_RETRY`(True)；既有 `HPI_COMPLETION_TERMINATION_ENABLED` 仍是總開關。

---

## 四、需產品/臨床拍板的決策（非工程問題）
1. **持續 high（肉眼血尿）現於硬上限收成 `completed`**（high 只 banner，只有 critical 才 abort）。要不要升級成 `aborted_red_flag` 分流訊號？
2. **偵測器真卡死**：撐 N 輪後強制收尾出 SOAP（接受極罕見 late-critical race），還是讓 session 一直開著、改通知 ops？
3. **`session.red_flag` 語意**：維持「＝因紅旗中止」，「曾有紅旗」改查 `red_flag_alerts`？
4. **D6 `R97` 粗粒度**：prefix-3 無法區分 R97.20(PSA)/R97.1(CA-125) → 接受並註記，還是投資 4 碼精度？是否也接受 Z12.5（攝護腺癌篩檢）？
5. **D4 歷史回填**：是否一次性 UPDATE 修正既有 ~8 筆 `soap.language` 誤標（僅 audit metadata、不違反 SOAP append-only）？

---

## 五、測試工具（session scratchpad，未進版控）
`e2e_driver.py`（OpenAI 模擬病患驅動器）、`run_all.py`（並發跑情境）、`local.env`（DB/redis 本機覆寫，配 `DATABASE_URL`/`DB_HOST=localhost` 繞過 alembic 的 Supabase SSL 強制）。
本機 JWT 為 HS256，可用 `app.core.security.create_access_token` 直接鑄 token 繞過 register 限流（`REGISTER_IP_LIMIT=5/小時`）。
