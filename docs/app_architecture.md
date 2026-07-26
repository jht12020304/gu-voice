# 泌尿科 AI 語音問診助手 — 系統架構設計

## 1. 產品概述

一款以語音對話為核心的泌尿科 AI 問診助手，協助醫師在門診前或門診中，透過 LLM 與病患進行結構化問診，自動產出 SOAP 報告、建議檢查項目及臨床推論，並於急性症狀出現時即時發出紅旗警示。

---

## 2. 核心功能模組

### 2.1 主訴選擇模組

```
┌─────────────────────────────────────┐
│         主訴選擇畫面                  │
│                                     │
│  ┌───────────┐  ┌───────────┐      │
│  │  血尿      │  │  頻尿      │      │
│  └───────────┘  └───────────┘      │
│  ┌───────────┐  ┌───────────┐      │
│  │  排尿困難   │  │  腰痛      │      │
│  └───────────┘  └───────────┘      │
│  ┌───────────┐  ┌───────────┐      │
│  │  尿失禁    │  │  陰囊腫痛   │      │
│  └───────────┘  └───────────┘      │
│  ┌───────────┐                     │
│  │ ＋ 自訂主訴 │                     │
│  └───────────┘                     │
└─────────────────────────────────────┘
```

- 預設常見泌尿科主訴清單（血尿、頻尿、排尿困難、腰痛、尿失禁、陰囊腫痛、PSA 異常等）
- 支援醫師自訂新增主訴
- 選擇後進入語音對話流程
- **主訴可複選（2026-06-26）**：協助 narrow down 鑑別診斷。後端 `chief_complaint_id` 仍是
  單一必填 FK → 取「第一個選的」當 primary，其餘選項名稱（+ 補充說明）合併進
  `chief_complaint_text`（後端 `String(200)`，LLM/Supervisor/SOAP/紅旗偵測實際吃的內容），
  故**無需 DB migration**。前端以 code-point 為單位嚴格 ≤200 字、選取時 `NAME_BUDGET`
  擋名稱總長，確保症狀名稱**永不被中途截斷**（否則醫師端/SOAP/紅旗會漏掉次要主訴 →
  under-triage）。實作見 `frontend/src/screens/patient/SelectComplaintPage.tsx`。
- **「其他」選項（2026-07-04，使用回饋 #5，`e43144f`）**：預設清單涵蓋不了的症狀走「其他」
  sentinel 主訴（固定 UUID `00000000-0000-4000-8000-0000000000ff`，seed migration
  `20260704_1000`，前後端常數同步）——FK 由 sentinel 滿足、實際主訴內容在
  `chief_complaint_text`（病患自述；**含「其他」時自述必填**，且合併文字排除字面「其他」
  佔位詞，否則「其他」訊號會完全消失）。開場語由 `_resolve_chief_complaint_display`
  特判 sentinel 改念病患自述（否則 AI 會說「關於您的『其他』…」）。已知 graceful 退化：
  該場次 ICD-10 `unverified`、對話紅旗提示退回全量清單（更保守、不漏）。

---

### 2.2 語音對話模組

```
┌──────────────────────────────────────────────────────┐
│                    語音對話流程                         │
│                                                      │
│   病患端               系統                 LLM       │
│     │                   │                   │        │
│     │── 語音輸入 ──────▶│                   │        │
│     │                   │── STT 轉文字 ────▶│        │
│     │                   │                   │        │
│     │                   │◀─ 生成追問 ───────│        │
│     │                   │                   │        │
│     │                   │── 紅旗偵測 ──┐    │        │
│     │                   │              │    │        │
│     │                   │   ┌──────────▼─┐  │        │
│     │                   │   │ 急性症狀？  │  │        │
│     │                   │   │  Y → 中斷   │  │        │
│     │                   │   │  N → 繼續   │  │        │
│     │                   │   └────────────┘  │        │
│     │                   │                   │        │
│     │◀── TTS 語音回覆 ──│                   │        │
│     │                   │                   │        │
└──────────────────────────────────────────────────────┘
```

- **STT（Speech-to-Text）**：將病患語音即時轉為文字
- **LLM 對話引擎**：根據主訴 + 歷史對話脈絡，生成結構化追問
- **TTS（Text-to-Speech）**：將 LLM 回覆轉為語音播出
- **紅旗即時偵測**：每輪對話同步偵測急性症狀關鍵字與語意

#### 2.2.1 實作補充與不變式（2026-06-26 — 病患語音 UX）

**語音輸入擷取**（`frontend/src/services/audioStream.ts`）
- 能量式 VAD（RMS）自動切段：`minSpeechMs`=90（確認開始說話）、`silenceEndMs`=2000
  （停頓視為講完）、barge-in 門檻 0.06（AI 說話時可大聲打斷）。
- **#1 句首截斷的真正解 = pre-roll 連續擷取**，藏在 build-time flag `VITE_VAD_PREROLL`
  **後、預設關**：ON 時用 ScriptProcessor tap 持續把 PCM 寫進 ring buffer，開口瞬間回頭取
  ~0.4s pre-roll，整段（pre-roll + 現場）編成**單一 WAV**送出（繞過 MediaRecorder/WebM 分段；
  後端 magic-byte 嗅測接受 WAV）。WAV header 須用**實際** `audioContext.sampleRate`（非
  getUserMedia 的 16000 hint）否則 Whisper 會變調。**OFF 時與原行為 byte-identical**；任何
  tap/編碼失敗都 fallback 回 per-utterance MediaRecorder。**啟用前須真實麥克風驗 STT**（句首
  是否補回、解碼品質、iOS ScriptProcessor 相容、低階機 payload/記憶體）。
- **打字輸入備援**：WS 新增 `text_message`（後端 `conversation_handler` 主迴圈），不走 STT 但
  與語音走同一條 `_handle_text_message`（紅旗篩檢 / LLM / auto-conclude 一視同仁）。斷線時前端
  不假裝送出（保留草稿、按鈕 disabled），避免症狀陳述跳過紅旗篩檢被丟棄。

**AI 語音輸出控制**（`ConversationPage.tsx` + `settingsStore`）
- 靜音 / 語速（前端 `playbackRate` 1.0/1.25/1.5，不改後端）/ 每則訊息播放鍵，偏好持久化。
- **不變式（醫療安全）**：靜音只擋「自動播放」；AI 文字與紅旗 banner 與 TTS 音訊**完全解耦**，
  永遠看得到。靜音時 `unmuteVAD()` 必須在**每條** `ai_response_end` 分支觸發，否則病患會被
  靜音鎖住、無法再開口。空 STT（Whisper 沒聽出字）時前端須 re-arm VAD（同上理由）。

**手動語音控制與辨識回饋（2026-07-04 — 使用回饋 #4/#6，`eb4993e`）**
- 新增**暫停/繼續鈕**（muteVAD/unmuteVAD + WS `control` `pause_recording`/`resume_recording`
  同步後端忽略音訊；暫停中常駐 amber 徽章）與**「我說完了」鈕**（`forceEndSegment()` 立即
  切段送出，不等 2s 靜音——病患思考停頓不再被迫等自動切段）。
- **不變式：unmute 一律走 `shouldUnmuteVAD` 純函式決策矩陣**（`conversationStore.ts`，56 案例
  矩陣測試 `shouldUnmuteVAD.test.mts`）：`userPaused`（手動暫停）與 AI 出聲硬鎖
  （`pendingAiUnmuteRef`）是**兩個獨立閘**——手動暫停不被 `ai_response_end` 的自動解鎖覆蓋；
  手動繼續不得解除 AI 出聲硬鎖與斷線 mute。`ConversationPage` 八個 unmute/mute 掛點全走
  此矩陣，新增播放/連線路徑時不可繞過。
- **不變式：`stopActiveTTS` 取下 `onended` 後必須手動補呼叫一次**——句級 TTS 佇列的 step
  promise 靠 `onended` resolve，否則鏈尾（唯一負責清硬鎖＋恢復收音者）永不執行 → 重播鍵
  會讓 VAD 永久卡死（對抗式 review 揪出，已修）。斷線（`_disconnected`）要**先停本地 TTS
  再 mute**，重連解鎖時喇叭必須已無 AI 語音（回授安全）。
- **辨識回饋**：`sttProcessing` 期間麥克風圈疊 spinner＋醒目徽章（原僅一行小灰字，病患
  以為沒錄進去）；**空 `stt_final` 不再靜默**——顯示「沒聽清楚，請再說一次」提示（4 秒
  自動消失、暫停中不顯示）並照舊 re-arm VAD。

**問診自動結束**（`conversation_handler.py`，修 #3「問診不會結束」；2026-06-29 調為「平衡 8-10 題」）
- **軟門檻**：Supervisor HPI 完整度 ≥ `HPI_COMPLETION_TERMINATION_THRESHOLD`(80) 且病患回合
  ≥ `MIN_PATIENT_TURNS_BEFORE_AUTO_END`(5)；**硬上限 backstop**：回合 ≥
  `MAX_PATIENT_TURNS_HARD_CAP`(10) 強制收尾，**不依賴 Supervisor**（降級寫 fallback hpi=0 時
  軟門檻永不觸發 → 硬上限才是「等不到結果」的真正保命線）。總開關
  `HPI_COMPLETION_TERMINATION_ENABLED`。舊值 85/4/15 因軟門檻幾乎不觸發、benign 全撐到 15 題，
  病患回報「AI 一直問、等不到自動結束」，故下調；`supervisor.py` 並補 hpi_completion 誠實評分準則。
- **don't-know 第三態（2026-07-04，使用回饋 #2「換句話重問」，`40c2f42`）**：Supervisor prompt
  明定「病患已表示不知道／記不得／無法回答的欄位＝已盡力採集」——移出 `missing_hpi`、
  `next_focus` 不再指向、完成度不因此壓低；兩處防重問護欄（問診準則 +
  `supervisor_guidance_no_repeat`，5 語）擴充涵蓋 don't-know 並升級為硬性護欄。修前整套
  機制只認「已明確回答」二元狀態：don't-know 欄位讓完成度卡在 80 以下、軟門檻永不觸發，
  AI 換句話重問到硬上限。
- **不變式（醫療安全）**：自動結束區塊放在**紅旗 gate 之後**且 critical/high 紅旗當輪不收尾；
  `_update_session_status` 採 **compare-and-set**（只在仍 `in_progress` 才轉 `completed`），
  避免把 `aborted_red_flag` 降級；`_generate_soap_report_async` 早期存在性檢查 +
  `soap_reports.session_id` UNIQUE → 任何結束路徑都不會重複報告。
- **2026-07-19 架構修復（P0 三件）**：
  - **WS row-level 授權**：問診 WS 於 `_validate_session` 後、connect 前必過
    `_authorize_ws_session_access`（與 REST `_authorize_session_access` 同模型：admin／
    指派醫師或未指派／本人病患），未授權回與不存在相同的 4004（不洩漏場次存在性）。
    先前 WS 只驗 JWT 不驗擁有權（IDOR）。
  - **紅旗與場次狀態事件跨行程橋接**：`new_red_flag` 與 `broadcast_localized_dashboard`
    （session_status_changed 等）改走 `broadcast_dashboard_event`（Redis publish→各行程
    subscriber→本地 fan-out）。生產 4 個 uvicorn worker 行程，舊 in-memory broadcast 只有
    同行程醫師收得到即時紅旗（3/4 機率漏接）。
  - **SOAP 生成單一路徑（耐久）**：`_generate_soap_report_async` 改為「建 GENERATING row →
    派 Celery `generate_soap_report`」純觸發器；生成本體只在 `tasks/report_queue`
    （acks_late + retry ×2 + on_failure 標 FAILED + `report_generated` 事件 + REPORT_READY
    通知）。舊 inline 生成在行程重啟時無聲消失且無 FAILED 可追，並與 Celery 重生路徑
    存在 transcript／summary 漂移；單一路徑後一併消滅。**部署前提：celery worker 必須在跑**
    （本機 e2e 也要起 worker）。
- **2026-07-19 架構後續（refactor followups）**：
  - **狀態機單一權威**：`VALID_TRANSITIONS` 與 `is_valid_transition()` 抽到
    `app/core/session_state.py`，REST（`update_status_static`，嚴格）與 WS
    （`_update_session_status`，`allow_noop=True` 放行 resume 的 in_progress→in_progress
    自轉移）共用同一份規則。先前 WS 只靠 compare-and-set 的 WHERE 擋、不查轉移表，
    可執行表外轉移；現在送 DB 前先擋、非法轉移 log warning 後 no-op（不 raise）。
  - **god file 拆分**：自動結束政策（6 純函式）→ `app/pipelines/conclusion_policy.py`、
    紅旗跨輪去重（3 函式）→ `app/pipelines/alert_dedup.py`；conversation_handler 以
    底線別名 re-import 保持既有呼叫端與測試相容（行為零變更，e2e 驗證）。
  - **JWT 遷移**：python-jose（停維護，CVE-2024-33663/33664）→ PyJWT 2.12.1，
    `jwt.decode` 顯式 `algorithms=[JWT_ALGORITHM]` 白名單防演算法混淆。
  - **Redis 連線單一權威**：`dependencies.get_redis` 收斂為 re-export
    `cache/redis_client.get_redis`，消滅兩套並存連線池單例。
- **§3b 高風險主訴風險因子必問（2026-07-06，PR#29，真實 e2e 血尿/ED 各 2/2）**：血尿/PSA/ED 的關鍵
  風險因子（吸菸/抗凝血/泌尿癌家族史；ED 心血管/糖尿病/吸菸）升為與 HPI 十欄同級必問
  （`shared.CRITICAL_RISK_FACTORS`，多語聯集、明確匹配才注入）。收尾邏輯對這類主訴（K=風險因子
  題數）動態調整，缺一不可：
  - **動態硬上限**：effective cap = `MAX_PATIENT_TURNS_HARD_CAP` + K + `RISK_FACTOR_HARD_CAP_BUFFER`(2)
    （K>0 才加；血尿/ED 10→15）。base=10 連 opening+HPI 十欄都塞不下，風險因子必被砍。
  - **確定性軟門檻下限**：K>0 主訴 soft-conclude 需病患回合 ≥ base+K-1(12)——作 supervisor gate
    （LLM，偶發只問到 1/K 就早放行 hpi≥80）的**語言無關 backstop**。
  - **極簡收尾 prompt**：收尾輪改用 `build_wrap_up_prompt`（只留輸出語言+角色+收尾規則，**移除整個
    HPI/次要/風險因子 questioning 框架**）且**跳過 supervisor next_focus 注入**——單靠強化文案+前後
    夾擊壓不住 LLM 在收尾輪硬問一題（實測 ED 反覆問次要用藥、留懸空問句），移除競爭指令才可靠。
  - **一致性陷阱**：`_session_risk_factor_count` 必須用 **raw `chief_complaint`**（非 display）——
    build_system_prompt/supervisor §3b 注入都用 raw，ED 的 display 漂移為 K=0 會讓 cap/floor gating
    與注入端矛盾漏問。另強化 supervisor gate 為逐項嚴格（任一未問到回報 60、next_focus 指向該項）。
    e2e 場景在 `scripts/e2e_realopenai/driver.py`（hematuria_3b_en/ed_3b_zh + analyzers）。
- **D1–D6 已修復（2026-07-04，`a92a23f`，真 OpenAI E2E 驗收 13/13 PASS）**：原「critical/high 紅旗
  當輪不收尾」的 deferral 對每輪再觸發 high 的主訴（肉眼血尿）會永久延後收尾。修復後的不變式：
  - **硬上限不再被紅旗 deferral 否決**：收尾閘門是純函式 `_should_conclude_now(should_conclude,
    hard_cap_reached, soft_defer, drain_unresolved)`——軟門檻仍可被 `soft_defer`（當輪嚴重紅旗或
    空回應 fallback）延後，**硬上限不行**；硬上限遇未解析 drain 走**有界 inline 解析**
    （`HARD_CAP_DRAIN_AWAIT_SECONDS`，late-critical 先 abort 再收尾），偵測器真卡死則
    `MAX_HARD_CAP_DRAIN_DEFERS` 輪後強制收尾出 SOAP（絕對保命線）。
  - **紅旗跨輪冪等（A5）**：`_persist_and_emit_alert` 以 Redis hash（canonical_id→severity）
    去重，record-on-success、high→critical 升級放行、Redis 失效 fail-open；
    **abort 判斷用的 alerts list 不過濾**（被抑制的 critical 仍照常 abort）。
  - **`sessions.red_flag` 持久化（A4）**：轉 `aborted_red_flag` 時補寫 `red_flag=True` +
    `red_flag_reason`；語意＝「因紅旗中止」，high-only completed 不設 true（曾有紅旗查
    `red_flag_alerts`）。
  - **空回應守衛（A1/D5）**：LLM 空串流 → try/except 單次 retry → 仍空送
    `ws.ai_empty_retry_fallback`（5 語）並直接 `_spawn_tts_task`；每分支唯一 `ai_response_end`。
  - **SOAP metadata（B 群/D6）**：`soap.language` 一律 `SOAP_REPORT_LANGUAGE`（固定 zh-TW，
    2026-07-19 產品決策——報告讀者是中文醫護，取代舊 D4「跟場次語言」；常數保證
    nullable=False 欄位絕不收 None，舊 fallback 防的 IntegrityError 路徑免疫）；
    問診對話與病患端 WS 訊息仍走場次語言。WS 路徑補傳 `symptom_id` 使
    `icd10_verified` 真的可為 true；ICD 白名單含 N52/R97（R97 接受 prefix-3 粗粒度）。
  - E7 臨床決策採保守預設（high 不升級 abort 等，見 TODO §E E7），kill-switch：
    `LLM_EMPTY_RESPONSE_RETRY`、`HARD_CAP_DRAIN_AWAIT_SECONDS`、`MAX_HARD_CAP_DRAIN_DEFERS`。
  原始根因與修法計畫見 [`e2e_realopenai_audit_2026-06-28.md`](archive/e2e_realopenai_audit_2026-06-28.md)。

---

### 2.3 紅旗警示機制

```
              對話內容（每輪）
                    │
                    ▼
        ┌───────────────────────┐
        │   紅旗偵測引擎         │
        │                       │
        │  規則層：關鍵字比對     │
        │  ┌───────────────┐    │
        │  │ 大量血尿       │    │
        │  │ 劇烈腰痛       │    │
        │  │ 無法排尿       │    │
        │  │ 發燒 + 尿路症狀 │    │
        │  │ 睪丸急性疼痛    │    │
        │  │ ...            │    │
        │  └───────────────┘    │
        │                       │
        │  語意層：LLM 判斷      │
        │  （上下文綜合評估）      │
        └───────────┬───────────┘
                    │
              ┌─────▼─────┐
              │ 觸發紅旗？  │
              └─────┬─────┘
               Y/   \N
              /       \
    ┌────────▼──┐   繼續對話
    │ 立即中斷   │
    │ 對話結束   │
    │ 通知醫師   │
    │ Dashboard  │
    │ 顯示紅旗   │
    └───────────┘
```

**紅旗條件範例：**

| 症狀 | 疑似急性診斷 | 處置建議 |
|------|------------|---------|
| 睪丸急性劇痛 | 睪丸扭轉 | 立即泌尿外科會診 |
| 完全無法排尿 + 下腹脹痛 | 急性尿滯留 | 緊急導尿 |
| 發燒 + 腰痛 + 尿路症狀 | 急性腎盂腎炎 / 敗血症 | 急診評估 |
| 大量肉眼血尿 + 血塊 | 膀胱填塞 | 緊急沖洗 |
| 腎絞痛合併感染徵象 | 感染性腎結石 | 急診處理 |

#### 2.3.1 實作補充與不變式（2026-07-04 — E8-4 / E9）

**兩層偵測的實際運作**（`red_flag_detector.py` + `prompts/shared.py` URO_RED_FLAGS 8 條）
- **規則層（關鍵字）自 E9 起才真正啟用**：`red_flag_rules` 表查詢成功但 **0 筆**時（生產現況，
  從無 seed）fallback 到內建 catalogue 8 條規則——修復前只在「DB 例外」時 fallback，空表＝
  規則層恆空、偵測全靠語意層單層。DB 有 ≥1 筆則尊重 DB 配置、不與內建混用。kill-switch
  `RED_FLAG_BUILTIN_RULES_FALLBACK`（預設開）；fallback 啟用時載入 log 一行 warning（含規則數），
  可作為生產端確認訊號。
- **關鍵字比對＝全語言聯集**（頂層 `triggers` ∪ `triggers_by_lang` 全語言、英文 case-insensitive）：
  場次語言只決定「顯示」語言，病患實際用詞可能跨語言混講；醫療關鍵字特異性高，聯集的誤報
  風險遠小於按語言篩選的漏報風險（fail-open）。
- **已知取捨**：規則層是子字串比對、無否定語意——否定句（「沒有注意到…體重減輕」）可能誤報
  high（E2E 實測 1 例；僅醫師端 banner、去重與在地化皆正確）。若 critical 級出現否定誤報
  （誤 abort）的退路：否定詞窗口防護／critical 僅語意層可 abort／kill-switch 退關。
- **title 在地化（E8-4）**：alert 顯示名依場次語言解析（`get_display_title`，fallback
  requested → en-US → zh-TW）；語意層不信任 LLM 原文 title（會逐字複製 prompt 中文範例），
  凡命中 catalogue canonical_id 一律重新解析；DB 管理員自訂規則（canonical 不在 catalogue）
  title 不覆寫。去重身份一律 canonical_id（單輪 `_dedup_key` 合併 + 跨輪 A5 Redis），
  title 只是顯示，**不可拿 title 做任何判斷**；abort 判斷依 severity。
- 8 條紅旗的 ja/ko/vi 譯名經 AI 稽核修 3 筆明確錯誤；8 筆 medium/uncertain 待母語臨床者
  覆核（TODO §E E10 有逐筆建議）。

---

### 2.4 SOAP 報告生成模組

```
   對話紀錄（全文）
         │
         ▼
  ┌──────────────┐
  │  LLM 報告    │
  │  生成引擎     │
  └──────┬───────┘
         │
         ▼
  ┌──────────────────────────────────────┐
  │            SOAP 報告                  │
  │                                      │
  │  S（Subjective 主觀）                 │
  │  ├─ 主訴                              │
  │  ├─ 現病史（HPI）                      │
  │  ├─ 過去病史 / 用藥史                   │
  │  └─ 系統回顧（ROS）                    │
  │                                      │
  │  O（Objective 客觀）                   │
  │  ├─ 目前已知檢查結果                    │
  │  └─ 生命徵象（如有）                    │
  │                                      │
  │  A（Assessment 評估）                  │
  │  ├─ 鑑別診斷列表（含可能性排序）          │
  │  └─ 臨床推論依據 ★                     │
  │                                      │
  │  P（Plan 計畫）                        │
  │  ├─ 建議檢查項目 ★                     │
  │  │   ├─ 尿液分析                       │
  │  │   ├─ 腎功能（BUN/Cr）               │
  │  │   ├─ 影像學（超音波/CT）             │
  │  │   ├─ PSA                           │
  │  │   └─ ...                           │
  │  ├─ 每項檢查的理由說明 ★                │
  │  └─ 後續處置建議                       │
  │                                      │
  │  ★ = 系統重點輸出項目                   │
  └──────────────────────────────────────┘
```

---

### 2.5 醫師儀表板（Dashboard）

```
┌─────────────────────────────────────────────────────────────┐
│  泌尿科 AI 問診儀表板                          Dr. 王○○     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ 紅旗警示 ──────────────────────────────────────────┐    │
│  │  🔴 陳○○ — 睪丸急性劇痛 — 疑似睪丸扭轉 — 2 分鐘前   │    │
│  │  🔴 林○○ — 發燒+腰痛 — 疑似急性腎盂腎炎 — 5 分鐘前   │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ 今日問診列表 ─────────────────────────────────────┐    │
│  │  狀態    病患     主訴       進度      操作         │    │
│  │  ─────────────────────────────────────────────     │    │
│  │  🔴    陳○○    睪丸痛     已中斷     查看報告      │    │
│  │  ✅    張○○    血尿       已完成     查看報告      │    │
│  │  🔄    李○○    頻尿       對話中     即時監看      │    │
│  │  ⏳    黃○○    排尿困難    等待中     —            │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ 統計概覽 ──────────────────────────────────┐           │
│  │  今日問診：12    已完成：8    紅旗：2          │           │
│  └──────────────────────────────────────────────┘           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**儀表板功能：**
- 紅旗警示區：置頂顯示，即時推播
- 問診列表：狀態追蹤（等待中 / 對話中 / 已完成 / 已中斷）
- 報告檢視：點擊查看完整 SOAP 報告
- 即時監看：可即時查看進行中的對話內容
- 統計概覽：當日問診數、完成數、紅旗數

---

## 3. 系統架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend（App）                           │
│                                                                 │
│   ┌──────────┐   ┌──────────────┐   ┌───────────────────┐      │
│   │ 主訴選擇  │   │  語音對話介面  │   │  醫師 Dashboard   │      │
│   │  頁面     │   │  （STT/TTS）  │   │                   │      │
│   └────┬─────┘   └──────┬───────┘   └────────┬──────────┘      │
│        │                │                     │                 │
└────────┼────────────────┼─────────────────────┼─────────────────┘
         │                │                     │
         ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                       API Gateway                               │
└────────┬────────────────┬─────────────────────┬─────────────────┘
         │                │                     │
         ▼                ▼                     ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────────┐
│  主訴管理     │  │  對話服務      │  │  報告 / 儀表板    │
│  Service     │  │  Service      │  │  Service         │
│              │  │               │  │                  │
│ - 預設主訴    │  │ - 對話管理     │  │ - SOAP 生成      │
│ - 自訂主訴    │  │ - 上下文維護   │  │ - 報告儲存       │
│              │  │ - 紅旗偵測     │  │ - 儀表板資料      │
└──────┬───────┘  └───────┬───────┘  └────────┬─────────┘
       │                  │                    │
       ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      基礎設施層                                  │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐   │
│  │ LLM API  │  │ STT API  │  │  TTS API  │  │  Database    │   │
│  │(Claude / │  │(Whisper) │  │           │  │  (PostgreSQL │   │
│  │ GPT-4o)  │  │          │  │           │  │   + Redis)   │   │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────┘   │
│                                                                 │
│  ┌──────────────┐  ┌───────────────────┐                        │
│  │  WebSocket   │  │  Push Notification │                        │
│  │  (即時通訊)   │  │  (紅旗推播)        │                        │
│  └──────────────┘  └───────────────────┘                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 完整使用流程

```
開始
 │
 ▼
┌──────────────┐
│ 1. 選擇主訴   │──── 預設清單 or 自訂新增
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 2. 開始語音   │
│    對話       │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────┐
│ 3. 對話迴圈                       │
│                                  │
│   病患語音 → STT → LLM 追問      │
│        → TTS → 病患聽取回覆       │
│                                  │
│   同時：紅旗偵測引擎持續監控        │
│                                  │
│   ┌────────────────────┐         │
│   │  偵測到急性症狀？    │         │
│   └─────┬──────────────┘         │
│     Y/     \N                    │
│    /         \                   │
│   ▼           ▼                  │
│ 中斷對話    對話是否結束？          │
│ 跳至步驟5   │                    │
│           Y/ \N                  │
│          /    \                  │
│         ▼     回到對話迴圈         │
│       步驟4                      │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────┐
│ 4. 生成 SOAP 報告         │
│    - 鑑別診斷 + 推論依據   │
│    - 建議檢查 + 理由說明   │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 5. 結果呈現               │
│    - 正常：報告送至儀表板   │
│    - 紅旗：紅旗標記 +      │
│           即時推播醫師     │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 6. 醫師儀表板             │
│    - 檢視 SOAP 報告       │
│    - 處理紅旗警示          │
│    - 追蹤問診進度          │
└──────────────────────────┘
           │
           ▼
          結束
```

---

## 5. 技術選型建議

| 層級 | 技術 | 說明 |
|------|------|------|
| Frontend | React Native / Flutter | 跨平台 App |
| Backend | Node.js / Python (FastAPI) | API 服務 |
| LLM | Claude API / GPT-4o | 對話引擎 + 報告生成 |
| STT | Whisper API / Google STT | 語音轉文字 |
| TTS | ElevenLabs / Google TTS | 文字轉語音 |
| Database | PostgreSQL | 主資料庫 |
| Cache | Redis | 對話狀態快取 |
| 即時通訊 | WebSocket | 對話串流 + 紅旗推播 |
| 推播 | Firebase Cloud Messaging | 紅旗通知 |

---

## 6. 資料模型概要

```
Patient（病患）
├── id
├── name
├── medical_record_number
└── basic_info

Session（問診場次）
├── id
├── patient_id → Patient
├── chief_complaint（主訴）
├── status: waiting | in_progress | completed | aborted_red_flag
├── red_flag: boolean
├── red_flag_reason: string?
├── created_at
└── updated_at

Conversation（對話紀錄）
├── id
├── session_id → Session
├── role: patient | assistant
├── content_text（文字內容）
├── audio_url（語音檔）
├── red_flag_detected: boolean
└── timestamp

SOAPReport（報告）
├── id
├── session_id → Session
├── subjective: JSON
├── objective: JSON
├── assessment: JSON（含鑑別診斷 + 推論依據）
├── plan: JSON（含建議檢查 + 理由）
├── generated_at
└── reviewed_by_doctor: boolean

ChiefComplaint（主訴清單）
├── id
├── name
├── is_default: boolean
├── created_by: doctor_id?
└── category
```

---

## 7. 安全與合規考量

- **病患資料加密**：傳輸（TLS）與儲存（AES-256）皆加密
- **語音檔案管理**：設定保留期限，過期自動刪除
- **存取權限控制**：RBAC，醫師僅能查看自己的病患
- **稽核日誌**：所有操作留下 audit log
- **AI 免責聲明**：報告標注「AI 輔助生成，需醫師確認」
- **符合醫療法規**：依據當地個資法 / HIPAA 規範設計
- **Auth token 雙路徑（2026-07-04，使用回饋 #3「一直被登出」，`5e6566e`）**：M-22 的
  httpOnly-cookie refresh + double-submit CSRF 在前後端**不同註冊網域**（Vercel↔Railway）
  下結構性失效（`SameSite=lax` 跨站不送 cookie；CSRF cookie 跨站讀不到）。`/auth/refresh`、
  `/auth/logout` 依 token 來源分路：**有 cookie 必驗 CSRF**（防降級攻擊）；無 cookie 走
  request body 路徑並豁免 CSRF（token 由 JS 顯式提交、無 CSRF 攻擊面）。rotation +
  reuse-detection 兩路徑共用零放寬。token 效期環境變數加 `AliasChoices` 兼容 `JWT_` 前綴
  （原 `.env` 變數名不符被 pydantic `extra="ignore"` 靜默吞掉、實際效期 15 分鐘）。
  **部署注意**：alias 生效後 Railway 上原被忽略的 `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` 會
  開始生效，建議統一設 canonical `ACCESS_TOKEN_EXPIRE_MINUTES=30`。
