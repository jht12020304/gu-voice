# 語音問診完成後的數據清單（Data Inventory）

> 盤點日期：2026-07-06（依 `main` 分支程式碼逐檔核實）
> **2026-07-06 更新**：首次盤點發現的 §11 缺口除「音檔不留存」（產品決定維持）外已全數修復；本文件同步為修復後現況，修復明細見 §11。
> 範圍：一場語音問診（WS `/ws/conversation`）從開始到結束，系統實際產生、暫存、廣播的**所有數據**，含問答原文的存放位置與取得方式。

---

## 0. 總覽：一場問診會留下什麼

| 層 | 存放處 | 內容 | 壽命 |
|---|---|---|---|
| **永久持久化** | PostgreSQL（Supabase） | `sessions`、`conversations`（問答原文逐輪）、`soap_reports`（含 `raw_transcript` 合併逐字稿）、`soap_report_revisions`、`red_flag_alerts`、`audit_logs`、`patients` | 永久（audit 有保留期任務；音檔 90 天——目前實際未上傳，見 §6） |
| **暫存** | Redis | 對話歷史（LLM context）、場次狀態、紅旗去重記錄、Supervisor 指導 | TTL 30 分鐘～1 小時 |
| **即時廣播（不落地）** | WebSocket | 病患端事件（STT 結果、AI 回覆逐句文字+TTS base64 音訊、紅旗、場次狀態）、醫師儀表板事件 | 僅當下連線 |
| **推播** | FCM（Firebase） | 紅旗警示推播給負責醫師 | 送出即結束 |
| **觀測性** | Prometheus / 後端 log / Sentry（前端） | 計數器、延遲直方圖、結構化 log | 依各平台保留設定 |

---

## 1. 問答原文（逐字稿）— 三個存放處

### 1.1 `conversations` 表（權威來源，逐輪原文）

`backend/app/models/conversation.py`。按月 Range Partition（分區鍵 `created_at`）。**每一輪問答各存一列**，這是唯一「逐輪、未壓縮、未改寫」的原文：

| 欄位 | 型別 | 實際內容 |
|---|---|---|
| `id` | UUID | 主鍵 |
| `session_id` | UUID | 所屬場次 |
| `sequence_number` | int | 場次內序號（advisory lock + trigger 保證唯一） |
| `role` | enum | `patient` / `assistant` / `system`（實際流程只寫前兩者） |
| `content_text` | Text | **問答原文**。assistant 的開場問候語也存；病患輪存 STT 最終辨識文字；AI 輪存完整回覆全文 |
| `audio_url` | String(500) | 恆為 NULL——**產品決定：音檔不留存**（見 §6） |
| `audio_duration_seconds` | Numeric(8,2) | 恆為 NULL（同上，音檔不留存） |
| `stt_confidence` | Numeric(5,4) | ✅ 病患語音輪存**真實估算值**：由 Whisper verbose_json segments 的 avg_logprob 推導 exp(mean)（幾何平均 token 機率，0~1）；segments 缺失或文字輸入輪為 NULL（`stt_pipeline._estimate_confidence`） |
| `red_flag_detected` | bool | ✅ 紅旗警示持久化成功後，觸發它的病患對話輪會被標記 true（`_persist_and_emit_alert`，獨立小交易、失敗不影響警示本體）；完整紅旗明細仍在 `red_flag_alerts` 表 |
| `metadata`（JSONB） | JSONB | ✅ 病患輪：`{"input_source": "voice"\|"text", "stt_language": ...}`；AI 輪：`{"message_id": ...}`（對應該輪 `ai_response_*` WS 事件）、開場另有 `"greeting": true` |
| `created_at` / `updated_at` | timestamptz | 建立/更新時間（updated_at 由 DB trigger 維護） |

**病患輪原文的性質**：是 Whisper STT 的辨識結果（非錄音），且經過幻覺/靜音過濾——被判定為幻覺的片段**直接丟棄、不會落 DB**（`stt_pipeline.py` `_is_hallucination`）。文字輸入模式（打字）則存病患原始輸入。

### 1.2 `soap_reports.raw_transcript`（合併為單一文字欄）

SOAP 報告生成時把全場對話串成一個 Text 欄位。✅ 兩條生成路徑（WS 結束 / Celery 重生）**共用單一格式來源** `app/utils/transcript.py::format_raw_transcript`，統一為 `[patient] ...` / `[assistant] ...` 中性標籤，不隨場次語言變動。

### 1.3 Redis 對話歷史（暫存，**不保證完整**）

Key `gu:session:{session_id}:context` 的 `conversation_history` 欄（JSON，含 `role`/`content`/`timestamp`），TTL 1 小時（`conversation_handler.py:37-40`）。超過上限時會做 **FIFO 摘要壓縮**（`_cap_conversation_history`）——所以 Redis 裡的不是完整原文，僅供 LLM context 與斷線 resume 用。**要完整原文一律查 `conversations` 表。**

---

## 2. `sessions` 表（場次主檔）

`backend/app/models/session.py`：

| 欄位 | 內容 | 寫入時機 |
|---|---|---|
| `id` | 場次 UUID | 建立時 |
| `patient_id` / `doctor_id` | 病患 / 指派醫師 | 建立 / 指派時 |
| `chief_complaint_id` | 主訴 FK（選「其他」時指向 sentinel UUID `...00ff`） | 建立時 |
| `chief_complaint_text` | 病患自述主訴（≤200 字，「其他」時為實際主訴） | 建立時 |
| `status` | `waiting` → `in_progress` → `completed` / `aborted_red_flag` / `cancelled`（CAS 轉移，終態不可被降級） | 全程 |
| `red_flag` | **語意＝「因紅旗中止」**，只有轉 `aborted_red_flag` 時設 true；「曾出現紅旗但正常完成」的場次為 false，要查 `red_flag_alerts` | 中止時 |
| `red_flag_reason` | 中止原因（critical 紅旗 title，已按場次語言在地化） | 中止時 |
| `language` | 場次語言（BCP-47：zh-TW / en-US / ja-JP / ko-KR / vi-VN） | 建立時 |
| `intake_data` | 問診前 intake 快照（JSONB，結構見 §2.1） | 建立時 |
| `intake_completed_at` | intake 完成時間 | 建立時 |
| `started_at` | 首次轉 `in_progress` 時（COALESCE 冪等，WS 路徑 E8-3 已補寫） | 開始時 |
| `completed_at` | 轉任一終態時 | 結束時 |
| `duration_seconds` | ✅ REST 與 WS 兩路徑皆寫：WS 終態轉移時以 `EXTRACT(EPOCH FROM now() − started_at)` 補寫（`started_at` 為 NULL 則保持 NULL）；儀表板平均時長仍以 `completed_at − started_at` 為優先來源 | 結束時 |
| `created_at` / `updated_at` | 時間戳 | 自動 |

### 2.1 `intake_data` JSONB 結構（`schemas/session.py` `SessionIntake`）

```json
{
  "no_known_allergies": false,
  "allergies": [{ "allergen": "", "reaction": "", "severity": "", "had_hospitalization": false }],
  "no_current_medications": false,
  "current_medications": [{ "name": "", "frequency": "" }],
  "no_past_medical_history": false,
  "medical_history": [{ "condition": "", "years_ago": "", "still_has": true }],
  "family_history": [{ "relation": "", "condition": "" }]
}
```

此快照會被格式化併入 SOAP 生成的 patient_info（`conversation_handler.py:2489-2520`），缺項才 fallback 到 `patients` 表的長期欄位。

---

## 3. `soap_reports` 表（AI 生成的 SOAP 報告）

`backend/app/models/soap_report.py`。一場一份（`session_id` UNIQUE）。所有結束路徑（HPI 自動結束 / `end_session` 指令 / 閒置逾時 / critical 紅旗中止）都會觸發生成，冪等保護三層（早期檢查 + insert 前複查 + DB UNIQUE）。

| 欄位 | 內容 |
|---|---|
| `status` | `generating` / `generated` / `failed` |
| `review_status` | `pending` / `approved` / `revision_needed`（醫師審閱） |
| `subjective` / `objective` / `assessment` / `plan` | 四段 JSONB，結構見 §3.1 |
| `raw_transcript` | 全場對話逐字稿（合併文字，見 §1.2） |
| `summary` | 3–5 句問診摘要 |
| `language` | 生成時所用語言（獨立於 session.language，供重生審計） |
| `icd10_codes` | ICD-10 碼陣列（已過泌尿科白名單過濾） |
| `icd10_verified` | 是否通過 symptom↔code 對映雙檢（false → 前端顯示「需醫師確認」） |
| `ai_confidence_score` | 0.00–1.00（LLM 自評 HPI/鑑別診斷完整度） |
| `reviewed_by` / `reviewed_at` / `review_notes` | 醫師審閱軌跡 |
| `generated_at` | 生成完成時間 |

### 3.1 四段 JSONB 完整 schema（`soap_generator.py` 系統提示詞強制）

```json
{
  "subjective": {
    "chief_complaint": "string",
    "hpi": { "onset": "…", "location": "…", "duration": "…", "characteristics": "…",
             "severity": "…", "aggravating_factors": "…", "relieving_factors": "…",
             "associated_symptoms": "…", "timing": "…", "context": "…" },
    "past_medical_history": "string|null", "medications": "string|null",
    "allergies": "string|null", "family_history": "string|null",
    "social_history": "string|null", "review_of_systems": "string|null"
  },
  "objective": { "vital_signs": null, "physical_exam": null,
                 "lab_results": null, "imaging_results": null },
  "assessment": {
    "differential_diagnoses": [
      { "diagnosis": "string", "likelihood": "high|moderate|low", "reasoning": "string" }
    ],
    "clinical_impression": "string（有紅旗時開頭強制加 ⚠️ 標註）"
  },
  "plan": {
    "recommended_tests": [
      { "test_name": "string", "rationale": "string",
        "urgency": "er_now|24h|this_week|routine", "clinical_reasoning": "string" }
    ],
    "treatments": ["string"], "medications": ["string"], "follow_up": "string|null",
    "patient_education": ["string"], "referrals": ["string"],
    "diagnostic_reasoning": "string",
    "urgency": "er_now|24h|this_week|routine"
  }
}
```

安全硬規則：偵測層紅旗會強制提升 `plan.urgency`（只升不降：critical→er_now、high→24h、medium→this_week），並同步提升各檢查項 urgency（`_enforce_red_flag_urgency`）。非法 urgency 值 fallback 成 `routine` 並記 warning。

### 3.2 `soap_report_revisions` 表（append-only 版本快照）

每次報告內容被寫入/覆寫前先存一版快照（`reason` = `initial` / `regenerate` / `review_override`），含四段 JSONB、summary、**raw_transcript**（migration `b7c8d9e0f1a2` 新增；舊資料為 NULL）、icd10_codes、language、ai_confidence_score、`created_by`。只 INSERT，不可改刪——醫師改過什麼、AI 原稿是什麼、當時 LLM 看到的逐字稿都可追溯。✅ WS 生成路徑現在與 Celery 路徑一致，首版也會寫 `initial` 快照。

---

## 4. `red_flag_alerts` 表（紅旗警示）

`backend/app/models/red_flag_alert.py`。問診中即時偵測（規則層 + LLM 語意層雙層），每筆：

| 欄位 | 內容 |
|---|---|
| `session_id` / `conversation_id` | 回指場次與觸發的病患對話輪 |
| `alert_type` | `rule_based` / `semantic` / `combined` |
| `severity` | `critical` / `high` / `medium` |
| `title` / `description` | 已按場次語言在地化的標題/描述 |
| `trigger_reason` | 觸發原因 |
| `trigger_keywords` | 命中的關鍵字陣列（規則層） |
| `matched_rule_id` | 命中的 `red_flag_rules` 規則 FK |
| `llm_analysis` | LLM 語意分析原始 JSONB |
| `suggested_actions` | 建議處置陣列 |
| `canonical_id` | 跨語言穩定 id（snake_case，去重 key） |
| `confidence` | `rule_hit` / `semantic_only` / `uncovered_locale`（後者自動 escalate + 寫 audit log） |
| `language` | 生成時場次語言 |
| `acknowledged_by/at` / `acknowledge_notes` / `action_taken` | 醫師確認軌跡與實際處置 |

同場次同 canonical 紅旗未升級時會被**跨輪去重**（不重複落 DB / 廣播）。critical 紅旗另外觸發：場次轉 `aborted_red_flag`、FCM 推播給負責醫師（含 alert_id / session_id / severity）。

---

## 5. 其他持久化資料

### 5.1 `patients` 表（病患主檔，非場次專屬但被引用）
`medical_record_number`（MRN）、`name`、`gender`、`date_of_birth`、`phone`、`emergency_contact`(JSONB)、`medical_history` / `allergies` / `current_medications`(JSONB)、soft-delete 欄位。SOAP 生成時取 name/age/gender 併入 prompt。

### 5.2 `audit_logs` 表（append-only，按月分區）
`user_id`、`action`、`resource_type/id`、`details`(JSONB)、`ip_address`、`user_agent`、`language`。與問診相關的實際寫入點：
- ✅ `SESSION_START` / `SESSION_END`：WS 路徑（`_update_session_status` 轉移成功後的第二段交易，user_id=NULL、details 含 previous/new status 與 `via: websocket`）與 REST 路徑（`update_status_static`，帶操作者 user_id 與 `via: rest`）皆會寫，並記錄場次語言
- `language_switch_end_session`：對話中切語言強制結束場次（含 from_lang / to_lang / session_id）
- 紅旗 `uncovered_locale` escalation（`alert_service.py`）
- 醫師審閱 / acknowledge 等操作（各 service）

### 5.3 `notifications` 表（站內通知）
✅ 三類通知已實際接上（皆發給場次負責醫師 `doctor_id`，標題/內文按醫師 `preferred_language` 解析，i18n 覆蓋 5 語系）：
- `RED_FLAG`：紅旗警示持久化時與 FCM 推播並行建立（病安關鍵，不受偏好抑制）
- `SESSION_COMPLETE`：WS 場次轉 `completed` 時（受偏好 `session_complete_enabled` 抑制）
- `REPORT_READY`：兩條 SOAP 生成路徑（WS / Celery）完成時，data 含 report_id + session_id（受偏好 `report_ready_enabled` 抑制）

場次未指派醫師時三者皆 no-op。FCM 推播（`notification_retry.py`）照舊並行，推播失敗會把無效 device token 標記 inactive。

---

## 6. 音訊數據：現況＝**不留存**

- 病患語音：前端以 webm/opus chunk 上傳 WS → 後端合併驗 magic bytes → 直接送 Whisper STT → **合併後的音訊 buffer 用完即棄**，不上傳 Storage、不寫 `audio_url`。
- AI 語音（TTS）：逐句合成後以 **base64 夾在 `ai_response_chunk` WS 事件**直接送前端播放，不落地。
- `AudioService.upload_audio`（Supabase Storage `audio-recordings` bucket，路徑 `{session_id}/{conversation_id}.{format}`）與 90 天清理任務 `cleanup_old_audio_files`（每月 1 日 05:00，`audio_lifecycle.py`）**基礎設施已就緒但目前無人呼叫上傳**——是為未來錄音留存預留的。

---

## 7. Redis 暫存數據（會過期）

| Key | 內容 | TTL |
|---|---|---|
| `gu:session:{id}:context` | `conversation_history`（LLM context，可能被 FIFO 摘要壓縮）等場次上下文 | 1 小時 |
| `gu:session:{id}:state` | 場次狀態快取（`status` 等） | 30 分鐘 |
| 紅旗去重 key | 已 emit 的 canonical_id + severity（跨輪去重用） | 場次級 |
| Supervisor 指導 | 前一輪 Supervisor 分析結果（HPI 完整度等），供下一輪開頭讀取 | 場次級 |

---

## 8. WebSocket 即時事件（廣播即逝，不落地）

### 8.1 病患端（`/ws/conversation`）
| 事件 | payload 重點 |
|---|---|
| `connection_ack` | 連線確認 |
| `stt_final` | `{ messageId, text（辨識原文）, confidence?（真實估算值 0~1；未知時不帶此鍵）, isFinal }` |
| `ai_response_start` | `{ messageId }` |
| `ai_response_chunk` | `{ messageId, text（單句）, chunkIndex, audioB64（TTS 音訊）, ttsFailed }` |
| `ai_response_end` | `{ messageId, fullText（AI 回覆全文）, ttsAudioUrl: "" }` |
| `supervisor_guidance` | Supervisor 指導（HPI 完整度等） |
| `red_flag_alert` | `{ alertId, severity, title, description, suggestedActions }` |
| `session_status` | `{ status: "completed"…, code, params, severity }`（前端據 `status==='completed'` 導向 thank-you 頁） |
| `error` | 在地化錯誤（STT 失敗、rate limit、紅旗持久化失敗等） |

### 8.2 醫師儀表板（dashboard WS）
| 事件 | payload 重點 |
|---|---|
| `new_red_flag` | `{ alertId, sessionId, patientName, severity, title, description }` |
| `session_status_changed` | `{ sessionId, status, previousStatus, code… }` |
| `queue_updated` / `stats_updated` | 候診佇列與統計（場次狀態變更後順帶推播） |
| `report_generated` | `{ reportId, sessionId, patientName, status }`（Celery 路徑經 Redis pub/sub 跨行程轉發） |

---

## 9. 事後取數的 API 端點

| 目的 | 端點 |
|---|---|
| 場次列表 / 詳情（含 intake、紅旗旗標、時間） | `GET /api/v1/sessions`、`GET /api/v1/sessions/{id}`（detail 含 conversations） |
| **問答原文逐輪**（cursor 分頁） | `GET /api/v1/sessions/{id}/conversations` |
| 報告列表 / 詳情（四段 JSONB + `raw_transcript` + ICD-10 + 信心分數） | `GET /api/v1/reports`、`GET /api/v1/reports/{report_id}` |
| 報告版本歷史（append-only） | `GET /api/v1/reports/{report_id}/revisions` |
| **PDF 匯出**（`include_transcript=true` 可附逐字稿；版面標籤支援 zh-TW/en-US/ja-JP/ko-KR） | `GET /api/v1/reports/{report_id}/pdf` |
| 重生報告（走 Celery） | `POST /api/v1/sessions/{session_id}/reports/generate` |
| 紅旗警示 | `GET /api/v1/alerts`、`GET /api/v1/alerts/{id}`、`POST /api/v1/alerts/{id}/acknowledge` |
| 稽核日誌（admin） | `GET /api/v1/audit-logs` |
| 儀表板統計（含平均問診時長） | `GET /api/v1/dashboard/*` |

---

## 10. 觀測性數據

- **Prometheus**（`core/metrics.py`）：`sessions_total`（按語言）、`red_flag_triggers`、`unsupported_lang_requests`、`forced_fallback`、`red_flag_rule_layer_coverage`、`stt_latency_seconds` / `tts_latency_seconds` 直方圖。
- **後端 log**：每輪 STT / LLM / TTS / 紅旗 / SOAP 生成的結構化 log。✅ 已去 PHI：STT preview、幻覺 dropped 原文、SOAP 語言檢查 sample、SOAP 生成起始的主訴原文皆已改為只記長度 / 語言碼，不再輸出對話原文。
- **Sentry**：前端錯誤回報（`frontend/src/services/sentry.ts`）；後端 `core/sentry.py`。
- 前端無 PostHog 實際埋點（`frontend/posthog/` 僅為資料夾，src 內無 capture 呼叫）。

---

## 11. 缺口修復狀態（2026-07-06 首次盤點 → 同日修復）

| # | 首次盤點發現 | 狀態 | 修復方式 |
|---|---|---|---|
| 1 | 音檔完全不留存 | **維持不修**（產品決定） | 病患語音用完即棄、TTS 只經 WS 播放；`AudioService` 與 90 天清理任務保留為未來預留設施 |
| 2 | `stt_confidence` 恆 NULL、`stt_final.confidence` 恆 1.0 佔位 | ✅ 已修 | `stt_pipeline._estimate_confidence` 由 segments avg_logprob 估算 exp(mean)；落 DB（病患語音輪）＋穿 WS（未知時不帶鍵）；前端低信心門檻由 0.8 校準為 0.5 |
| 3 | `red_flag_detected` 恆 false | ✅ 已修 | 警示持久化成功後標記觸發的病患對話輪（獨立小交易，失敗不影響警示） |
| 4 | `conversations.metadata` 無人寫入 | ✅ 已修 | 病患輪存 input_source / stt_language、AI 輪存 message_id；順帶修掉 `Conversation(metadata=...)` 被 `Base.metadata` 遮蔽而靜默丟值的 ORM 陷阱（改用 `metadata_=`） |
| 5 | `raw_transcript` 兩路徑格式不一致 | ✅ 已修 | 抽出單一來源 `app/utils/transcript.py::format_raw_transcript`，兩路徑共用（測試鎖住不得再 inline） |
| 6 | `duration_seconds` 只在 REST 寫 | ✅ 已修 | WS 終態轉移同 UPDATE 內以 `EXTRACT(EPOCH ...)` 補寫；started_at NULL 則保持 NULL |
| 7 | 站內通知死路 | ✅ 已修 | `RED_FLAG`（警示建立時、恆送）/`SESSION_COMPLETE`（WS completed）/`REPORT_READY`（兩條 SOAP 路徑）接上；依醫師 preferred_language 出 5 語系文案，受既有偏好開關抑制 |
| 8 | `SESSION_START`/`SESSION_END` audit 未寫入 | ✅ 已修 | WS 與 REST 兩路徑皆寫（含 previous/new status、via、場次語言）；`AuditLogService.log` 補 `language` 參數 |
| 9 | revision 快照不含 raw_transcript | ✅ 已修 | migration `b7c8d9e0f1a2` 加欄 + 快照帶入；並補上「WS 生成路徑漏寫 INITIAL revision」的隱藏缺口（現與 Celery 路徑一致） |
| 10 | 後端 log 含原文片段（PHI） | ✅ 已修 | STT preview / 幻覺 dropped 原文 / SOAP 語言檢查 sample / SOAP 起始 log 主訴原文全數改為長度或語言碼 |

**設計不變式（修復時遵守）**：稽核與通知一律放在狀態轉移 / 警示 commit **之後**的獨立交易，任何失敗只記 warning，絕不回滾已生效的病安關鍵寫入。

**驗證（2026-07-06）**：backend 單元測試 809 passed（含新增 24 個守護測試：STT confidence 估算、metadata_ 陷阱、raw_transcript 單一來源、red_flag_detected 標記、duration/稽核 SQL、通知 i18n 5 語系覆蓋）；migration 鏈於乾淨 PG15 全套用 + downgrade/upgrade 雙向驗證；frontend `tsc --noEmit` 通過。
