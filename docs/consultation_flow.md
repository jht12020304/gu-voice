# 問診流程圖：選主訴 → 問答 → 資料落地 → 研究分析

> 建立日期：2026-07-06
> 用途：完整盤點病患從「選擇主訴」到「語音/文字問答」到「產生的資料」到「研究分析頁」的端到端流程，
> 附 `file_path:line` 錨點、每階段寫入的表/欄、觸發點、以及分析頁讀取欄位可能為 NULL 的資料品質缺口。
> 相關文件：資料盤點 [session_data_inventory.md](session_data_inventory.md)、分析頁 [research_analytics.md](research_analytics.md)、管線不變式見記憶 `voice_pipeline_invariants`。

---

## 0. 一頁流程總覽

```
病患端                                          後端
──────                                          ────
[1] 選主訴 SelectComplaintPage
    多選≤5、selected[0]=primary、其餘併入自述文字
    「其他」sentinel(..ff)→自述必填、剝離「其他」字樣
        │ complaintId / complaintName / complaintText(≤200cp)
        ▼ (URL query 帶到下一頁)
[1b] 填基本資料 MedicalInfoPage
    身分(name/gender/dob/phone)+ intake(過敏/用藥/病史/家族史)
    language = i18n.resolvedLanguage
        │ POST /sessions
        ▼                                       ──►  [2] create_session
                                                     get_or_create patients 列
                                                     INSERT sessions(status=waiting, red_flag=false, language, intake_data)
                                                     dashboard WS: session_created / queue_updated
        │ navigate /conversation/{id}
        ▼
[3] 問答 ConversationPage  ◄── WebSocket ──►  [4] conversation_websocket
    語音(VAD/靜音矩陣)或文字 text_message          _validate_session → in_progress → 開場白
    每輪：送 audio_chunk / text_message             每患者輪：INSERT conversations(patient)
    收 stt_final / ai_response_* / red_flag_alert   紅旗偵測(規則層+語意層) → INSERT red_flag_alerts
    session_status=completed → 導向 thank-you        LLM 串流回覆 → INSERT conversations(assistant)
                                                     自動結束 或 critical→aborted_red_flag
                                                     → _update_session_status(terminal, duration/red_flag)
                                                     → SOAP 非同步：INSERT soap_reports + soap_report_revisions
                                                     → dashboard WS: session_status_changed
        │                                            ▼
        │                                       [5] 資料落地（見 §5 表）
        ▼                                            ▼
                                                [6] GET /api/v1/research/analytics
                                                     6 個查詢聚合 → 去識別化統計 → /research 頁
                                                     /research 訂閱 session_status_changed → debounce 1.5s refetch
```

---

## 1. 選主訴（前端）

**畫面**：`frontend/src/screens/patient/SelectComplaintPage.tsx`

- 病患**多選最多 5 個**主訴（`MAX_SELECT=5`，`SelectComplaintPage.tsx:40`）。`selected[0]` 為 **primary**（送後端的單一 FK），其餘併入自述文字。
- **「其他」sentinel** 主訴固定 UUID `00000000-0000-4000-8000-0000000000ff`（`:46`），與 alembic seed 同步。選它時補充自述**必填**（`otherNeedsText`，`:176`）。
- 自述文字：`customText`（`:141`）由 `buildComplaintText()`（`:205-214`）與所選名稱組合，clamp 到 **≤200 code points**、名稱不中途截斷；送後端的文字會**剝離「其他」字樣**（`safeTextNames`，`:174-175`）。
- 開始（`handleStart`，`:226-240`）導向 `/patient/medical-info`，帶 query：`complaintId` = `selected[0].id`（可能是 Other sentinel）、`complaintName`、`complaintText`（≤200cp，供 AI/SOAP/紅旗的 payload）。
- **主訴目錄**：`stores/complaintStore.ts` `fetchComplaints()`（`:57-73`）→ `GET /complaints`（`services/api/complaints.ts:12-20`），依 `displayOrder` 排序。**此頁只讀目錄，不建場次。**

## 1b. 填基本資料 + 建場次（前端）

**畫面**：`frontend/src/screens/patient/MedicalInfoPage.tsx`

- 從 URL 讀 `complaintId/complaintName/complaintText`（`:139-141`），收集身分（name/gender/dob/phone）+ intake（過敏/用藥/病史/家族史）。
- `handleSubmit()`（`:220-297`）：`sessionLanguage = i18n.resolvedLanguage`（fallback `zh-TW`，`:236-240`），呼叫 `POST /sessions`（`services/api/sessions.ts:24-27`）payload：
  - `chiefComplaintId`（`:244`）、`chiefComplaintText: complaintText || complaintName`（`:245`）、`language`（`:246`）
  - `patientInfo{name,gender,dateOfBirth,phone|null}`（`:247-252`）、`intake{...}`（`:253-290`）
  - 成功 → `navigate('/conversation/{session.id}')`（`:292`）

> **E2E driver 對應**：`register_and_create_session` 直接 `POST /sessions` 帶 `chiefComplaintId/chiefComplaintText/language/patientInfo`——**一定要帶 `chiefComplaintText`**，否則 WS 端 `_validate_session` fallback 到 ORM 物件會 TypeError 斷線（見 §2）。

---

## 2. 建場次（後端）

**Router**：`backend/app/routers/sessions.py` `create_session()`（`:33-63`）。語言優先序 = `payload.language > user.preferred_language > Accept-Language > default`（`:49-51`）。

**Schema**：`backend/app/schemas/session.py` `SessionCreate`（`:72-100`）：`chief_complaint_id: UUID` 必填、`chief_complaint_text: Optional[str] max_length=200`、`language` 對 `SUPPORTED_LANGUAGES` 做 BCP-47 正規化、`patient_info` + `intake`。

**Service**：`backend/app/services/session_service.py` `create_session()`（`:628-762`）：
1. 以 `(user_id, name, dob, phone)` `get_or_create` **`patients` 列**（`:672-713`）；fallback 到第一個 patient 或自動建 placeholder（name "Unknown"、dob 1900-01-01）（`:715-740`）。
2. `SessionService.create()`（`:254-281`）INSERT **`sessions`**：`patient_id, doctor_id?, chief_complaint_id, chief_complaint_text, status=WAITING, red_flag=False, language, intake_data(JSONB), intake_completed_at`。
3. `commit` + 重取（eager `conversations`+`patient`）。
4. `_broadcast_session_created()`（`:37-75`）→ dashboard WS `session_created` + `queue_updated`/`stats_updated`（同行程、僅在有 dashboard client 連線時）。

**`_validate_session` 的 chiefComplaintText fallback** 其實在 **WS handler**：`conversation_handler.py:2494-2631`。fallback 鏈（防 E8-2：ORM relationship 物件洩進 substring 比較）：
```
chief_complaint = session_obj.chief_complaint_text
                  or resolved_chief_complaint_display   # name_by_lang → name
                  or ""                                  # 保證 str
```

---

## 3. 問答（前端）

**畫面**：`frontend/src/screens/patient/ConversationPage.tsx`

- **載入**：`GET /sessions/{id}` + `GET /sessions/{id}/conversations`（`:500-503`）。
- **WebSocket**：`useConversationWebSocket(sessionId)`（`:110`）。
- **語音/VAD**：`useAudioStream(isSessionActiveForMic)`（`:128`）；mic 僅在 `in_progress`/`waiting` 自動啟用（`:126-127`），音訊以 `audio_chunk` 串到後端。
- **AI 講話硬鎖麥**（管線不變式）：voice 模式 `ai_response_start` 時 `muteVAD()`（`:561-567`），逐句 TTS 尾端 `ai_response_end` 釋放（`:619-624`）。
- **收訊事件**（`:527-745`）：`stt_final`（患者泡泡 + `sttConfidence`，空辨識→重掛 VAD `:536-541`）、`ai_response_start/chunk/end`、`red_flag_alert`（`:628-639`）、`supervisor_guidance/degraded`、`session_status`、`error`。
- **文字 fallback**：`handleSendText()` 送 `text_message{text}`（`:337-357`），WS 未開時 disable（醫療安全：斷線不假造泡泡）。**E2E driver 走此路徑（全 text_message）。**
- **結束**：手動 `control{action:'end_session'}`（`:825-828`）；或 server 端 `session_status==='completed'` → 導向 thank-you（`:660-679`）。

---

## 4. 問答 WS handler（後端）

**檔案**：`backend/app/websocket/conversation_handler.py` `conversation_websocket()`（`:398`）

**連線**：auth → `_validate_session`（`:440`）→ 只允許 `waiting/in_progress`（`:446-452`）→ `connection_ack` → 初始化管線 STT/LLM/TTS/RedFlagDetector/Supervisor → `_update_session_status(in_progress)`（`:507`）+ dashboard `session_status_changed` → 無歷史則開場白（`:576-586`）。

**主迴圈**（`:645`）：`ping` / `control` / `audio_chunk` / `text_message`。
- `control end_session`（`:670-705`）：`→ completed`、`session_status` 給 client、dashboard `session_status_changed`、**觸發 SOAP** `_generate_soap_report_async`（`:696-703`）。
- `audio_chunk`（`→ _handle_audio_chunk :1064`）：buffer 到 `isFinal`、magic-byte 驗證、LLM per-user rate limit、Whisper `transcribe`（帶 session 語言）、emit `stt_final` 帶真實 `confidence`（None 時省略 key）、再委派 `_handle_text_message`，帶 `patient_metadata={input_source:"voice", stt_language}`。

**患者輪持久化 + 紅旗 + 終止** — `_handle_text_message()`（`:1379`）：
1. 已終止 guard（`:1417-1430`）。
2. INSERT **`conversations` 患者列** `ConversationService.create(role="patient", stt_confidence=..., metadata=patient_metadata)`（`:1446-1455`）。文字路徑 `input_source:"text"`（`:795`）、語音 `input_source:"voice"`。
3. 用**前一輪** Supervisor 的 `hpi_completion_percentage`（Redis）決定是否自動結束（`_should_auto_conclude :266-290`）。
4. LLM 串流 + 逐句 TTS task（`:1517-1545`）；背景**紅旗偵測 task** `red_flag_detector.detect()`（`:1527-1529`）。
5. INSERT **`conversations` assistant 列**（`:1633-1640`）。
6. **紅旗 gate（醫療安全）**：等 ≤3.5s（`:1710-1712`）；`critical`/`high` 在 `ai_response_end` **之前** emit、較低嚴重度延後；timeout → 背景 `_drain_late_red_flags`（自帶 DB session）。
7. **`_persist_and_emit_alert()`**（`:1763-1914`）：跨輪 `canonical_id` 去重、title 重解析到 session 語言、INSERT **`red_flag_alerts`**（`AlertService.create`，`:1808-1825`）、標記患者 `conversations.red_flag_detected=True`、WS `red_flag_alert` + dashboard `new_red_flag`。
8. **critical → 終態**：`_update_session_status(aborted_red_flag, red_flag_reason=critical_title)`（`:2096-2103`）+ **SOAP task** + `_terminated`。
9. **自動結束 → 終態**：`_should_conclude_now()` gate → `_update_session_status(completed)`（compare-and-set）+ **SOAP task** + `_terminated`。

**紅旗偵測雙層** — `backend/app/pipelines/red_flag_detector.py`：規則層 `_rule_based_detect`（`alert_type="rule_based", confidence="rule_hit"`）+ 語意層 `_semantic_detect`（`alert_type="semantic", confidence="semantic_only"`）；`_merge_and_deduplicate` 同 `canonical_id` 併為 `combined`、升級 confidence；語意-only 但該 canonical 在 session 語言無關鍵字覆蓋 → 降級 `uncovered_locale`。

**SOAP 生成** — `_generate_soap_report_async()`（`:2308-2450`）：冪等（存在檢查 + 預插重查 + DB `UNIQUE(session_id)`）；`resolve_symptom_id()` 供 ICD-10 驗證（Other-sentinel/缺主訴回 None）；INSERT **`soap_reports`**（`status=GENERATED, review_status=PENDING, subjective/objective/assessment/plan, icd10_codes, icd10_verified, language, ai_confidence_score, raw_transcript, generated_at`）+ INSERT **`soap_report_revisions`** INITIAL 快照 + `notify_report_ready`。**此主流程路徑不 publish `report_generated`**（見缺口 4）。

**狀態轉移 + 稽核** — `_update_session_status()`（`:2644-2798`）：compare-and-set 保護終態；`in_progress` 時 `started_at=COALESCE(started_at, now())`；終態時 `completed_at=now()`、`duration_seconds=extract(epoch, now()-started_at)`（`started_at` NULL 則 NULL）；`aborted_red_flag` 時 `red_flag=True, red_flag_reason=critical_title`；**audit_logs** SESSION_START/END（`via="websocket"`）、`notify_session_complete`。

---

## 5. 產生的資料（每次問診寫入的表/欄）

| 表 | 何時寫 | 關鍵欄位 |
|---|---|---|
| **`patients`** | 建場次 `get_or_create` | `user_id, medical_record_number, name, gender, date_of_birth, phone` |
| **`sessions`** | 建場次 + 每次狀態轉移 | `patient_id, doctor_id?, chief_complaint_id, chief_complaint_text(≤200), status(waiting→in_progress→completed/aborted_red_flag), red_flag, red_flag_reason, language, intake_data, started_at, completed_at, duration_seconds` |
| **`chief_complaints`** | 唯讀目錄（不每次寫） | FK 參照；`name/name_en/name_by_lang/category` |
| **`conversations`** | 每輪一列 | `session_id, sequence_number, role(patient/assistant/system), content_text, stt_confidence(Numeric(5,4), 僅語音), red_flag_detected, metadata_ JSONB{input_source:"voice"\|"text", stt_language?, greeting?}, created_at` |
| **`red_flag_alerts`** | 每次紅旗 | `session_id, conversation_id, alert_type(rule_based/semantic/combined), severity(critical/high/medium), title, description, trigger_reason, trigger_keywords[], matched_rule_id?, suggested_actions[], canonical_id, confidence(rule_hit/semantic_only/uncovered_locale), language, created_at`；審閱後 `acknowledged_by/at, action_taken` |
| **`soap_reports`** | 結束後一份（UNIQUE session_id） | `session_id, status, review_status(pending/approved/revision_needed), subjective JSONB(含 `hpi` 10 欄), objective, assessment, plan JSONB(含 `urgency`=er_now/24h/this_week/routine), raw_transcript, summary, language, icd10_codes[], icd10_verified, ai_confidence_score(Numeric(3,2)), generated_at`；審閱後 `reviewed_by/at, review_notes` |
| **`soap_report_revisions`** | append-only 快照 | `report_id, revision_no, reason(initial/regenerate/review_override), subjective/.../plan, raw_transcript, icd10_codes[], language, ai_confidence_score, created_by, created_at` |
| **`audit_logs`** | 狀態轉移 | SESSION_START / SESSION_END / LANGUAGE_SWITCH_END_SESSION |

---

## 6. 資料如何到分析頁

**Router**：`backend/app/routers/research.py` `GET /api/v1/research/analytics`（`:28-57`），角色 `doctor`/`admin`，選填 `date_from/date_to`（依 `Session.created_at`）。

**Service**：`backend/app/services/research_service.py` `get_analytics()`（`:249-385`）跑 6 查詢；`_assemble()`（`:389-749`）純 Python 聚合。

| 查詢 | 來源 | 讀取欄位 |
|---|---|---|
| **Q1 sessions** | `:256-272` | `id, status, language, created_at, started_at, completed_at, duration_seconds` |
| **Q2 患者輪** | `:284-297` | `session_id, length(content_text), stt_confidence, metadata_["input_source"]`（`role=='patient'`） |
| **Q3 紅旗** | `:300-311` | `session_id, severity, alert_type, confidence, created_at, acknowledged_at` |
| **Q4 SOAP** | `:314-327` | `id, session_id, status, review_status, ai_confidence_score, icd10_verified, subjective, plan["urgency"]` |
| **Q5 revision reason** | `:333-349` | `reason`（grouped count） |
| **Q6 demographics/case mix** | `:354-373` | `patient_id, Patient.date_of_birth, Patient.gender, coalesce(ChiefComplaint.name_en, name)` |

**即時更新**：`ResearchAnalyticsPage.tsx` 訂閱 dashboard WS `report_generated` + `session_status_changed`（`:119-120`），debounce 1.5s refetch。
- `session_status_changed` **主流程每次轉移都會 fire**（`conversation_handler.py:513,683,2112,2280`）→ 這是可靠的更新觸發。
- `report_generated` **只從 Celery worker 路徑** publish（`tasks/report_queue.py:330-352`、`report_service.py:477-495`），主流程 `_generate_soap_report_async` 不 publish（見缺口 4）。

---

## 7. 資料品質缺口（分析頁讀取的欄位可能 NULL/缺）

> 這些缺口**不影響既有功能**：research service 對 NULL 一律排除或以 fallback 處理。列出供投稿時解讀與後續補強參考。

1. **`sessions.duration_seconds`/`started_at`/`completed_at`**：`duration_seconds` 在 `started_at` NULL 時為 NULL。efficiency 優先 `completed_at−started_at`，再 fallback `duration_seconds`（`research_service.py:490-493`）；兩者皆 NULL 則該場次靜默排除於時長統計。
2. **`conversations.stt_confidence`**：**只有語音路徑會寫**；`text_message` 輪一律 NULL（`:795`），Whisper 無信心時亦省略。→ STT 品質指標**只涵蓋有信心值的語音輪**。**⚠️ E2E driver 全走 text_message，故整批 `stt_confidence`=NULL、STT 區 n=0——這是預期，非 bug。**
3. **`metadata.input_source`**：`voice_turn_share` 分母只算有此鍵的輪；舊列缺鍵會被排除。
4. **`report_generated` 主流程不 fire**：主 WS 自動生成不 publish `report_generated`；/research 靠 `session_status_changed` 仍會即時更新，但只聽 `report_generated` 的消費者會漏掉主流程報告。
5. **`soap_reports.plan["urgency"]`**：`urgency_distribution` 只算 truthy urgency；LLM 漏標會被 backend fallback 到 `routine`（`soap_generator.py:99`），或 `plan` 缺鍵 → NULL 排除。
6. **`soap_reports.icd10_verified`**：預設 False；Other-sentinel/缺主訴 `resolve_symptom_id` 回 None → 該報告計為未驗證，壓低自述主訴的 `icd10_verified_rate`。
7. **`soap_reports.ai_confidence_score`**：nullable；`summarize()` 跳過 None，故 `ai_confidence_summary.n` 可能 < `reports_generated`。
8. **`soap_reports.review_status`**：`physician_agreement` 分母 = `approved + revision_needed`；醫師未審前全 `pending` → 分母 0 → 同意率 = None。**⚠️ 新問診在醫師審閱前，documentation 的同意率為 None——預期。**
9. **`sessions.red_flag`/`red_flag_reason` 有寫但 research 不讀**：safety 全由 `red_flag_alerts` 表推導（`terminal_with_alert`）。且 `red_flag` 只在 `aborted_red_flag`（critical）設 True、high-only 不設，本就不是可靠的「有任何 alert」旗標。
10. **HPI 完整度 proxy**：`hpi_completeness` 只把「非空字串」算填答（`:206-210`）；若 SOAP 生成器對某 HPI 欄輸出非字串（list/number）會被算空、低估完整度。

> **承重不變式**：分析頁所有比例的**分子必須是分母的子集**，否則 `wilson_proportion` 會 `sqrt(負數)` → 500（PR#18 生產教訓）。safety 紅旗率分子已改用 `sessions_with_alert ∩ terminal_ids`。詳見 [research_analytics.md](research_analytics.md) §3。
