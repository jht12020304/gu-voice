# GU-Voice TODO 清單

> 依據 [`system_issues_and_risks.md`](archive/system_issues_and_risks.md) 整理的可執行待辦事項。
> 完成一項就把 `[ ]` 改成 `[x]`，並在後面加上完成日期與 commit hash。
>
> 最後更新：2026-08-21。最新一輪是 **2026-08-21 敵意複驗修復（第二戰役）**——
> PR #57（merge `5457b32`、內容 commit `3eacd50`），修掉第一戰役自己造成的回歸與遺漏
> （S7／S8／S10／S11／S12），接在 **2026-08-20 LLM 管線稽核修復戰役**（PR #55）之後。兩輪都見 §S。
>
> **2026-08-17**：P0–P2、§E E1–E9、§F F1–F7 全部完成並部署生產。本輪變動：
> - 部署不變式更正——**merge 到 main 不會上線**，要手動 `railway up` / `vercel --prod`（見 deployment_guide.md 一、）
> - #2 假記載更正（celery worker/beat service 不存在，改跑在主 API 容器內）
> - Flutter 遷移使 P3 的 #22／#24／#32 作廢、#23／#27 縮成單行工程項
> - 新增 §G（flutter_app 入庫審查：2 blocker + 11 high **全部修完**，剩 22 medium）
> - 新增 §H（H1 忘記密碼路徑已結案／H2 儀表板 monthLabel 硬寫中文）
> - E10 底下工程項拆成 E11／E12，讓 E10 純粹等母語臨床覆核
>
> **2026-07-27 ultracode 批次**：E11（紅旗否定守衛，含對抗式驗證找到的 ja/ko/vi/en critical 漏報）、
> H2（儀表板年月）、G35b（切語言守衛＋不變式 #16 修正）、G36／G37、TTS 測試覆蓋、
> H4（G36 抓到的兩個 Flutter 缺口）全數完成，**真 OpenAI e2e 兩情境通過**。
>
> **2026-07-27 §R 批次（四輪 workflow，54 agent）**：用文字模擬 + 真 OpenAI 把
> 「intake → 問診判斷 → 紅旗 → SOAP」整條流程走了一遍，修掉 17 項（R1–R17，含 intake
> 從不進 SOAP、三條「終態卻沒有 SOAP」的路徑、規則層對真人語序 4/5 語漏偵測、
> §3b 家族史誤判會捏造病歷），4 項未結案（R18–R21）。7 個 commit，見 §R。
> **§R-lessons 的六條教訓比任何一條個別修復重要，動紅旗／§3b 之前先讀。**
>
> 未結案：**§V 六條 Flutter 未驗證項**（V1／V3／V4／V5／V7／V8——V1 是紅字，語音仍未跑過；
> V2 已於 2026-07-27 用文字代替語音驗畢，V6 是 2026-08-17 結案的 **Flutter Web** 管道。
> **V8 是 2026-08-21 從 §V6 拆出來的 iOS TestFlight 發佈管道**——它先前寄生在已勾選的 §V6 底下，
> 掃 checkbox 的人會讀成已完成）、
> E10（等母語臨床覆核）、F8／G35a（等臨床拍板）、E12（投機 schema，無消費端，不做）、
> H3（dashboard 其餘硬寫中文標籤）、H5（replay 未 await，推測性未驗證）、
> **§R 四條**（R18 斷言過嚴／R19 第 1 輪重問／R20 收尾後多一輪／R21 政策接受的誤報）、
> **§S 八條**（S1／S2 待臨床拍板的紅旗字面／S3 通知文案搬 i18n／S4 e2e 掃不到病患語言版摘要／
> S5 `additional_notes` 收下未用／S6 兩份終態清單無跳閘器／
> **S9 `is_dont_know` 含數詞固定語誤判**（2026-08-21 發現，**仍尚無人認領**）／
> **S13 `chief_complaint_text` 可繞過 §3b 必問安全 gate**（2026-08-21 e2e 實證，既有行為、非任一輪造成））。
>
> **2026-08-22 效能稽核**：7 面向 × 敵意查證，42 條提出／33 條存活／9 條駁回，已修 21 處（開機路徑、醫師端 N+1、語音頁重建頻率、gzip、bcrypt 移出 event loop）。**剩下的 18 條、四條要你拍板的、以及三條「明確不要這樣做」全部在 [perf_audit_2026-08-22.md](perf_audit_2026-08-22.md)**——那份是唯一權威來源，這裡不重抄。
>
> ⚠️ **這行數字先前是錯的**：舊版寫「§S 十二條」卻只列到 S12，**S13 從來沒被算進去**
> （它是第二戰役的 e2e 新發現，加進 §S 時漏了同步檔頭）。現在的八條＝S1–S6 ＋ S9 ＋ S13。
>
> **§S 已結案（2026-08-21，PR #57 / 內容 commit `3eacd50`）**：**S7／S8／S10／S11／S12** 五條落地。
> 缺陷描述與教訓在 §S **原地保留**（那是這份文件的價值），只把狀態改成已修並補上修法摘要與守它的測試名。
> ⚠️ **S9 沒有跟著修**——它是同一批發現裡唯一沒人認領的一條，別因為隔壁四條變綠就順手當它也好了。
>
> **2026-08-18 文字先行測試掃蕩（P0–P5，分支 `fix/text-sweep-2026-08-18`）**：以文字代替語音把
> 兩端全流程再走一遍，發現並修掉 14 項。一行式索引（詳情見各 commit message）：
> `0e33bce` Redis 黑名單 fail-open ＋ refresh 登記失敗改 503／`8a0647d` 移除三處 dashboard
> 廣播的本地連線數 early-return（多 worker 漏發）／`7758ce2` Decimal 欄位 JSON 輸出改 float
> （Flutter `as num?` 解析全滅）／`5ec7022` 逾時取消補 CAS ＋ 狀態機驗證 ＋ dashboard 廣播／
> `ed759d4` 無麥克風降級（iOS 原生探針，修 SIGABRT）＋ `voiceUnavailable` 旗標／
> `8a7764e` StatusBadge 補 `common.` namespace／`7761e81` 兩端訂閱 `resume_failed` 並以 REST
> 重建逐字稿／`dadbca3` 本機 CORS 白名單、紅旗場次報告按鈕、Google Fonts 失效 URL／
> `ec6f46e` supervisor `next_focus` 不得換句話重問已拒答欄位（四層防線，收束 R19 的一部分）／
> `df486b5` Flutter Web/iOS 整合測試基礎設施／`7a59205` 見 R22／`3877729` 見 G34、G35b。
> **未含**：P6 真麥克風／STT/TTS/VAD 人工驗證仍未做（§V1／§V4 不變）；
> `refresh`／`logout`／`reset` 三條路徑的 503 語意一致性列管未收；
> `ink_sparkle` 著色器在測試環境的問題另案。
>
> **2026-08-20 LLM 管線稽核修復戰役（PR #55 `b7323ca`，9 commits，見 §S）**
>
> - **稽核**：以 `.claude/skills/voice-pipeline-invariants/SKILL.md` 的不變式為基準（**當時 27 條，
>   本輪之後已擴到 37 條**——照這個指標點過去看到的是 37），
>   四路靜態稽核 ＋ 真 OpenAI e2e 六場，**只讀不修**先產出缺陷表。抓到兩條 P0 **漏報**
>   （RF-1 否定幻覺後過濾誤刪規則層共現組命中；RF-2 critical 否定回看無語意邊界，
>   五語「否認一串病史＋逗號＋真急症」全滅）與一條 Flutter Web promote blocker
>   （IN-1 `no_*` 由空清單推斷＝捏造病歷）。
> - **修復**：逐項修完並逐項驗收，9 個 commit。索引：`8e30bd3` e2e 工具可攜性／
>   `931b9b7` Flutter intake（IN-1／D-3／D-10／D-5）／`116282d` 結束機制（EM-1 abort
>   fall-through、EM-4 `end_session` 守衛、EM-5 先標後送、REST 六件事、SO-3 drain 順序）／
>   `6fc51e3` 紅旗偵測（RF-1／RF-2 漏報 ＋ RF-3／RF-4 誤報字面逐條舉證收窄）／
>   `7e28d11` Flutter 病患端顯示／`2daa82c` React 對稱（EM-3 結束不搶先導頁）／
>   `c6938c8` SOAP 報告鏈（SO-1 時間窗消毒、SO-2 regenerate／FAILED、`patient_facing_localized`）／
>   `24d3083` 對話層（IN-2 §3b 五語詞庫、IN-3 來源標籤三態、D-2 配額、D-1 入口消毒、D-8）／
>   `fb403d6` e2e `t5` 斷言改版。
> - **總驗收**：backend unit **4602 passed / 4604 collected**（稽核前 `67cdf30` 是
>   3954 collected → **collected +650**；**passed 的差是 +648**，兩種跑法都一樣，
>   見 §S 的總驗收段；注入式回歸依**七個** commit message 自報合計
>   **82 組**，其中 backend 四個 commit 佔 52 組；`fb403d6` 另自報 10 組**離線注入驗證**，
>   類別不同、未計入）、
>   flutter 217 tests ＋ `analyze` 零 issue、React type-check／lint／build／11 tests、
>   `check_translations.py` OK、真 OpenAI e2e 六情境（torsion×2／dontknow／intake_wiring／
>   ed_zh／hematuria_3b_en）全 PASS ＋ ruleprobe 36 ＋ preflight 10。
>   ⚠️ 六場留存結果的 `backend_head` 都是 `24d3083`，即**第 9 個 commit `fb403d6`（t5 斷言
>   改版）之前**；且 `intake_wiring_zh` 在同一個 head 上留有一份 FAIL
>   （`results/intake_wiring_zh.24d3083_run1_i5fail.json`），**同日稍後重跑才 PASS**
>   （FAIL 那場 `started_at 14:52:54Z / finished_at 14:55:49Z`、PASS 那場
>   `started_at 15:04:43Z / finished_at 15:08:13Z`——先前寫「13 分鐘後」不對應任何一種讀法）。
>   ⚠️ **`results/` 裡 grep `i5fail` 會撈到兩份，別把它們讀成同一件事**：另一份
>   `intake_wiring_zh.run1_i5fail.json`（檔名沒有 head 前綴）是**稽核前基線 `67cdf30`**
>   上的 FAIL（08-20 12:58→13:02），那是修復前的預期結果、不是本輪的飄動證據；
>   本輪的飄動只由帶 head 前綴的那份 `24d3083` 佐證。**留檔請一律把 head 寫進檔名。**
> - **部署現況（✅ 兩輪都已上線）**：後端與 React 前端都在跑新碼。
>   - **第一戰役（PR #55）後端 deployment `09b58ea3`**（2026-08-20 15:27 UTC 建立）——當時
>     **SUCCESS**，新碼確認在服務流量：
>     `https://gu-voice-app-production.up.railway.app/openapi.json` 的
>     `SOAPReportResponse` 與 `SOAPReportDetailResponse` **都有 `patient_facing_localized`**、
>     `GenerateReportRequest` **沒有 `required` 欄位**（＝body 全可選，舊碼是 `["session_id"]`）；
>     12/12 openapi 探針通過。migration `d2e3f4a5b6c7`
>     （`backend/alembic/versions/20260820_1000-soap_report_patient_facing_localized.py`）
>     已套用生產 DB、celery 與 Firebase 正常。
>     ⚠️ **今天 `railway deployment list` 看它會是 `REMOVED` 不是 `SUCCESS`**——那是被下面
>     第二戰役那次取代的正常狀態，**不是失敗**。查歷史部署時別把 `REMOVED` 讀成出事。
>   - 過程曾因 **Railway 平台事故（上游 GCP，事故編號 `VVL3A03V`）卡約 50 分鐘**未切流量，
>     期間依 runbook **未重送 `railway up`**——重送只會排進同一個壞掉的佇列。
>   - React 前端 alias 已切，bundle hash 與 `--prod` deployment 一致；生產
>     `locales/en-US/session.json` 有本輪新增的 `patientFacing`。
>   - 先前記載的「醫師端『重新產生報告』仍回 422」已隨後端上線解除。
>   - **第二戰役（PR #57 `3eacd50`）後端 deployment `79c5721a`**——
>     `2026-08-20T19:37:01Z` 建立、**SUCCESS**，`railway status --json` 顯示它就是
>     `production / gu-voice-app` 的 `activeDeployments`（instance `RUNNING`）；
>     新容器 log 的 celery banner 時間戳是 `2026-08-20 19:37:28`
>     ＝**建立到容器起來約 27 秒**。啟動 log 有「資料庫遷移完成」但**沒有 `Running upgrade` 行**
>     （head 已由 `09b58ea3` 那次套用完，本輪無新 migration，符合預期）。
>   - ⚠️⚠️ **兩次的驗證強度不一樣，這個差異要記住**：
>     - 第一次是 **schema 有變**（新增 `patient_facing_localized` 欄位、`GenerateReportRequest`
>       的 `required` 消失），所以 `/openapi.json` 是**外部可驗的硬證據**——新舊容器回不同的東西。
>     - 第二次是**純行為改動**（紅旗共現組 `cross_clause`、`sanitize_for_prompt` 剝除次數、
>       SOAP prompt 內部消毒），**API schema 一個位元都沒動**。於是
>       **任何外部探針都區分不出新舊容器**：`/openapi.json` 一模一樣、`healthz` 本來就恆綠。
>       能拿到的只有 **deployment id ＋ SUCCESS ＋ 它是 active ＋ 新容器 log**，
>       那是**推斷**不是端點證據。
>     - **未來所有純行為改動的部署都會遇到這個限制。** 想要硬證據就得事先埋
>       （例如 `/healthz/deep` 或某個 debug 端點回 build/commit 標識），
>       否則就誠實寫成「以 deployment id 與容器 log 推斷」，**不要假裝驗過端點**。
>   ⚠️ **`healthz` 綠不代表新碼上線**（舊容器一樣回綠）。schema 有變時要打 `/openapi.json`
>   找新欄位；schema 沒變時連這招都不管用，見上面那條。
>   這條與「grep -c 退出碼會讓沒命中被判成命中」已寫進部署手冊（PR #56 `6ecf10a`）。
> - **本輪新增／變更的不變式**已同步進 `voice-pipeline-invariants` skill 與 CLAUDE.md 鐵律，
>   TODO 這一份記的是**未結案的部分**（§S）。
> **2026-08-21 敵意複驗修復（第二戰役，PR #57 merge `5457b32`／內容 commit `3eacd50`）**
>
> - **由來**：第一戰役的文件同步 workflow 有一道敵意查證關卡，它抓到**我們自己的修復造成的
>   回歸與遺漏**——五個真缺陷，當時全部在 `6ecf10a` HEAD 上逐句可重現。
> - **已修（✅ 五條，`3eacd50`）**：
>   S7 紅旗跨子句漏報（`我今天小便，然後有很多血塊` → 零紅旗，是 `6fc51e3` 的回歸）、
>   S8 `soap_generator.py` 的 SOAP prompt 完全沒過 `sanitize_for_prompt`（D-1 只覆蓋對話路徑）、
>   S10 `sanitize_for_prompt` 的行首 `#` 只剝一次（`'# ## X'` → `'## X'`，消毒層自己漏）、
>   S11 終態 AST 跳閘器的形狀覆蓋面（**它從來就不是 HEAD 上可重現的缺陷**，見 §S 的 S11 開頭那個框；
>   與本輪同一個 commit 落地，該條記的是能力清單與刻意不做的部分）、
>   S12 越南文 `tiểu` 是「排尿」與「小／次要」的假朋友（`tiểu đường`＝糖尿病 → urosepsis critical）。
> - ⚠️ **仍未結案**：**S9**（`is_dont_know` 對含數詞的固定語誤判 → 真拒答被漏掉 → AI 換句話重問）
>   ——同一批發現裡**唯一沒人認領**的一條，第二戰役沒動它。
> - **新增未結案**：**S13**（`chief_complaint_text` 可繞過 §3b 必問安全 gate，
>   `injection_pseudosection_zh` e2e 實證）——**既有行為、非任一輪造成**，本輪只列管不改碼。
> - **驗收**：`backend venv/bin/pytest tests/unit -q` → **4743 passed / 2 skipped**
>   （2026-08-21 於 `5457b32` 重跑確認，與 commit message 自報一致；跑法＝**有**
>   `scripts/e2e_realopenai/results/*.json` 的工作副本，見下方總驗收段對兩種跑法的說明）；
>   真 OpenAI e2e 4 場全 PASS（torsion×2、hematuria_3b_en、新增 `injection_pseudosection_zh`
>   端到端證明偽區段不進 SOAP）＋ ruleprobe 36 例 ＋ preflight 11 情境。

---

## P0 — 阻斷級（上線前必修）

### [x] 1. 修 `auth_service.logout` 簽名不匹配 — 2026-04-17（待 commit）

- **檔案**：
  - `backend/app/services/auth_service.py:193`（定義）
  - `backend/app/routers/auth.py:122-126`（呼叫端）
- **要做**：
  - [ ] 重寫 `logout(db, user_id, refresh_token)`：內部 decode refresh token 取 jti 與 exp → 算 ttl → `redis.setex("gu:token_blacklist:{jti}", ttl, "1")`
  - [ ] 若 `refresh_token=None`，撤銷該使用者所有 refresh token（遍歷 Redis 或在 DB 有 sessions 表追蹤）
  - [ ] 加單元測試：登出後同一 access token 呼叫 `/api/v1/auth/me` 應回 401
- **驗收**：`curl -X POST /api/v1/auth/logout` 回 200，不再是 500

### [x] 2. Celery worker + beat 啟動 — 2026-07-26 改為同容器（原 2026-04-18 (1b7a41e) 的獨立 service 已不存在）

> ⚠️ **2026-07-26 更正**：本條原記載「worker + beat service 已 ACTIVE」是**假的**。實查 Railway 專案
> `gu-voice-api` 底下只有 `Redis` 與 `gu-voice-app` 兩個 service，worker/beat 不在（也不在任何其他
> Railway 專案）。因為 #31 把 SOAP 生成改成 Celery 單一路徑，這導致 #31/#32 一上生產每份 SOAP
> 就永遠卡 GENERATING（已實際發生一次，見 PR #34）。
>
> 現行做法：`backend/scripts/start.sh` 在同一個容器內起 worker + beat，由 `RUN_CELERY_IN_API`
> （預設 true）控制。要拆回獨立 service 時設 false 並照 `railway_celery_runbook.md` 建。
> **調大 `numReplicas` 前必須先把 beat 拆出去**，否則排程重複觸發。

- **檔案**：Railway Dashboard（不在 repo 內），可能需新增 `backend/scripts/start_worker.sh`、`backend/scripts/start_beat.sh`
- **要做**：
  - [ ] 在 Railway 專案建立 `gu-voice-celery-worker` service，`startCommand = celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2`
  - [ ] 建立 `gu-voice-celery-beat` service，`startCommand = celery -A app.tasks.celery_app beat --loglevel=info`
  - [ ] 兩個 service 共用同一 Redis、同一組 env vars
  - [ ] 手動觸發一次 `check_session_timeouts` 驗證
- **驗收**：Railway logs 能看到 `beat: Starting...` 與每 5 分鐘的 session timeout 檢查輸出

### [x] 3. Firebase Admin SDK 在 lifespan 初始化 — 2026-04-17（待 commit）

- **檔案**：`backend/app/main.py`、新增 `backend/app/core/firebase.py`
- **要做**：
  - [ ] 新增 `app/core/firebase.py`：`initialize_firebase()` 函式，從 `GOOGLE_APPLICATION_CREDENTIALS_JSON`（base64 decode）讀入
  - [ ] `main.py` lifespan 啟動階段呼叫（FCM_CREDENTIALS 未設時要 log warning 不 raise，方便本機開發）
  - [ ] 移除 `notification_retry.py:85` 的動態 import，改成檔頂 import
  - [ ] 測試：手動發一則推播驗證
- **驗收**：冷啟動後第一次推播即可送達，不會 `ValueError: default Firebase app does not exist`

### [x] 4. Alembic migration 補分區表定義 — 2026-04-18 (caa60ce)（已在 Railway 主 API deploy 成功跑過 `alembic upgrade head`）

- **檔案**：`backend/alembic/versions/` 新增一個 migration
- **要做**：
  - [ ] 新 migration：把 `conversations`、`audit_logs` 改成 PARTITION BY RANGE(created_at)
  - [ ] 建立當月 + 下月初始分區
  - [ ] `partition_manager.py` 只負責建新月份分區，不負責建 parent table
  - [ ] 在 staging 環境跑一次 `alembic upgrade head` 驗證
- **驗收**：新環境 fresh migrate 後，`\d+ conversations` 顯示 `Partitioned table, partition key: RANGE (created_at)`

### [x] 5. 修 Migration Enum 大小寫 vs ORM value 不一致 — 2026-04-18 (caa60ce)（已在 Railway 主 API deploy 成功跑過 `alembic upgrade head`）

- **檔案**：
  - `backend/alembic/versions/20260412_0302-c98fa7840c8c_initial_schema.py`（目前用 `'PATIENT','DOCTOR'`）
  - `backend/app/models/enums.py`（value 是小寫）
  - 所有 ORM model 的 `Column(Enum(UserRole))`
- **要做**：
  - [ ] ORM 改用 `Enum(UserRole, values_callable=lambda x: [e.value for e in x])` 強制存小寫 value
  - [ ] 寫 data migration：`ALTER TYPE userrole RENAME VALUE 'PATIENT' TO 'patient'` 等（PG 12+ 支援）
  - [ ] 相同處理 `sessionstatus`、`alertseverity`、`conversationrole` 等所有 enum
  - [ ] 前端 `enums.ts` 不變（已經是小寫）
  - [ ] 跑整合測試確認 register / login / create session 正常
- **驗收**：DB 直接查 `SELECT role FROM users LIMIT 1` 回 `patient`（小寫），API response 也是小寫

---

## P1 — 本週內

### [x] 6. JWT 黑名單檢查納入 `get_current_user` — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/dependencies.py`、`backend/tests/unit/services/test_get_current_user_blacklist.py`
- **要做**：
  - [x] `get_current_user` 在 `verify_access_token` 後，取 jti 檢查 `redis.exists("gu:token_blacklist:{jti}")`
  - [x] 有命中 → raise `UnauthorizedException("Token 已失效")`
  - [x] 單元測試：blacklist 命中 → 401；未命中 → 正常通過（`test_get_current_user_blacklist.py`，2 tests pass）
- **驗收**：登出後同一 access token 打 `/me` 回 401

### [x] 7. OpenAI 呼叫統一 timeout + retry + token 預算 — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/openai_client.py`（新增）、7 個 pipeline / websocket 呼叫點、`backend/tests/unit/services/test_openai_client.py`
- **要做**：
  - [x] `openai_client.py`：singleton `get_openai_client()`（`AsyncOpenAI(timeout=60)`）、`call_with_retry()`（tenacity AsyncRetrying，指數退避最多 3 次，白名單 `APITimeoutError / RateLimitError / APIConnectionError`）、`count_tokens` + `budget_messages`（保留 system、從頭部丟舊訊息）
  - [x] `llm_conversation.py`：`get_openai_client()` + `budget_messages` + `call_with_retry`（streaming 僅 create 時重試）
  - [x] `supervisor.py` / `soap_generator.py` / `red_flag_detector.py`：`call_with_retry` 包 JSON mode 呼叫
  - [x] `stt_pipeline.py`：每次重試重建 BytesIO；`tts_pipeline.py`：audio.speech.create 包 retry
  - [x] `websocket/conversation_handler.py` 中的動態 AsyncOpenAI 也切到 singleton
  - [x] 單元測試 8 tests pass（singleton、三類錯誤重試、非白名單不重試、上限 raise、budget 保留 system）
- **驗收**：測試模擬 RateLimitError 成功退避重試；模型 context_limit 被縮至極小時保留 system 並丟舊訊息

### [x] 8. Axios 401 refresh race 改用 shared promise — 2026-04-18（待 commit）

- **檔案**：`frontend/src/services/api/client.ts`
- **要做**：
  - [x] 把 `isRefreshing + failedQueue` 重寫成 `refreshPromise: Promise<string> | null`
  - [x] 401 時若 `refreshPromise` 已存在就 await 同一個，一次 `/auth/refresh` 對應所有併發請求
  - [x] Refresh 失敗：finally 清空 refreshPromise、`clearAuthAndRedirect()` 導回 login
  - [ ] 前端無 vitest / jest 設定，先以 type-check 通過 + `_getInflightRefresh()` debug hook 保留單測入口
- **驗收**：DevTools Network 裡，token 過期後只看到一次 `/auth/refresh` 呼叫；搭配後端 P1-#11 reuse detection 不會被自家併發踢掉

### [x] 9. Sentry 初始化 + 敏感資料過濾 — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/sentry.py`（新增）、`backend/app/main.py`、`frontend/src/services/sentry.ts`（新增）、`frontend/src/main.tsx`、`backend/tests/unit/services/test_sentry_redact.py`
- **要做**：
  - [x] 後端 `init_sentry()`：`traces_sample_rate=0.1, send_default_pii=False, before_send=redact_sensitive`，FastAPI/Starlette/Asyncio integrations；lifespan 啟動時呼叫，未設 DSN 時 log warning 不阻擋
  - [x] `redact_sensitive`：遞迴清洗 dict/list，凡 key contains `password / access_token / refresh_token / authorization / api_key / secret / jwt / cookie` 均取代為 `[Filtered]`
  - [x] 前端 `src/services/sentry.ts`：同樣策略，`beforeSend` + `beforeBreadcrumb` 都套 redact；未設 `VITE_SENTRY_DSN` 靜默跳過
  - [x] 單元測試 5 tests pass（Authorization / body password+tokens / 巢狀 / 非敏感欄位不動 / Set-Cookie 大小寫）
  - [ ] 手動 `raise Exception("test")` 實機驗證 — 留給 deploy 後以 API 客戶端觸發
- **驗收**：Sentry dashboard 能看到事件，且 payload 無密碼 / token

### [x] 10. Prometheus instrument 接上 — 2026-04-18（待 commit）

- **檔案**：`backend/app/main.py`
- **要做**：
  - [x] `Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)`
  - [x] 本機 `TestClient` smoke test：`/metrics` 回 200 + text format 指標
  - [ ] Railway Grafana 或外部 Prometheus scrape config — deploy 後配
- **驗收**：`curl /metrics` 拿到 text format 指標 ✅

### [x] 11. Refresh token rotation + reuse detection — 2026-04-18（待 commit）

- **檔案**：`backend/app/services/auth_service.py`、`backend/tests/unit/services/test_refresh_token_rotation.py`
- **要做**：
  - [x] 簽發 refresh token 時存 Redis：`gu:refresh:{user_id}:{jti} → 1`，TTL = token exp - now
  - [x] `refresh_token()` atomic 消耗舊 jti（`DEL` 回傳 0 即視為 replay）
  - [x] 偵測到 reuse → 掃 `gu:refresh:{user_id}:*` 全刪，並 raise `UnauthorizedException("Refresh token 重複使用，請重新登入")`
  - [x] `logout()` 帶 refresh → 同步刪 rotation 登記；未帶 refresh → 撤銷該 user 所有 refresh 登記
  - [x] 單元測試 5 tests pass（rotate 成功、replay 被拒、未登記 jti 拒、logout 清 rotation）
- **驗收**：用同一 refresh token 連呼叫兩次，第二次回 401 並把該 user 登出

---

## P2 — 當月

### [x] 12. `.env.example` / docker-compose / config.py 三者對齊（2026-04-18 完成）

- **檔案**：`backend/.env.example`、`docker-compose.yml`、`backend/app/core/config.py`、`backend/tests/unit/core/test_config_env_precedence.py`
- **已做**：
  - [x] `config.py`：`DATABASE_URL` / `REDIS_URL` 改用 `validation_alias`，顯式值優先於 `DB_*` / `REDIS_*` 元件；`_to_sync_db_url` / `_to_async_db_url` 雙向標準化驅動後綴，連 Railway/Heroku 的 `postgres://` 舊格式都吃
  - [x] `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`：自動偵測 `BEGIN` 當 PEM 內容、否則當路徑；Railway 常見的字面 `\n` 會自動還原成真換行；未設時 fallback 到 `*_PATH`
  - [x] `APP_LOG_LEVEL` → `LOG_LEVEL` 單一欄位，對齊 `scripts/start.sh` / `.env.example` / `docker-compose.yml`
  - [x] `.env.example`：方案 A（顯式 URL）/ 方案 B（元件）並列並加註解；JWT 兩種用法都寫
  - [x] `docker-compose.yml`：註解標明顯式 URL 走優先分支、HS256 是 dev 用替代
  - [x] 測試：`tests/unit/core/test_config_env_precedence.py` 15 項（URL 優先序 / 驅動標準化 / PEM-vs-path / `\n` 還原 / HS256 略過 PEM / LOG_LEVEL 單一來源）
- **驗收**：`venv/bin/python -m pytest tests/unit/ -q --ignore=tests/unit/api` → 96 passed；`from app.main import app` 乾淨載入

### [x] 13. Conversation 表加唯一性保證 + `updated_at`（2026-04-18 完成）

- **檔案**：
  - `backend/alembic/versions/20260418_1400-conversations_updated_at_and_seq_guard.py`
  - `backend/app/models/conversation.py`
  - `backend/app/services/conversation_service.py`
  - `backend/tests/unit/services/test_conversation_seq_lock.py`
- **已做**：
  - [x] 新 migration 加 `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` + BEFORE UPDATE trigger (`conversations_set_updated_at_trg`) 自動維護
  - [x] 新 migration 加 BEFORE INSERT trigger (`conversations_check_seq_unique_trg`) 檢查 `(session_id, sequence_number)` 跨分區唯一（**分區表無法 native UNIQUE 除非納入 partition key，所以走 trigger**）
  - [x] 偵測現存 dupes 的 `DO $$ ... RAISE NOTICE`，不強制失敗（conversations 目前僅開發資料）
  - [x] `ConversationService.create` 加 `pg_advisory_xact_lock(hashtext(session_id))` 序列化同 session 的 `MAX(seq)+1` 計算，消除併發 race，trigger 退居兜底
  - [x] Model 加 `updated_at: Mapped[datetime]`（不靠 SQLAlchemy onupdate，由 DB trigger 維護）
  - [x] 單元測試 2 項（lock 在 MAX select 之前、lock key 為 session_id 字串）
  - [x] 真 PG（本機 supabase_db）驗證：重複插入被擋、updated_at 隨 UPDATE 前進、5x 併發插入在 advisory lock 下拿到唯一序號 2..6
- **驗收**：`alembic upgrade head` 乾淨套用；單元 98 passed；併發寫不再重號

### [x] 14. Login rate limit + OpenAI per-user limit (2026-04-18)

- **檔案**：`backend/app/core/rate_limit.py`（新增）、`backend/app/routers/auth.py`、`backend/app/services/auth_service.py`、`backend/app/websocket/conversation_handler.py`、`backend/tests/unit/core/test_rate_limit.py`（新增）
- **要做**：
  - [x] `SlidingWindowLimiter`：Redis sorted-set + `ZREMRANGEBYSCORE`/`ZCARD`/`ZADD` 在 atomic pipeline 中跑；超限時從 `ZRANGE(0, 0, withscores)` 算 `retry_after`（ceil 到下一秒，不超過 window）
  - [x] `enforce_login_ip_rate_limit(ip)`：每 IP 每分鐘 10 次，`/auth/login` 路由從 `X-Forwarded-For` 第一段取 IP（Railway/Cloudflare 代理層），超過抛 `RateLimitExceededException`（HTTP 429，`scope="ip"`）
  - [x] `enforce_account_not_locked` + `record_login_failure` + `clear_login_failures`：連續 5 次失敗寫 `gu:rl:login_locked:{email}`（TTL 600s）並清計數；成功登入呼叫 `clear_login_failures`；email 一律 `.lower()` 避免大小寫繞過
  - [x] `AuthService.login` 流程：IP 檢查 → 帳號鎖定檢查 → 密碼驗證（失敗時 `record_login_failure` 再 re-raise `InvalidCredentials`）→ 成功時 `clear_login_failures`
  - [x] `enforce_llm_per_user_rate_limit(user_id)`：每 user 每分鐘 20 次；在 `_handle_audio_chunk` 於 `is_final=True` 後、STT 之前檢查（一次語音輪次算 1 次），超限走 WS `error` frame `{code: "RATE_LIMIT_EXCEEDED", retryAfter}` 並 return，不中斷連線
  - [x] 單元測試 12 項（sliding window 允許/阻擋邊界、IP 第 11 次觸發、空 IP 跳過、失敗計數第 5 次鎖且清計數、鎖定期間 enforce_account_not_locked 抛/未鎖通過、clear 清計數+鎖、大小寫混用不逃過、LLM 超限、多 user 互不影響、`user_id=None` 跳過）
- **驗收**：單元 110 passed；`from app.main import app` 乾淨；key 命名 `gu:rl:*` 便於維運 `SCAN` 分類

### [x] 15. WebSocket token 改 handshake message (2026-04-18)

- **檔案**：`backend/app/websocket/auth.py`（新增）、`backend/app/websocket/conversation_handler.py`、`backend/app/websocket/dashboard_handler.py`、`backend/app/websocket/connection_manager.py`、`frontend/src/services/websocket.ts`、`backend/tests/unit/websocket/test_auth_handshake.py`（新增）
- **要做**：
  - [x] 共用 `authenticate_websocket(ws, context)`：先 `accept()` → 試 `?token=`（legacy，有 warning log）→ 否則 `receive_text()` 等 handshake，5s 逾時；成功回 JWT payload，失敗統一 `close(4001)`
  - [x] `ConnectionManager.connect_session` / `connect_dashboard` 加 `already_accepted=False` 參數，讓 handshake 先 accept 後再註冊不會 double-accept
  - [x] `conversation_handler` / `dashboard_handler` 切換到共用 helper；保留舊查詢參數模式兼容一段時間
  - [x] 前端 `WebSocketManager.createConnection`：URL 不再帶 `?token=`；`onopen` 送 `{type:"auth", token:...}`（頂層 raw，不走 `this.send()` 的 WSMessage 信封）
  - [x] 單元測試 12 項（handshake 成功、legacy query 兼容、accept 只呼叫一次、`type=authenticate` alias、JWT 無效 / timeout / 非 JSON / 錯 type / 缺 token / 空 token / 非 dict JSON 都 close 4001）
- **驗收**：單元 122 passed；`from app.main import app` 乾淨；完全移除 query-param 路徑只需刪 `authenticate_websocket` 內 legacy 分支並確認日誌為 0

### [x] 16. Supabase RLS policy (2026-04-18)

- **檔案**：`docs/supabase_rls_policies.sql`（新增，約 260 行）
- **要做**：
  - [x] 4 個 helper function：`gu_current_user_role()`、`gu_is_admin()`、`gu_is_doctor_or_admin()`、`gu_current_patient_id()`（STABLE + SECURITY DEFINER，讀 `public.users` / `public.patients` 表判斷）
  - [x] `sessions`：病患經 patients.user_id = auth.uid() 推回 patient_id；醫師 `doctor_id = auth.uid() OR doctor_id IS NULL`（可接候補）；admin 全開；INSERT 限自己名下、UPDATE 限自己負責或 admin
  - [x] `soap_reports`：依 session ownership 判讀取；醫師 UPDATE 限自己負責的
  - [x] `red_flag_alerts`：同 soap；醫師 acknowledge 限自己負責或未指派
  - [x] `notifications`：`user_id = auth.uid()` 讀寫；admin 可讀全部
  - [x] Throwaway postgres:15-alpine 驗證：套用 SQL 乾淨；病患 A 讀 sessionB → **0 rows**；醫師 D（指派 A）看 2 場；醫師 E（未指派）看 1 場；admin 看 2 場／全表
- **驗收**：Throwaway 驗證全部 pass；所有 `DROP POLICY IF EXISTS` + `CREATE POLICY` 皆可重跑；service_role（後端 FastAPI）自動 bypass RLS 不影響現有邏輯

### [x] 17. Audit log 實際落表 + 7 年保留 (2026-04-18)

- **檔案**：`backend/app/core/middleware.py`、`backend/app/tasks/audit_retention.py`（新增）、`backend/app/tasks/__init__.py`、`backend/tests/unit/core/test_audit_middleware.py`（新增）、`backend/tests/unit/tasks/test_audit_retention.py`（新增）
- **要做**：
  - [x] Middleware 加 `_AUDIT_RULES` allowlist（15 條規則）：login / logout / register / change-password / reset-password / update-me / session-CUD / soap-review / red-flag-ack / export；UUID `resource_id` 從路徑 regex 抽出；GET / health 不寫
  - [x] `_persist_audit_entry` 用 `async_session_factory()` 獨立 session 插入 `audit_logs`；以 `asyncio.create_task` fire-and-forget；失敗只 log，不影響 response
  - [x] `_extract_client_ip` 支援 X-Forwarded-For 第一段；`_extract_user_id` 支援 UUID / str；user_agent 截斷 500 字
  - [x] 4xx / 5xx 也寫（details.status_code 納入），稽核查分析更完整
  - [x] 新 Celery task `cleanup_old_audit_partitions`：查 `pg_inherits` 枚舉 `audit_logs_YYYY_MM` 子分區；`_parse_suffix` 精準格式守護；`_cutoff_yyyymm` = (today.year-7)*100+month；對 cutoff 以前的分區 `DETACH` + `DROP`；單步失敗不阻斷其他；排程每月 1 日 04:00（錯開 partition_manager 的 25 日 03:00）
  - [x] 單元測試 18 項（7 項 rule matching、5 項 middleware 行為含失敗與 persist exception、6 項 retention 含 parse/cutoff/drop 主流程/detach 失敗不中斷/空分區）
- **驗收**：單元 140 passed；`from app.main import app` 乾淨；七年保留為 `RETENTION_YEARS=7` 常數，未來若合規要改只需一處

### [x] 18. CORS `allow_methods` / `allow_headers` 收緊 (2026-04-18)

- **檔案**：`backend/app/main.py`、`backend/tests/unit/core/test_cors.py`（新增）
- **要做**：
  - [x] `allow_methods` 明確列 `GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD`，不再用 `*`
  - [x] `allow_headers` 白名單：`Authorization`、`Content-Type`、`Accept`、`Origin`、`X-Requested-With`、`X-Request-ID`
  - [x] `expose_headers=["X-Request-ID"]` 讓前端能讀 request_id 對 log
  - [x] `max_age=600`（10 分鐘 preflight cache）
  - [x] 6 項單元測試（精確 methods、精確 headers、奇怪 header 不可列入、expose X-Request-ID、未允許 origin 不 echo、max_age 設定）
- **驗收**：單元 146 passed；任意 origin 拿不到 `Access-Control-Allow-Origin`；`*` + credentials 的瀏覽器 reject 模式杜絕

### [x] 19. HTTP 安全 header middleware (2026-04-18)

- **檔案**：`backend/app/core/middleware.py`、`backend/app/main.py`、`backend/tests/unit/core/test_security_headers.py`（新增）
- **要做**：
  - [x] `SecurityHeadersMiddleware`：HSTS（`max-age=31536000; includeSubDomains; preload`）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy: camera=(), microphone=(self), geolocation=()`
  - [x] `/docs` `/redoc` `/openapi.json` 走寬鬆集合（只留 HSTS + nosniff），避免打壞 Swagger UI
  - [x] 用 `setdefault` 不覆寫上游（Railway / Cloudflare）已設的 header
  - [x] `main.py` 最早 `add_middleware(SecurityHeadersMiddleware)` 確保最晚執行、最外層包所有 response
  - [x] 4 項單元測試（API 核心 header 齊全、/openapi.json 寬鬆、上游 header 不被覆寫、404 也帶 header）
- **驗收**：單元 150 passed；securityheaders.com 掃描可達 A 等（HSTS+nosniff+Frame+Referrer+Permissions 齊）

### [x] 20. Health check 加深度檢查 (2026-04-18)

- **檔案**：`backend/app/main.py`、`backend/tests/unit/core/test_health_deep.py`（新增）
- **已做**：
  - [x] `/api/v1/healthz/deep`：DB `SELECT 1` + Redis `PING`，各 2 秒逾時；全過 200、任一失敗 503 並回 `fail: <err>`
  - [x] `_deep_check_db` / `_deep_check_redis` helper 各自捕捉 `TimeoutError` 與一般 Exception，錯誤訊息不洩漏 stack trace 給外部
  - [x] 3 項單元測試（雙 ok / DB 失敗 / Redis 失敗）
- **驗收**：`curl /api/v1/healthz/deep` 回 `{"status":"ok","checks":{"db":"ok","redis":"ok"}}`；中斷 Redis 立刻看到 503 + `fail: ...`

### [x] 21. `backend/.dockerignore` 新增 (2026-04-18)

- **檔案**：`backend/.dockerignore`（新增）
- **已做**：排除 `.env*`（但保留 `.env.example`）、`venv/`、`.git/`、`*.log`、`__pycache__/`、`*.pyc`、`tests/`、`keys/`、`.pytest_cache/`、`.coverage`、`*.egg-info/`、`.mypy_cache/`、`.ruff_cache/`
- **驗收**：image build 不把本機開發密鑰 / venv / 測試資料包進去；單獨針對 backend service 的 context 顯著縮小

---

## P3 — 技術債 / 長期改善

### [~] 22. ~~前端型別補齊 + zod runtime validation~~ — 2026-07-26 作廢（Flutter 遷移）

- 原內容：`frontend/src/types/api.ts` 的 `unknown[]` 換具體 interface、新裝 `zod` 驗 API response
- **作廢理由**：這是 TS 生態的技術債，Flutter 端由語言本身解掉——Dart 靜態型別 + `flutter_app/lib/data/models/*.dart`
  的 `fromJson` 已是邊界轉型層。**不要因此在 Flutter 引入 freezed / json_serializable**，現行手寫 fromJson 夠用。
- React `frontend/` 下線前若仍要動，就當它是遺留碼庫的舊債，不要新投入

### [x] 23. GoRouter 補 `onException` — 2026-07-26 完成（PR #42，見 §G21）

- **剩這一條**：`flutter_app/lib/core/router/app_router.dart:54` 無 `onException`/`errorBuilder`，
  醫師端或 `/patient/bogus` 之類無效路徑會露出 go_router 未在地化的英文錯誤頁——kiosk 上不可接受。
  修法：`onException: (_, s, r) => r.go(prefixLngToPath('/', currentLng))`
- **已由 Flutter 結構性解決、不需再做**：loading 閘（`main.dart:17` bootstrap-before-runApp）、
  token 單一權威（`TokenStore` 單例取代 localStorage 之爭）

### [~] 24. ~~前端表單驗證~~ — 2026-07-26 作廢（Flutter 遷移）

- 原內容：Login / Register / 主訴選擇接 `react-hook-form` + `zod`；密碼至少 8 字含數字+字母
- **作廢理由**：`flutter_app/lib/features/auth/password_rules.dart:6-29` 的純函式驗證比原要求更嚴，
  且錯誤訊息天生走 `t()`（i18n 不用另接）。表單驗證在 Flutter 是 `TextFormField.validator`，
  不需要等價於 react-hook-form 的套件

### [x] 25. Mock mode 在 production 強制關閉 (2026-04-18)

- **檔案**：`frontend/vite.config.ts`
- **已做**：production mode 時 `define: { 'import.meta.env.VITE_ENABLE_MOCK': '"false"' }` 強制常數折疊，無論使用者環境變數怎麼設，build 產物都不再讀 mock 分支
- **驗收**：`npm run build` 通過；production bundle grep `VITE_ENABLE_MOCK` 僅剩字面 `"false"`

### [x] 26. Safari / iOS 音訊相容性 (2026-04-18)

- **檔案**：`frontend/src/services/audioStream.ts`
- **已做**：
  - [x] 新 `pickSupportedMimeType()`：以 `MediaRecorder.isTypeSupported()` 依序試 `audio/mp4`（Safari 優先） → `audio/webm;codecs=opus` → `audio/webm` → `audio/wav`，找不到則降回瀏覽器預設
  - [x] `AudioContext` 取得改成 `window.AudioContext ?? window.webkitAudioContext`，iOS < 14.5 的 WebKit 前綴也能 fallback
  - [x] `npm run type-check` + `npm run build` 雙雙通過
- **驗收**：iOS Safari 建立 MediaRecorder 不再拋 `Unsupported MIME type`；桌面 Chrome / Edge / Firefox 仍走 opus 最佳路徑

### [x] 27. 補一個硬編碼中文 — 2026-07-26 完成（PR #42，見 §G22）

- **剩這一條**：`flutter_app/lib/features/admin/screens/complaint_management_page.dart:349` 的
  `'顯示順序'` 是全碼庫唯一硬編碼中文，en-US admin 會看到中文標籤。
  補 `admin.complaints.fieldDisplayOrder` 到 5 語系（兩份 locales 都要，見 §G 最後一條）
- **原目標已達成**：en 缺 key 實測 0（525 個 `t()` key 在 5 語言全部命中），掛未結案會誤導

### [x] 28. E2E 測試 + GitHub Actions CI (2026-04-18)

- **檔案**：`.github/workflows/ci.yml`（新增）
- **已做**：
  - [x] `backend-tests` job：ubuntu-latest、Postgres 15 + Redis 7 services、Python 3.12、pip cache；跑 `pytest tests/unit/ -q --ignore=tests/unit/api`
  - [x] `frontend-checks` job：Node 20、npm cache；跑 `npm run type-check` + `npm run build`（lint 暫緩直到前端補 ESLint 設定）
  - [x] `e2e-playwright` job：`if: false` 留位；前端 happy path Playwright 待 Phase 5 追加
  - [x] Trigger：PR + push to main；YAML `"on":` 加引號避免 YAML 1.1 boolean 誤讀
- **驗收**：workflow 檔本機 `yaml.safe_load` 通過；後端 168 tests、前端 type-check / build 在 CI 都能重跑

### [x] 29. Redis DB index 分離 (2026-04-18)

- **檔案**：`backend/app/core/config.py`、`backend/app/tasks/__init__.py`、`backend/app/core/dependencies.py`、`backend/app/cache/redis_client.py`、`backend/tests/unit/core/test_redis_url_split.py`（新增）
- **已做**：
  - [x] `config.py` 加 `REDIS_DB_CACHE=0` / `REDIS_DB_CELERY_BROKER=1` / `REDIS_DB_CELERY_RESULT=2`；`_redis_url_with_db` 基於 `urlparse`/`urlunparse` 把 path 置換成 `/{db}`，保留 user/password/port/TLS scheme
  - [x] 三個 computed property：`REDIS_URL_CACHE` / `REDIS_URL_CELERY_BROKER` / `REDIS_URL_CELERY_RESULT`
  - [x] `app/tasks/__init__.py`：broker / backend 各走獨立 DB index → 以後 `FLUSHDB 0` 清 cache 不會誤炸 Celery queue
  - [x] `dependencies.py` + `cache/redis_client.py` 都改用 `REDIS_URL_CACHE`
  - [x] 5 項單元測試（三個 property 切對 DB / helper 保留 password / TLS `rediss://` 正常）
- **驗收**：單元 153 passed；本機 `redis-cli -n 0 KEYS '*'`、`-n 1 LLEN celery`、`-n 2 KEYS 'celery-task-meta-*'` 各自獨立

### [x] 30. 音檔生命週期管理 (2026-04-18)

- **檔案**：`backend/app/tasks/audio_lifecycle.py`（新增）、`backend/app/tasks/__init__.py`、`backend/app/core/config.py`、`backend/tests/unit/tasks/test_audio_lifecycle.py`（新增）
- **已做**：
  - [x] 新 Celery task `cleanup_old_audio_files`：掃 `audio_blobs` / Supabase Storage，刪除 `created_at < now - AUDIO_RETENTION_DAYS` 的 row + object；單步失敗只記 log 不中斷整批
  - [x] `AUDIO_RETENTION_DAYS=90` 為 config 常數，未來法規要改只需一處
  - [x] Beat schedule：每月 1 日 05:00 跑（錯開 04:00 的 audit retention 與 03:00 的 partition ensure）
  - [x] 5 項單元測試（cutoff 計算 / 空結果快退 / 部分失敗不中斷其他 / storage 錯誤只 log / DB 刪 0 筆直接結束）
- **驗收**：單元 158 passed；本機 `.delay()` 手動觸發後看到 log 輸出 `cleaned N audio files`

### [x] 31. `forgot_password` 實作 email 發送 (2026-04-18)

- **檔案**：`backend/app/core/email_client.py`（新增）、`backend/app/services/auth_service.py`、`backend/app/core/config.py`、`backend/.env.example`、`backend/tests/unit/services/test_forgot_password.py`（新增）
- **已做**：
  - [x] 統一抽象 `send_email(to, subject, html, text)`：依 env 自動選 `_SendGridClient`（`SENDGRID_API_KEY`）/ `_SmtpClient`（`SMTP_HOST` + `SMTP_USER`）/ `_LoggingEmailClient`（本機開發只印 log）
  - [x] `auth_service.forgot_password`：`secrets.token_urlsafe(32)` 產 token、Redis 存 `gu:reset:{token} → user_id`（TTL 1800s）、mail 內嵌 `{FRONTEND_BASE_URL}/reset-password?token=...`；對外回應永遠相同泛用訊息（`FORGOT_PASSWORD_GENERIC_MESSAGE`）避免 email enumeration
  - [x] `auth_service.reset_password`：讀 `gu:reset:{token}` → 取 user → `bcrypt` 新密碼 → 成功後 `DEL` 該 key（one-shot）
  - [x] 常數集中化：`RESET_TOKEN_KEY_PREFIX` / `RESET_TOKEN_TTL_SECONDS` / `FORGOT_PASSWORD_GENERIC_MESSAGE`
  - [x] `.env.example` 補 `FRONTEND_BASE_URL` / `SENDGRID_API_KEY` / `SMTP_*`
  - [x] 5 項單元測試（valid email 寫 Redis + 送信、不存在 email 仍回同訊息且不送信、正確 token 重設成功 + 清 key、錯 token 拋錯、過期 token 拋錯）
- **驗收**：單元 168 passed；本機未設 SENDGRID / SMTP 時走 `_LoggingEmailClient` 印出模擬 email，方便前端 QA 流程

### [x] 32. ~~`archive/專案開發進度.md` 更新~~ → 改成寫 `flutter_app/README.md` — 2026-07-26 完成

- **作廢理由**：`docs/archive/` 已明文宣告「勿當現行文件讀」（見 `docs/archive/README.md`），
  更新歸檔文件是白做工
- **取代物**：`flutter_app/README.md` 寫遷移現況（原本是 `flutter create` 樣板，新人看不出兩套前端關係）

---

## E — 真 OpenAI E2E 稽核發現（2026-06-28）

> 來源：[`e2e_realopenai_audit_2026-06-28.md`](archive/e2e_realopenai_audit_2026-06-28.md)（8 情境真 OpenAI E2E + 對抗式驗證，已對 DB 核實）。
> 依賴排序：A 群（紅旗/結束流程，同一 `conversation_handler.py` 區塊，需協調）→ B 群（SOAP/ICD）。先就 E7 臨床決策再實作 A3/severity。

### [x] E1. 🔴 D1 — 硬上限被紅旗 deferral 打穿，持續 high 紅旗（肉眼血尿）問診永不結束 — 2026-07-04 (a92a23f)

- **檔案**：`backend/app/websocket/conversation_handler.py:1702`（閘門）、`:1698-1701`、`:1649-1652`、`:289-290`
- **A1 [D5]**：空回應守衛（包 try/except 的單次 retry → 在地化 fallback 直接 `_spawn_tts_task`，因 `_SENTENCE_BOUNDARY_CHARS` CJK-only）
- **A2**：`hard_cap_reached` 抽成獨立旗標；閘門改純函式 `_should_conclude_now(...)`，硬上限不被 `soft_defer` 否決
- **A3**：硬上限對 late drain 做有界 inline 解析（late-critical 先 abort 再 conclude）+ `MAX_HARD_CAP_DRAIN_DEFERS` 絕對 backstop
- **驗收**：重跑 `hematuria_coop_en` → ~15 輪 `completed` 出 1 份 SOAP（現況 18 輪卡 `in_progress` 無 SOAP）；`test_auto_conclude` 加 `_should_conclude_now` 案例

### [x] E2. 🔴 D2 — `sessions.red_flag`/`red_flag_reason` 從不被對話紅旗或 aborted_red_flag 更新 — 2026-07-04 (a92a23f)

- **檔案**：模組級 `_update_session_status`（`conversation_handler.py:1985`，`.values` @`:2017`）；abort 呼叫 `:1656`、`:1628`
- **A4**：轉 `aborted_red_flag` 時 `.values(..., red_flag=True, red_flag_reason=<critical title>)`；WHERE 不動（終態保護不變）。語意維持「＝因紅旗中止」
- **驗收**：重跑 `torsion_critical_zh` → DB `red_flag=true, red_flag_reason IS NOT NULL`；新增 `test_update_session_status`

### [x] E3. 🔴 D3 — 紅旗非冪等（同一紅旗每輪重複送，肉眼血尿 18×） — 2026-07-04 (a92a23f)

- **檔案**：`_persist_and_emit_alert`（`conversation_handler.py:1410-1503`）；`red_flag_detector.py` canonical_id
- **A5**：加跨輪去重（Redis hash `session:{id}:emitted_red_flags`，record-on-success，**升級放行** high→critical）；不可過濾 abort 用的 `red_flag_alerts`
- **驗收**：重跑 `hematuria_coop_en` → `red_flag_alerts` 僅 1 筆（原 18）；single + escalation 單元測試

### [x] E4. 🟡 D4 — `soap_reports.language` 恆 zh-TW — 2026-07-04 (a92a23f)

- **檔案**：`conversation_handler.py:1819-1832` SOAPReport 建構子
- **B3**：補 `language=session_context.get('language') or settings.DEFAULT_LANGUAGE`（`or DEFAULT` 承重，避免 NULL→IntegrityError 靜默掉 SOAP）、`icd10_verified=...`（依賴 B2）
- **驗收**：en/ja 場次 `soap.language` 正確；歷史回填見 E7 決策

### [x] E5. 🟡 D5 — 空 AI 回應 turn（空泡泡） — 2026-07-04 (a92a23f)

- 併入 A1（見 E1）。新增 `test_empty_response_fallback`（retry-raises 仍送 `ai_response_end`、en-US ASCII-`?` 至少 1 個非空 chunk）

### [x] E6. 🟢 D6 — ICD-10 缺漏（ED 應 N52.9、PSA 應 R97.20） — 2026-07-04 (a92a23f)

- **B1**：`icd10_validator` 白名單加 `N52`/`R97` + `icd10_symptom_map` 加 ED/PSA（同一 commit）
- **B2**：抽共用 `resolve_symptom_id`（讀 `name_en`）；`_generate_soap_report_async` `selectinload(chief_complaint)` 把 `symptom_id` 傳進 `generate()`（無此步 verified 永遠 False）
- **驗收**：ED/PSA `icd10_codes` 非空 + `icd10_verified=true`

### [~] E7. 臨床拍板決策 — 2026-07-04 已採保守預設實作（可翻案）

- 實作採用的預設（a92a23f）：(1) 持續 high 至硬上限收 `completed`（只有 critical abort，維持現行語意）；
  (2) 偵測器真卡死 → `MAX_HARD_CAP_DRAIN_DEFERS`(2) 輪後強制收尾出 SOAP；(3) `session.red_flag` 語意
  ＝「因紅旗中止」，high-only completed 不設 true（「曾有紅旗」查 `red_flag_alerts`）；(4) R97 接受
  prefix-3 粗粒度；(5) D4 歷史回填不做。任一項臨床端有不同意見時再翻案（kill-switch 已備）。詳見稽核 §四

### [x] E8. 🟡 驗收過程新發現（2026-07-04 真 OpenAI E2E）— 2026-07-04 全部修復（本輪）

- **abort 後 WS 對話仍繼續**：critical abort 後 server 對已中止場次續答（每輪重發 abort 事件）；
  AI 話術正確（告知現場醫護）但場次應考慮拒收後續 text_message
- **`_validate_session` TypeError**：建場次不帶 `chiefComplaintText` 直接打 API →
  `shared.py`（render 紅旗時對 ChiefComplaint ORM 物件做 substring）炸 internal_error 斷 WS
  （前端固定會帶所以線上未觸發）
- **`sessions.started_at/completed_at` 恆 NULL**
- **en-US 場次紅旗 alert title 仍是中文**（「肉眼血尿」；code 內已有 TODO-E6 註記）
- **#2 防重問殘留（第一輪邊界）**：首輪 Supervisor guidance 尚不存在時，病患說不知道
  仍可能被 conversation LLM 換句話重問一次（第二次說不知道後不再發生）；
  修法方向＝conversation prompt 對「開場即拒答」補一條規則

---

## F — 使用回饋第三輪（2026-07-03 回報，2026-07-04 已全部修復）

> 來源：使用者院內 Kiosk 實測回饋 5 題。根因調查 + 20-agent workflow（設計→並行實作→
> 5 視角審查→對抗式驗證→修正）完成，後端 662 unit 全綠、前端 tsc/lint/build 綠、
> 主訴 e2e 7 案例綠。架構說明已同步 `app_architecture.md` §2.1／§2.2.1／§7。
> **尚未部署**：Railway 需跑 alembic migration（其他主訴 seed）並檢查 env（見 F1）。

### [x] F1. #3 帳號一直跳掉 — 2026-07-04 (5e6566e)

- 根因：M-22 httpOnly-cookie refresh 在 Vercel↔Railway 跨站結構性失效（SameSite=lax 不送
  cookie、CSRF cookie 跨站讀不到）+ access token 因 `.env` 變數名 `JWT_` 前綴被靜默忽略、
  實際只有 15 分鐘
- 修法：refresh/logout 依 token 來源分路（有 cookie 必驗 CSRF；無 cookie 走 body 豁免 CSRF）、
  body 恢復下發 refresh_token 由前端 localStorage 保管、config 加 AliasChoices、
  WS token 改 provider 每次取最新、hydrate 不再蓋回舊 token
- **部署必查**：Railway 若設有 `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`，alias 上線後會開始生效，
  建議統一改 canonical `ACCESS_TOKEN_EXPIRE_MINUTES=30`

### [x] F2. #2 病患說「不知道」仍被換句話重問 — 2026-07-04 (40c2f42)

- 根因：全機制只認「已明確回答」二元狀態，don't-know 欄位永留 missing_hpi、完成度卡 80 以下
- 修法：Supervisor prompt 補 don't-know 第三態（視為已盡力採集）+ 兩處防重問護欄擴充並升級硬性（5 語）
- **驗收待做**：prompt 層修復，需真 OpenAI 情境重放驗證（病患連答「不知道」→ next_focus 不再指向該欄）

### [x] F3. #4 手動語音控制（暫停/繼續、「我說完了」）— 2026-07-04 (eb4993e)

- 新增暫停/繼續鈕（同步後端 pause_recording/resume_recording）與「我說完了」鈕（forceEndSegment）
- `shouldUnmuteVAD` 純函式決策矩陣統一八個 unmute/mute 掛點（56 案例測試）；userPaused 與
  AI 出聲硬鎖分離。review 加修：重播鍵永久卡死 VAD（high）、斷線未停本地 TTS 即解鎖

### [x] F4. #6 辨識中回饋 + 空辨識提示 — 2026-07-04 (eb4993e)

- sttProcessing 疊 spinner + 醒目徽章；空 stt_final 不再靜默（「沒聽清楚」4 秒提示 + 照舊 re-arm VAD）

### [x] F5. #5 主訴「其他」選項 — 2026-07-04 (e43144f)

- 「其他」sentinel seed（UUID `00000000-0000-4000-8000-0000000000ff`、migration `20260704_1000`）；
  含「其他」自述必填；開場語特判念病患自述。退化（graceful）：ICD-10 unverified、紅旗退全量清單

### [x] E9. 🟡 紅旗規則層可靠性 — 2026-07-04 工程項完成（本輪）

- [x] 空表 fallback：`red_flag_rules` 查詢成功但 0 筆時也 fallback 內建 8 條（規則層生產首次真正
  啟用）；kill-switch `RED_FLAG_BUILTIN_RULES_FALLBACK`（預設開）；DB 有 ≥1 筆則尊重 DB 不混用；
  載入時 log warning
- [x] 多語 triggers：規則比對改「全語言聯集」（頂層 + `triggers_by_lang` 全部，跨語言混講也命中，
  fail-open）+ 英文 case-insensitive；內建 catalogue 補齊 ja/ko/vi triggers（24 組）
- [x] AI 術語稽核（56 詞條）：3 筆明確錯誤已修（ja「腎仙痛」錯字→「腎疝痛」、ko 睪痛語序、
  vi「lú lẫn」太寬鬆會誤觸發 critical→「rối loạn ý thức」）

### [x] H6. 🔴 `end-for-language-switch` 在生產從來沒成功過 — 2026-07-27 修復（PR #47）

部署 #46 後驗收時抓到的 500。根因：`AuditAction.LANGUAGE_SWITCH_END_SESSION`
（`models/enums.py:132`）自加入以來**沒有任何 migration 把它寫進 DB 的 `auditaction` type**
→ 只要走到寫 audit log 就 `InvalidTextRepresentationError`。

**這不是 #46 造成的**：舊碼同樣呼叫該 action（`HEAD~1:510`）。先前沒被發現，是因為
唯一會走到 audit 的路徑（active 場次真的切語言）在 React 端只顯示「切換失敗」的 toast，
看起來像使用者操作問題。#46 把終態改為冪等後，終態路徑也會走到 audit，才讓它浮出來。
**也就是說：React 使用者在問診中切語言，一直都是失敗的。**

- migration `c1d2e3f4a5b6`：`ALTER TYPE auditaction ADD VALUE IF NOT EXISTS`。
  PG12+ 可在交易內執行；降級刻意 no-op（PostgreSQL 無 DROP VALUE，對七年保留的稽核表
  重建 type 風險遠高於留一個未使用的值）
- 生產 enum 逐一比對：只有這一個漂移
- **加防護測試**：掃 migration 檔確認每個 `AuditAction` 值都出現過。新增成員卻忘了寫
  migration 就會紅（移走 migration 驗證過會失敗）

## V — Flutter 尚未驗證項（2026-07-27 盤點）

> 這一節記的是**「沒人試過」**而不是「試過有問題」。§G 的清單是缺陷，這節是**未知**。
> `flutter analyze` + `flutter test` 全綠不代表這些能用——本輪就有兩次靜態全綠但 app
> 在真機一片紅（`markNeedsBuild during build`、`GoError`）。
>
> **現況一句話（2026-07-27 更新）：病患端非語音全流程已真跑驗畢（V2），
> 但麥克風／VAD 路徑仍是零實測（V1）——而語音就是這個 app 的存在理由。**

### [ ] V1. 🔴 麥克風路徑從未在 Flutter 上跑過一次

app 的存在理由。§G 的四條語音修法**全部只靠單元測試與讀碼推論**，沒有任何一次真的對麥克風講過話：
- G3 `onSpeechEnd` 缺 hard-mute → AI 自己的喇叭回音被當成病患下一句
- G4 `stopActive()` 在 await 後才捕獲 `_activeStep` → VAD 提前解鎖 + completer 洩漏
- G14 `pause()` 順序 → 病患半句症狀消失、狀態列卡「正在辨識」
- G15 `onSpeechStart` 無硬鎖 re-assert

**最小驗證**：iOS Simulator **可以用 Mac 的麥克風**，不必實機。跑完整病患流程
（選主訴→intake→真的講話→STT/TTS/VAD→SOAP），並特別驗：
暫停時半句話有沒有進逐字稿／AI 講話時麥克風是否被鎖／TTS 中斷後 VAD 是否恢復／
紅旗情境是否導到正確的感謝頁變體（G1）。會用到真 OpenAI 額度。

### [x] V2. 病患端全流程已驗（2026-07-27，**文字代替語音**）

`integration_test/patient_text_flow_test.dart`，iOS Simulator 對本機後端＋真 OpenAI，
兩情境都過並用 DB 佐證：

| 情境 | 場次終態 | 逐字稿 | SOAP |
|---|---|---|---|
| `normal`（頻尿 4 輪） | `completed` | 9 則（病患 4／AI 5） | `generated`、`zh-TW`（不變式 #12） |
| `redflag`（睪丸扭轉 1 句） | `aborted_red_flag` | — | `generated`，紅旗 1 筆 |

涵蓋：登入→選主訴→intake→WS auth handshake→`text_message` 往返→AI 追問→
紅旗中止＋G1 感謝頁變體→結束問診→SOAP（Celery 路徑）。

**這一輪抓到 3 個只有真跑才會出現的缺陷**，都已修：

1. `UnmountedRefException`／`_debugCallbackStack` assert——在飛的 mic frame 與
   `_ws.disconnect()` 自己發的 `_statechange` 晚於 provider dispose 抵達，
   **病患一離開對話頁就炸**。修法：`_disposed` 閘門 + `_wsOn` 統一入口。
2. **按「結束問診」完全沒反應**——後端 `end_session` 回的 `session_status` 沒帶
   終態 `status`（`extra` 沒填），前端 handler 認不出。修在後端（回歸測試
   `tests/unit/websocket/test_end_session_status_extra.py`）。
3. 前端若改成「送出即本地設 completed」會**丟掉整場**：導頁 → autoDispose →
   `_ws.disconnect()` 早於 `end_session` 送達，場次停在 `in_progress`、SOAP 不生成。
   已在 `endSession()` 註記為不可再犯。

**仍未涵蓋**：麥克風路徑（見 V1）。文字輸入繞過 VAD，所以 G3／G14／G15 依然沒被驗過。

跑法（每次都要重新授權——`flutter test` 重裝會重置 TCC）：

```
xcrun simctl privacy <udid> grant microphone com.guvoice.guVoice
flutter test integration_test/patient_text_flow_test.dart -d <udid> \
  --dart-define=API_BASE=http://127.0.0.1:8000/api/v1 \
  --dart-define=WS_BASE=ws://127.0.0.1:8000/api/v1/ws \
  --dart-define=E2E_PATIENT_EMAIL=... --dart-define=E2E_PATIENT_PASSWORD=... \
  --dart-define=E2E_SCENARIO=normal|redflag
```

⚠️ 沒先授權麥克風的話 `start()` 會卡在 `await openMic()`，**WS 永遠不連**
（`_ws.connect` 排在它後面），症狀是 `WsConnState.connecting` 逾時。

### [ ] V3. 🟡 TTS 從未實機播過音

有 5 條回歸測試但用 fake player。對抗式驗證指出兩個結構性盲區：
- fake 用 broadcast stream，真 player 是 `BehaviorSubject.seeded` →
  **「陳舊 completed 被重播」整類 bug 測不到**
- 2 隻存活突變未被釘住：第三道 epoch 守衛、`clearQueue` 的 chain reset

### [ ] V4. 🟡 Flutter Web 語音已進 staged production，待實體麥克風驗證（HIGH risk）

2026-08-17 已部署固定預覽 `https://gu-voice-flutter-preview.vercel.app`，並驗過 release build、
78 tests、五語 deep link、Railway CORS 與測試病患登入。**尚未用真人麥克風驗 STT/TTS/VAD**，
所以只能說非語音頁與登入可用；未完成 `docs/flutter_web_cutover.md` 的 voice checklist 前不得 promote。

⚠️ **2026-08-20 更新**：稽核找到的 IN-1（intake `no_*` 由空清單推斷＝捏造病歷）被列為
Flutter Web promote blocker，已於 `931b9b7` 修掉（見 §S）。**但 promote 前提完全不變**——
V4 擋的是實體麥克風驗證，那條仍未做（見 V1 與檔頭未竟事項），不要因為少一個 blocker 就 promote。

### [ ] V7. 🟡 iOS 醫師端（報告/通知/APNs 推播）— 2026-08-20 拍板新方向

**平台分工拍板：Web＝病患語音問診（kiosk），iOS＝醫師端查看報告與通知，不做語音問診。**
影響：實體麥克風驗證（V1/V4）只需針對 Web；iOS 的麥克風/MicProbe/TCC 坑不再是 blocker。
iOS 這條線的待辦：醫師登入後的角色分流、通知列表與 SOAP 報告查看頁、APNs 推播
（simulator 開發期用 `xcrun simctl push` 模擬；真機/TestFlight 需 Apple Developer 的 .p8 推播金鑰）、
TestFlight 發佈管道（**見 §V8**——2026-08-21 從 §V6 拆成獨立條目，別再回頭找已勾選的 §V6）。

**2026-08-21 進度**：TestFlight 打包管道已備妥（圖示、出口合規、ExportOptions、六關腳本），
簽章憑證補齊後**首顆 build 已上傳、TestFlight 狀態「準備測試」**（見 §V8）；
還沒建內部測試群組、還沒在真機上裝過、推播也還沒端到端驗過。
APNs 推播金鑰（.p8）存在於 **repo 之外**——**絕對不得複製進 repo**，`.gitignore` 已補上
`*.p8`／`*.p12`／`*.cer`／`*.certSigningRequest`／`*.mobileprovision`／`AuthKey_*` 排除。

⚠️ **發佈管道現況、送測前未解的資料風險（含逐條 file:line）、以及「加第 2 個測試人員之前」
的完整前置條件，一律見 §V8**（2026-08-21 從 §V6 拆出的獨立條目）；設定值見
[`ios_release_settings.md`](ios_release_settings.md)。**拍板：第一版只裝使用者自己一台。**
⚠️ `ExportOptions.plist` 的 `testFlightInternalTestingOnly=true` **已證實生效**（2026-08-21，
build 在 ASC 上標「內部」），但它擋的是**散佈**不是**資料**，**不是 PHI 護欄**——
擋 PHI 的仍然只有那個拍板本身（理由見 §V8）。

### [ ] V5. 🟡 Android 完全沒碰

本輪只跑 iOS simulator。release 簽章缺 keystore 會刻意失敗（G37 的設計），
**連 release 包都出不來**，更沒在 Android 裝置上跑過。Android emulator 連本機後端要用 `10.0.2.2`。

### [x] V6. Flutter Web staged deployment 管道 — 2026-08-17

沿用 Vercel `chuns-projects-068de742/gu-voice`，FVM 固定 Flutter 3.41.3；
`flutter_app/tool/build_vercel_output.sh` 會 analyze、test、CSP release build 並產生 Build Output API。
固定 staged alias 為 `https://gu-voice-flutter-preview.vercel.app`，正式 React alias 尚未切換；
rollback deployment 已記錄。**Android 內部測試管道仍未建立**，另案追蹤（見 §V5）。

**iOS TestFlight 發佈管道另案追蹤：見 §V8。**（2026-08-21 拆出——它原本整段寫在這個
**已勾選、標題是 Flutter Web、日期 08-17** 的 §V6 底下，掃 checkbox 的人會讀成已完成。）

### [ ] V8. 🟡 iOS TestFlight 發佈管道 — 2026-08-21：**首顆 build 已上傳，TestFlight 狀態「準備測試」**；待建內部測試群組、加測試員、真機安裝與推播驗證

**✅ 2026-08-21 20:46 首次上傳完成。** 首顆 build（版本 1.0.0，號碼見總表 §7）已通過 ASC 自動處理，
狀態**「準備測試」**，而且在 TestFlight 建置版本清單上標著「**內部**」。上傳前
`xcrun altool --validate-app` 回 "VERIFY SUCCEEDED with no errors"，`--upload-app` 傳輸十秒出頭。
**✅ 沒有卡 "Missing Compliance"**——`ITSAppUsesNonExemptEncryption = false` 那一修生效了，
省掉人工到 ASC 網頁回答出口合規問卷這一步。
⚠️ **90 天到期的倒數已經開始跑**（build 不能刪、只能等它過期）。
**build number／Delivery UUID／大小／到期日／群組與測試員狀態，一律見
[`ios_release_settings.md`](ios_release_settings.md) §7**——那份是 iOS 所有設定值的唯一權威來源，
本節不重抄值，只留風險、理由與踩過的坑。

**⬜ 還沒做的**：建內部測試群組、把自己加進去、真機安裝（確認不是白畫面）、推播端到端驗證、
年齡分級問卷、隱私政策 URL。清單見總表 §9，操作步驟見 `deployment_guide.md` 二、。

**2026-08-21 20:26 打包端到端驗證通過。** 六關全跑真簽章，產出 `build/ios/ipa/gu_voice.ipa`
（24MB），第 6 關全綠：`aps-environment = production`、`get-task-allow = false`、
`Assets.car` 2,285,304 bytes、`CFBundleIconName = AppIcon`、
`ITSAppUsesNonExemptEncryption = false`。archive 497s、export 53s。
`aps-environment = production` 同時證明 **App ID 已有 Push Notifications capability**。
操作細節與 `testFlightInternalTestingOnly` 的證據見 `docs/deployment_guide.md` 二、。

> ⚠️ **第 5 關（真簽章 `flutter build ipa`）第一次跑必然失敗一次，這是新的已知坑。**
> codesign 首次使用剛建好的私鑰時 macOS 會跳**鑰匙圈授權對話框**，腳本是非互動情境 ⇒ codesign
> 直接失敗，而 `flutter build ipa` 顯示的錯誤只有
> `exportArchive codesign command failed (... Flutter.framework: replacing existing signature`
> ——**「replacing existing signature」是 codesign 的正常訊息、不是失敗原因**，真正的原因被 Flutter
> 截掉了，照字面去查會查錯方向。按對話框「允許」（選 Always Allow）之後，archive 已經在了，
> **直接跑 `xcodebuild -exportArchive -allowProvisioningUpdates` 即成功**，不必重編。
> ⚠️ 而且 `flutter build ipa` 在 export 失敗時**仍回傳 exit 0**——**唯一判準是
> `build/ios/ipa/*.ipa` 存不存在**，第 6 關就是靠這個擋下來的（這次它真的擋到了）。

⚠️ **Team ID 曾經是錯的**：`A73R7M7VB9`（基線 commit `2aa0ff9` 就寫死在 pbxproj、從未有人驗證）
是錯的值。2026-08-21 使用者登入 Xcode 後由 Xcode 自行改寫 pbxproj 三處，本輪已把
ExportOptions／打包腳本／三份文件共 11 處一併更正（正確值見
[`ios_release_settings.md`](ios_release_settings.md) §1——**值只留那一份**，這次繞遠路正是因為
同一個值散在四個地方）。
**當時的下游疑慮：APNs 金鑰是哪個 team 產的無法從檔案判斷**（`.p8` 不含 team ID）——
若不屬於簽 App 的那個 team，推播一定不通且後端 log 與前端都零徵兆。
✅ **2026-08-21 已到 developer.apple.com → Keys 實查，歸屬正確**（見總表 §5）。日後換 team 要重驗。

> 2026-08-21 從 §V6 拆出來的獨立條目。§V6 是**已結案的 Flutter Web** 管道（08-17、已勾選），
> iOS 這條當時**一包都還沒上傳過**，寄生在那底下會被讀成已完成；現在雖然傳出去了，
> **內部測試群組、真機安裝、推播驗證都還沒做**，所以這一條仍然是未勾選的。
> 操作步驟一律見 [`deployment_guide.md`](deployment_guide.md) 二、、設定值見
> [`ios_release_settings.md`](ios_release_settings.md)；**本節是全 repo 唯一持有**
> **這組風險 file:line 的地方**，SKILL.md／deployment_guide／README／腳本 banner 只留濃縮敘述並指回這裡。

已備妥的東西（這裡只記狀態，操作步驟不重抄）：

- `flutter_app/tool/build_ios_testflight.sh` — 六關打包腳本（前置檢查／build number／
  後端位址斷言／analyze+test／`build ipa`／產物驗證），開頭與結尾各印一次資料風險 banner。
- `flutter_app/ios/ExportOptions.plist` — 各 key 的值見 [`ios_release_settings.md`](ios_release_settings.md) §4。
  兩個要記住的理由：`method` 用正名 `app-store-connect`（`app-store` 已是 deprecated 別名）；
  `destination=export` 是刻意的，先出本機 .ipa 跑完產物驗證才由人上傳。
- `flutter_app/tool/gen_app_icons.py` — 從 `frontend/public/logo.png` 產 15 張 App Icon ＋ 3 張 LaunchImage，
  `--check` 缺檔就 exit 1（順帶驗 1024 那張無 alpha）。`.gitignore` 原本的 `*.png` 讓圖示永遠進不了版控，
  已補**三條窄白名單**（asset catalog／Android mipmap／web icons）。
  ⚠️ **不要「簡化」成 `!flutter_app/**/*.png`**——這是**公開** repo 而且是醫療系統，一放寬，
  任何人隨手把醫師 dashboard 或 SOAP 報告的截圖放進 `flutter_app/` 就會 commit 出去，
  且 git 歷史清不乾淨。理由寫在 `.gitignore` 那幾行的註解裡，改之前先讀。
  ⚠️ **它靠 `backend/venv` 的 Pillow，而 `backend/requirements.txt` 沒有列 Pillow**（自己 grep 可證）
  ——所以**任何一次重建 venv 之後都必然缺**，`--check` 會以 `ModuleNotFoundError` exit 1，
  和「圖示缺檔」同樣是 exit 1、分不出來。打包腳本已改成**先探測 `import PIL` 再跑 `--check`**，
  缺 Pillow 時分開報並給 `backend/venv/bin/pip install Pillow`（先前會誤報「圖示資產不齊全」，
  照那個指引去重跑 `gen_app_icons.py` 又會以同一個原因再爆一次＝死路）。
  **刻意不改 `requirements.txt`**：Pillow 是這支打包工具的相依，不是後端執行期相依。
- `flutter_app/ios/Runner/Info.plist` 的 `ITSAppUsesNonExemptEncryption = false`——少了它 build 會卡在
  App Store Connect 的 "Missing Compliance"，內部測試也一起被擋。

已實測通過（2026-08-21，Xcode 26.6 Build 17F113）：

- `fvm flutter build ipa --release --no-codesign --dart-define=API_BASE=… --dart-define=WS_BASE=…`
  → **exit 0**，47.1s，產出 `build/ios/archive/Runner.xcarchive`（185.6MB）
  ＝ Flutter 3.41.3 能對 Xcode 26.6 的 iOS 26 SDK 乾淨編譯。
- 產物：`Assets.car` 2,285,304 bytes（改動前**完全不存在**）、
  `CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName = AppIcon` 已被 actool 注入
  （⚠️ **頂層沒有 `CFBundleIconName`**，Xcode 26.6 的 actool 只吐巢狀那兩份，照字面斷言頂層會誤擋正常 build）、
  `ITSAppUsesNonExemptEncryption = false` 已進 bundle。
- `fvm flutter clean` → 重跑 `pub get` ＋ `pod install` 後 `git diff ios/Podfile.lock` **零變動**
  （證實 3.41.3 是對的工具鏈），並補回原本缺失的 `ios/Pods/Manifest.lock`
  （缺它 Xcode 會直接 Archive 在 `[CP] Check Pods Manifest.lock` 失敗）。
- ⚠️ **一律用 `fvm flutter`**：PATH 上的裸 `flutter` 是 homebrew 3.47.0，它 SPM 預設開，
  會把 `.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true` 並動到 Podfile.lock。
  「SPM／CocoaPods 半切換」不是架構問題，只是跑錯 SDK。

✅ **當日稍早的卡點已解除（保留紀錄，因為換機器會再撞一次）**：那時
`security find-identity -v -p codesigning` → **0 valid identities found**、
`~/Library/MobileDevice/Provisioning Profiles/` 目錄不存在、Xcode 未登入任何 Apple ID
→ **產不出已簽章的 .ipa**，腳本第 1 關擋在這裡並印出修法（含「team 名稱標 (Personal Team)＝免費帳號＝
永遠拿不到 Distribution 憑證」的判別）。⚠️ **登入 Xcode 不會自動產生 Distribution 憑證**，
要自己去 Accounts → Manage Certificates… 建——這是當天卡最久的一步。
憑證補齊後第 5 關已端到端跑過（見上），**「第 5 關零覆蓋」的敘述已過期**。

**第 6 關已不再是零覆蓋（2026-08-21 補）**：腳本新增 `--verify-only=<path/to/.ipa 或 .app>` 模式，
跳過第 1e 簽章關與整個 build，只跑產物驗證。已用 ad-hoc 簽章（`codesign -s -`）造出的測試產物
把 6a–6f 逐關實跑過：production／development 兩種 `aps-environment`、`get-task-allow` 三態、
build number 不符、`.ipa` 與裸 `.app` 兩種輸入、以及 codesign 輸出無法解析時的錯誤分支，
全部走到並印出預期訊息。**憑證到手那天不必第一次面對這幾十行。**

⚠️ 實跑時抓到一條真缺陷並已修：`codesign -d --entitlements :-` 在本機（macOS 26.5.1／Xcode 26.6）
吐的是**單行緊湊 plist**，舊版那支「假設 `<key>` 與 `<string>` 分行」的 sed 備援對它回**空字串**
→ 會把**解析失敗**誤報成「Apple 後台沒勾 Push Notifications」，把人送去改一個沒壞的東西。
現在先 `plutil -convert xml1` 正規化再解析，正規化失敗時**誠實報「解析失敗」**並保留原始輸出。

⚠️ **build number 沒有遞增機制**：`pubspec.yaml` 的 `CFBundleVersion` 解析為 `1`；
TestFlight 要求同一 `CFBundleShortVersionString` 下單調遞增，重複的會被拒。打包一律由腳本用
`date -u +%Y%m%d%H%M` 覆寫。✅ **2026-08-21 已證實 ASC 收 12 位數整數**（首顆 build 就是這個格式），
先前「超過 uint32、尚未證明 ASC 收」的殘留風險解除。腳本的格式斷言收的是
**最多三段句點分隔的非負整數**，另一種寫法 `date -u +%Y.%m%d.%H%M` 也放行。

⚠️ **但兩種格式不可混用**（2026-08-21 補進腳本註解）：`CFBundleVersion` 是**逐段**比較的，
不是當成一個大整數比。`2026.0821.1930` 的首段是 `2026`，而 `202608211930` 只有一段。
`2026 < 202608211930` → 從 12 位數格式**換成**三段格式會被判定為**倒退**而拒收，且無法回頭
（同一個 `CFBundleShortVersionString` 下沒辦法往回填）。換格式前必須先確認**這個版本號底下
尚未用另一種格式上傳過任何一版**；已經傳過的話唯一出路是把 `pubspec.yaml` 的 `version` 往上帶，
＝換一個 `CFBundleShortVersionString`、重新開一條 build number 序列。

⚠️ **測試裝置要 iOS 16+**（deployment target 是 15.0，但 TestFlight App 本身要 16+）——
細節與另一個到期門檻見 [`deployment_guide.md`](deployment_guide.md) 二、〈到期與相容性門檻〉。

❌ **對抗式查證推翻過、不要再犯的三件事**：① 改 `ios/Runner/Runner.entitlements` 的
`aps-environment` 成 production（值由簽章時的 provisioning profile 決定，Apple TN2265，**改了沒有用**；
真因是 Apple Developer 後台 App ID 沒勾 Push Notifications capability → ITMS-90078）
② 動 `project.pbxproj` 的 `CODE_SIGN_IDENTITY[sdk=iphoneos*]`（與 Flutter 官方 template 一字不差，
automatic signing 會覆寫它）③ 把 iOS build 加進 `.github/workflows/ci.yml`
（`ci.yml:124-127` 明文註解「iOS/Android builds and integration_test stay local」，是專案既有決定）。
①② 已寫進 CLAUDE.md 鐵律，驗法（`codesign -d --entitlements :-`）見
[`deployment_guide.md`](deployment_guide.md) 二、。

#### ⚠️ 送測前未解的資料風險（2026-08-21 逐行核實；唯一持有 file:line 的地方）

這是醫療系統，**內測包打的是生產後端**，本專案沒有 staging（`deployment_guide.md` 只有 production 一組）。

> ❌ **先更正一條被證實錯誤的引用（本輪之前四份文件與打包腳本 banner 都照抄它）**：
> 舊敘述寫「`backend/app/utils/i18n_messages.py:587` 的 `notifications.session_complete.body`
> 會把病患姓名推到測試者的鎖定畫面」——**錯的**。`notification_service.notify_session_complete`
> 的 docstring 明文寫「**這一條刻意不 fan-out**」，且呼叫端（`conversation_handler`）本來就只在
> **有 `doctor_id` 時**才呼叫；碼內自陳「實測 DB 內 `sessions.doctor_id` 全為 NULL」
> → **session_complete 目前根本不會發出去**。照舊敘述去「補去識別化 587」只會改到一條不會觸發的
> 文案，**真正的外洩通道原封不動**。下面第 1–3 條才是會打到手機的。

1. **真實病患姓名會出現在測試者的鎖定畫面上——通道是 report_ready，不是 session_complete。**
   `backend/app/utils/i18n_messages.py:601` 的 `notifications.report_ready.body`
   （zh-TW＝「病患 {patient_name} 的 SOAP 報告已生成，請審閱。」）原封不動送進 FCM。
2. **而且這一條是 fan-out 給全體在職醫師。** `backend/app/services/notification_service.py:205`
   （`notify_report_ready` 的 fan-out 迴圈）在 `sessions.doctor_id IS NULL` 時對**每一位在職醫師**
   各建一則通知＋一次推播（docstring 自陳「實測 DB 內 `sessions.doctor_id` 全為 NULL」）
   → 測試者一登入註冊 FCM token，就成為**全院每一位病患**報告的收件人。
3. **第二條會打到手機的文案**：`backend/app/services/notification_service.py:729` 的
   `_REPORT_FAILED_COPY`（report_failed，body 帶 `{patient_name}`，**同樣走 fan-out**）。
4. **休眠地雷（目前不觸發，但「開始指派醫師」那天會自動解封）**：
   `backend/app/services/alert_service.py:403` 的紅旗推播，body ＝ `data["description"]`
   ＝ **LLM 生成的醫師向臨床描述**（比姓名更敏感）。它走 `session.doctor_id`，因為目前全 NULL
   所以不觸發——**一旦開始指派醫師，這條會直接把臨床描述送上鎖定畫面，沒有人需要改任何一行碼**。
5. **iOS 端可達破壞性 API**：`flutter_app/lib/data/api/patients_api.dart:35` 刪病患、
   `admin_api.dart:40/51` 停用帳號與重設密碼（`route_guard` 只擋 `/patient` 問診子樹，
   `/patients` 是刻意開著的醫師端清單）。
6. **另一條休眠地雷**：`flutter_app/lib/features/doctor/services/push_service.dart:161` 的
   `unregister()` 失敗只 `debugPrint`、**不重試**——登出後那台手機的 token 可能還留在
   `fcm_devices` 裡，繼續收全院推播。

**拍板（2026-08-21）：第一版 TestFlight 只裝使用者自己一台**，用途純粹是驗證發佈管道。

✅ **`testFlightInternalTestingOnly` 已證實生效（2026-08-21 實查，這條推翻了先前的立場）**：
上傳後的那顆 build 在 App Store Connect 的 TestFlight 建置版本清單上標著「**內部**」。
也就是說即使走 `destination=export` ＋ `xcrun altool`（不是 xcodebuild 直傳、也不是 Organizer），
這個旗標**仍然會被帶到 ASC**。先前寫的「未經驗證／不可當技術護欄／`destination=export` 下是否
生效未經證實／要上傳後才知道」**全部過期**，不必再用懷疑的語氣講它——當然更**不要拿掉那個 key**。

⚠️ 但有兩件事**沒有**被推翻，而且是這一整段的重點：

- **(a) 它擋的是「散佈」，不是「資料」。** 它讓這顆包不能拿去做 external TestFlight／上架，
  但**對任何一個被加進 internal 群組的人完全沒有作用**——那個人拿到的是真實醫師帳號，
  登進去就讀得到全部真實病患姓名與完整 SOAP 報告（上面第 1–6 條）。
  ⇒ **它不是 PHI 護欄。** 擋 PHI 的仍然只有「第一版只裝自己一台」這個人為拍板，
  **下面〈加第 2 個測試人員之前的前置條件〉一個字都沒有因此放寬**。
  🛑 **「旗標有效」≠「PHI 有護欄」**，把這兩件事混在一起就是這一段最容易犯的錯。
- **(b) 走 Xcode Organizer 上傳仍然會自己重新 export**，整份 `ExportOptions.plist` 連同這個 key
  一起被繞過，而且沒有任何機制會發現。腳本收尾段已把 Organizer 標成不建議路徑
  （建議走 altool 或 Transporter——它們傳的就是第 6 關驗過的那一顆位元組）。

ⓘ 附帶一條本機事實，免得日後有人以為壞了：**第 6 關驗不到這個旗標是正常的**——
它是給 xcodebuild 的匯出指示，不會在 `.ipa` 的 bundle 或 entitlements 裡留下痕跡
（`Packaging.log` 也掃不到）。「產物驗證全綠」與「這道旗標有生效」本來就是兩件無關的事，
它生效與否只能在 ASC 上看。

#### 加第 2 個測試人員之前的前置條件（不是選配）

> ⚠️ **已查證的關鍵事實：遮蔽推播文案不會降低 PHI 暴露。**
> 測試者拿到的是**真實醫師帳號**，登進去就能在 `/patients`、`/reports/:id`、`/sessions/:id`
> 讀到**全部真實病患姓名與完整 SOAP 報告**；**後端沒有 tenant／scope 隔離**。
> 推播文案只是鎖定畫面那一行——把它遮掉，帳號本身的存取面**一點都沒有變**。
> 任何「先把姓名遮掉再多發一個人」的計畫都建立在這個誤解上。

依第 2 人的**授權狀態**二選一，不要混：

- **A) 第 2 人已獲授權接觸真實病歷**（院內醫護）：遮蔽推播文案（report_ready 與 report_failed
  的 body 拿掉 `{patient_name}`）＋ 關掉 iOS 端破壞性入口（刪病患／停用帳號／重設密碼）
  ＋ 書面記錄授權依據。**估時約 3 小時。**
- **B) 第 2 人未獲授權**（工程師／PM）：**任何程度的文案遮蔽都不足以合法化**——他一登入就看得到全部。
  唯一的最小安全集是**開 staging 環境**：獨立 Railway service ＋ 空的 Supabase DB ＋ 3–5 筆
  明顯假名的病患資料，內測包改打 staging。**估時 4–8 小時。** 附帶好處：同時解鎖 V1／V4 的
  實體麥克風驗證（不必拿生產資料練習）與日後的 external TestFlight。

⚠️ **本輪刻意不實作**（使用者已拍板「第一版只裝自己一台」）：後端去識別化、route guard 擋 `/admin`、
`unregister()` 失敗重試。這三項在這裡是**前置條件的記錄**，不是本輪待辦——動手前先確認要走 A 還是 B。

#### 兩條沒人提過、但第一次上傳就定生死的風險

- **App 仍然沒有崩潰回報，但例外至少看得見了（2026-08-22 更新）。**
  `flutter_app/lib/core/error_boundary.dart` 掛上 `FlutterError.onError`、
  `PlatformDispatcher.onError` 與 `ErrorWidget.builder`：Dart 例外現在會顯示成一行可讀訊息，
  堆疊寫進 stderr（裝置接著 Mac 時 `flutter logs`／Console.app 看得到）。
  **`pubspec.yaml` 仍然沒有 Sentry／Crashlytics**——錯誤不會自己送到任何地方，
  還是要測試者手動截圖回報（ExportOptions 的 `uploadSymbols=true` 只救得了原生 crash，救不了 Dart）。
  ⚠️ 這條原本寫「任何 Dart 例外＝白畫面、哪裡都查不到」，那個前提在 2026-08-22 之後不再成立；
  但「裝上去打不開時先假設是 Dart 例外而不是後端掛了」這個判斷順序仍然對。
- **第一次上傳的錯誤是永久的。** `CFBundleIdentifier` 與 App Store Connect 的 SKU **建立後不可更改**；
  已上傳的 build **不能刪、只能等它過期**；TestFlight build **90 天到期且不能延長**。
  ⇒ 90 天那件事**上傳當天就排進行事曆提醒**——寫進文件不會提醒任何人。
  ⚠️ **2026-08-21 已經上傳，所以這幾件事現在都是既成事實**：bundle id 與 SKU 定了（值見總表 §3）、
  第一顆 build 的 90 天倒數已經在跑（到期日見總表 §7）。**行事曆那件事現在就該做，不是日後。**

### [ ] E10. 🟢 紅旗譯名待母語臨床者最終覆核（AI 稽核標 medium/uncertain 的 8 筆）

> **後端專屬，與 Flutter 遷移無關。擋在「母語 + 泌尿科背景」覆核者身上，工程與 AI 不該拍板**——
> 這些詞影響規則層召回率與 critical abort（誤判會誤中止問診或漏掉真紅旗）。
> 底下兩條工程項已拆出獨立追蹤（見本節末），E10 本體純粹等人。

- ko `산통과 발열`→建議 `신산통과 발열`（산통日常語感=分娩陣痛，混淆風險）
- en urosepsis trigger `fever with dysuria`→`fever with painful urination`（病患不講術語）
- en cauda_equina 建議增補口語 `numbness down there / in my private area`（saddle anesthesia 是教科書詞）
- ko gross_hematuria_heavy trigger `혈전`→`핏덩어리`（血塊口語）
- vi display_title `Tiểu máu đại thể lượng nhiều`→`Tiểu máu đại thể nặng`（語序）
- ja display_title `高度肉眼的血尿`（可考慮加「の」）、ko `회음부 감각 이상`（可更口語）、
  vi trigger `giảm cân`（偏健身脈絡，可換 `sụt cân nhanh`）——風格邊界，母語者定奪
- **E9 驗收觀察（追蹤）**：規則層子字串比對無否定語意——病患否定句「沒有注意到…體重減輕」
  被命中 `unexplained_weight_loss` high（已正確去重 1 筆、title 在地化；語意層不會這樣誤判）。
  fail-open 取捨下先接受，生產觀察誤報率；若 critical 級出現否定誤報（誤 abort）則需處理——
  選項：規則層否定詞窗口防護／critical 降為僅語意層可 abort／`RED_FLAG_BUILTIN_RULES_FALLBACK=false` 退關
- DB `red_flag_rules.keywords` 仍是扁平 ARRAY 無 `keywords_by_lang`——若日後要讓管理者精細管理
  DB 規則多語關鍵字需加欄位（目前靠塞同一陣列）

### [x] F6. 🟡 既有 e2e 紅燈：`i18n_en_no_cjk.spec.ts` 4 案例在乾淨 HEAD 也失敗 — 2026-07-04 修復（mock 資料依 resolvedLanguage 在地化，12/12 綠）

- playwright webServer 強制 mock 模式，mock 假資料（陳小明、中文主訴清單、中文 SOAP）洩漏 CJK
  到 en-US 頁面（select-complaint / medical-info / session-complete / thank-you）
- 非 F 輪造成（HEAD 對照確認）。修法方向：mock 資料補英文 variant 依語言 pick，或 spec 對
  「資料層 CJK」設 allowlist

### [x] F7. 🟢 F 輪 review 判 low 的遺留 — 2026-07-04 七條全修（本輪；審查加修 3 條：red_flag_reason 語言一致、dashboard WS 防迴圈 guard 改「首則應用層訊息」歸零、AI 硬鎖 re-assert 競態窗口）

- AI 回合硬鎖無 re-assert（語言切換 closeMic/openMic 重跑可遺失硬鎖）
- logout 的 401-retry 會重放舊 refresh token → rotation 後的新 token 未被黑名單（7 天自然過期）
- refresh rate-limit 移到 CSRF 驗證之前（無憑證請求也扣 REFRESH_IP_LIMIT 額度）
- 其他主訴 seed migration 重跑在 sentinel 已被 sessions 引用時撞 FK（docstring 與行為矛盾）
- dashboard WS 無 token 續期路徑（過期後重連永遠同一顆舊 token）
- 快速斷線重連時本地 TTS 佇列殘播可打穿 AI 出聲硬鎖（既有行為，本輪矩陣將其正式化）
- 重播若打斷 AI 出聲回合，鏈尾清硬鎖後重播期間 VAD 開啟（與 Fix 18 重播 barge-in 設計一致，邊界待定調）

### [ ] F8. 待臨床拍板：其餘 6 筆 `is_default=False` 預設主訴（尿失禁/下腹痛/陰囊腫脹/ED/PSA/尿檢異常）是否對病患開放

- 病患現僅見 5 個選項（血尿/頻尿/排尿疼痛/腰痛/其他），痛點「找不到符合症狀」部分仍在，
  開放與否屬臨床分流決策
- **後端 `is_default` 決策，前端框架無關**（React 與 Flutter 都是讀 API，零改動）。實作成本＝一句 UPDATE
- 拍板前先確認的具體前置：(1) ED/PSA 的 ICD-10 對照與紅旗清單是否已備（E6 已補 N52/R97）；
  (2) 開放後變 11 個選項，kiosk 單頁是否需要分類分組

### [x] E11. 紅旗規則層否定語意 — 2026-07-27 修復（PR #46）

⚠️ **原始描述有誤**：規則層**早就有**否定守衛（`_NEGATION_CUES` 等），不是「純子字串比對」。
真正的問題比原描述嚴重——那個守衛有兩類**漏報**（under-triage）洞：

1. **假朋友**：字面含否定詞、語意其實肯定的詞被當成否定線索。實測 main：
   - 「我睪丸非常痛，尿不出來」→ **零紅旗**（「非常」的「非」吃掉整句）
   - 「我沒有什麼特別的問題，就是尿不出來」→ **零紅旗**
   - 「我無法排尿也睪丸劇痛」→ 只剩 `urinary_retention`，`testicular_pain_severe` 被吃掉
   修法：`_CUE_FALSE_FRIENDS`（無力／無法／非常…）＋ `就是／只是` 重置詞
2. **ja/ko/vi/en 缺轉折詞**（對抗式驗證找到，原 agent 未揭露）：`_CONTRAST_MARKERS`
   只有中文＋`" but "`，導致「否認 A ＋ 轉折 ＋ 真的有 critical B」在那四種語言**全數漏報**：
   「熱はないですが尿閉になりました」「열은 아니고 극심한 고환 통증이 있어요」
   「denies fever, however he has testicular pain」皆 MISS。中文對照組一直正常，故肉眼難察。
   修法：補 ja（ですが/けど/しかし/でも/ではなく…）、ko（지만/하지만/아니고/아니라…）、
   vi（nhưng/mà）、en（however/though/although）。**不收裸「고」**（泛用連接詞，收了等於關守衛）

**方向性（安全關鍵）**：轉折詞與假朋友都只會讓守衛**少抑制** → 紅旗**更容易**命中。
過寬＝over-triage（護理師多走一趟，可逆）；過窄＝under-triage（不可逆）。取寬。

**驗證**：17 組跨語言探針全過（7 個 critical 漏報修復 + 7 個抑制仍成立）；
mutation test（拿掉轉折詞 → 7 failed）；backend unit 1041 passed；
**真 OpenAI e2e `torsion_critical_zh` + `dontknow_zh` 皆通過**（紅旗鐵律的合併前置條件）。

**仍待臨床拍板（未修）**：「不會痛，尿不出來」仍被抑制。兩種修法（時間副詞重置／
list 分隔符切斷）實測都會製造新的 critical 誤報（「沒有高燒、寒顫」變命中 → 誤 abort），
方向需要臨床決定。`RED_FLAG_NEGATION_GUARD` kill-switch 已備（預設開）。

⚠️ **2026-08-20 更新（`6fc51e3` RF-2／RF-3）**：本條當時擋下「list 分隔符切斷」的兩個理由
依碼面判讀都已不適用——(a) RF-2 採用的切斷**加了語意條件**：只有分隔符之後那段已含
**時間錨點**（`_CURRENT_EPISODE_TIME_ANCHORS`）才切，而「沒有高燒、寒顫」分隔符後沒有時間錨點，
不觸發（`backend/app/pipelines/red_flag_detector.py:891-957` 的 `_clause_before`，(b) 的 `break`
在 `:936-937`）；(b) RF-3 已把 `高燒／高熱／고열` 從 urosepsis 的裸 trigger 降進共現組
（`backend/app/pipelines/prompts/shared.py` 的 `urinary_x_systemic_infection` 共現組
`acuity_terms`——**不是** urosepsis 定義開頭那段舉證註解），那個字面本身不再單軸判 critical。

✅ **「不會痛，尿不出來」已實跑複驗（2026-08-21）：仍回 `[]`，仍被抑制。**
所以 E11 未結案的前提成立（先前記的「未實跑複驗」可以劃掉）。
同批實測佐證：`_has_time_anchor("寒顫")` = False；`_rule_based_detect("沒有高燒、寒顫")`
與 `"我沒有高燒、寒顫"` 皆 `[]`；`我上個月因為流感發高燒` → `[]`、
`我發高燒而且小便會痛` → urosepsis critical。E11 這條臨床拍板仍未結案。

### [ ] E12. `red_flag_rules.keywords` 缺 `keywords_by_lang` 欄位（從 E10 拆出的工程項）

- DB 欄位仍是扁平 ARRAY，多語靠塞同一陣列。若日後要讓管理者從 admin 精細管理各語言關鍵字才需加欄位

---

## G — flutter_app 基線入庫審查（2026-07-26，17-agent 六視角 + 對抗式驗證）

> 來源：`flutter_app/` 10,686 行入庫前審查（58 筆存活發現，1 筆被反駁剔除）。
> 入庫判定 GO 且已入庫（`feat/flutter-app-baseline`）：analyze 0 issue、test 17/17、零 secret、
> `build/` 與 `.dart_tool/` 已正確排除。以下是入庫後要修的。
> **動任何 voice/ 下的檔案前先讀 `voice-pipeline-invariants` skill**——G1/G3/G4/G14/G15 都是它列管的行為。
> 2026-07-26：2 blocker（G1/G2）+ **11 條 high 全部**（G3–G13）+ **21 條 medium**（G14–G34）
> + **10 條 medium**（G25–G34）已修並附回歸測試；**剩 2 medium**（G35，皆有外部依賴）。

### [x] G1. 🔴 紅旗中止導向錯頁（病患拿不到「告知現場醫護」）— 2026-07-26 修復

- 根因：`conversation_page.dart` 的 `ref.listen` 只 select `completed`，callback 內卻讀 build 期
  快照的 `s.abortedRedFlag`。`_onSessionStatus`（controller:307）在**同一個 copyWith** 設兩個欄位，
  所以 listener 讀到的仍是 `false` → 病患拿到一般感謝頁 + 8 秒自動導回首頁
  （`session_thank_you_page.dart:28-29` 只在非紅旗時起那個 Timer），永遠看不到「告知現場醫護」。
  違反不變式 #11，且與 G14（無語音播報）疊加＝三層告知同時失效
- 修法：改成 select `(v.completed, v.abortedRedFlag)` **records tuple**，兩個值來自同一次 emission
  → 讀到過期快照在結構上不可能發生（比補 `ref.read` 更穩，不依賴後人記得這件事）

### [x] G2. 🔴 跨病患 session 污染（同一 kiosk 第二位病患沿用前一位場次）— 2026-07-26 修復

- 根因：provider 非 autoDispose → notifier 活得比頁面久，`ref.onDispose(_teardown)` 永不觸發
  （離頁後麥克風仍開、WS 仍連），且 `_started` 閂鎖讓下一位病患的 `start()` 直接 return
  → 第二位病患繼承前一位的 session／逐字稿／紅旗／靜音狀態
- 修法：`NotifierProvider.autoDispose`。`_started` **保留**但語意改為「單一 instance 的
  re-entrancy guard」（autoDispose 後每位病患都是新 instance，`_started` 自然是 false）；
  並把 `_started = true` 移到三個服務建構之後——否則 dispose 撞上剛進 `start()` 的競態會踩到
  `late final` 未初始化而拋 LateInitializationError，而不是乾淨 no-op
- 順帶：`_sessions` 改 `late final`（原本 eager 建構會拿 `ApiClient.dio`，需要平台通道，
  導致 controller 在 unit test 裡根本無法建構）

**驗證**：`flutter analyze` 0 issue、`flutter test` **19/19**（新增 2 項回歸）。
autoDispose 那項刻意驗過會紅——把 `.autoDispose` 拿掉即 `-1`，還原即全綠，
確認不是永遠通過的空測試。

### [x] G3–G10 的 8 條 high — 2026-07-26 修復（PR #38）

| # | 修法 | 驗證 |
|---|---|---|
| G5 | web 補 path URL strategy（conditional import，native 為 no-op stub）——原本路由躲在 `#` fragment 後，`/vi-VN/patient` 的語言段在 router 解析範圍外，URL 不再是語言權威 | **web + iOS build 皆過** |
| G6 | redirect 改用 `state.uri.replace(path:...)`——原本只回 path，重設密碼信的 `?token=` 被吃掉，整條流程死在「連結無效」 | **4 項新回歸測試** |
| G8 | logout 帶 `ApiClient.skipAuthRefresh`——原本 401 會觸發 refresh 輪換 token，再用**已捕獲的舊 token** 重試，後端黑名單舊 jti 而新 token 活 7 天（登出的反面） | analyze/test |
| G9 | refresh 用的裸 Dio 補 `receiveTimeout`/`sendTimeout`——一次 hang 就讓共享的 `_refreshInFlight` 永不 settle，所有併發 401 一起卡死＝全 app 靜默鎖死 | analyze/test |
| G10 | 逐字稿 `reverse: true` + 反向索引——原本第 4 輪後 AI 當前問題落在畫面外，病患看著過期畫面 | analyze/test |

驗證：`flutter analyze` 0 issue、`flutter test` **23/23**（+4）、**web `--release` build 過**、
**iOS simulator build 過**、**simulator integration test 對生產後端仍 1/1 pass**（G6/G8/G9 都在登入路徑上）。

### [x] G12. 醫師端全域紅旗提示 — 2026-07-26 修復（PR #39）

- 新 `features/doctor/doctor_alert_watcher.dart` 掛在 `MaterialApp.router` 的 `builder`
  （navigator 之上、MaterialApp 之下 → ScaffoldMessenger 在 scope 內、跨路由存活）
- **比原本診斷更嚴重的一點**：`alertsProvider` 只有被讀到才會建立。醫師登入後直接去
  `/reports`（沒進過任何 shell tab）→ controller 從未建立 → `ensureConnected()` 從未跑
  → **dashboard WebSocket 根本沒連上**，不只是沒有徽章而已。watcher 用 `watch` 而非
  `read`，讓 controller 在整個已認證 session 內存活（provider 刻意非 autoDispose）
- 只對 doctor/admin 訂閱（病患角色後端會回 4003，`ws_manager` 視為永久關閉不重連）
- 只在 unacknowledged **上升**時 toast（acknowledge 使計數下降必須安靜）；8 秒、error 色、
  附「查看」導向 `/alerts`；5 語系文案
- **刻意未做**：把 `/patients`、`/reports`、`/research`、`/admin/*` 重新包進 `DoctorShell`。
  `NavigationBar.selectedIndex` 必須是有效索引，那些頁沒有對應 tab；且它們都有 AppBar
  返回。安全缺口（零信號）已由 watcher 補掉，底部導覽的可達性屬 UX 偏好，留給日後決定

### [x] G13. 病患 intake 家族病史 — 2026-07-26 修復（PR #39）

- `medical_info_page.dart` 的 `'familyHistory': []` 硬寫空陣列 → **攝護腺癌家族史永遠空白**，
  醫師無法分辨「沒問」與「病患否認」
- 加 `_Family` model + `_familySection`（relation 下拉 8 種親屬 + 疾病自由文字 + 刪除/新增），
  送出時過濾空白列，形狀對齊後端 `SessionIntakeFamilyHistoryItem{relation, condition}`
- **i18n 零新增**：`medicalInfo.family.*` 與 8 個 `medicalInfo.relations.*` 早就在 5 語系
  翻譯檔裡（React 版已用），只是 Flutter 沒接
- 空白列必須過濾：後端 `condition` 是 `min_length=1`，送空字串會 422 掉整個建場次請求

⚠️ **2026-08-20 補記（`931b9b7` D-3／D-10 ＋ `2daa82c`）**：本條當時只把硬寫 `[]` 修成送真值，
**第三態仍缺**——後端 `app/pipelines/patient_context.py:115-119` 的 `no_family_history` 分支
因為**兩份前端都送不出這個旗標**而是死碼，所以「病患表明沒有家族史」與「還沒填」在後端仍然
同形。Flutter（D-10）與 React 各自補上「無家族病史」勾選框後才活化
（`flutter_app/lib/features/patient/medical_info_page.dart`、
`frontend/src/screens/patient/MedicalInfoPage.tsx:172`／`:291`／`:719`）。
同批 D-3 把 relation 改送在地化字串（zh 場次不再出現 `father：膀胱癌`，
`intake_payload.dart:113` 的 `'relation': tr('intake.medicalInfo.relations.${f.relationKey}')`，
所屬 familyHistory block 是 `:108-116`；`:96-101` 是 **medicalHistory** 的 entry，不是這裡；
React 本來就送 `t()`，見 `MedicalInfoPage.tsx:297`）。
投影邏輯抽成純函式 `flutter_app/lib/features/patient/intake_payload.dart`，
形狀由 `flutter_app/test/intake_payload_test.dart` 直接斷言——e2e 送裸 JSON 看不到前端偽造，
那是唯一的防線。**新增 intake 三態欄位時，後端 schema、`patient_context` 分支、兩份前端 UI
要一起做**，否則後端看起來有支援、實際永遠收不到。

### [x] G11. kiosk 閒置自動登出 — 2026-07-26 修復（PR #40）

- 新 `features/patient/kiosk_idle_guard.dart`，逐條照抄 React `KioskIdleGuard.tsx` 的三個守衛：
  限 `patient` 角色（醫師審報告不可被登出）、排除 `/conversation`（語音時病患可能長時間不觸控，
  問診閒置由後端 `SESSION_IDLE_TIMEOUT` 管）、`Env.kioskIdleTimeoutSeconds == 0` 可停用
- **預設 180 秒**——React 版註解裡就寫了這個建議值（「kiosk 於 Vercel env 設如 180000（3 分）」），
  取 parity 而非另挑。可用 `--dart-define=KIOSK_IDLE_TIMEOUT_SECONDS=<n>` 覆寫
- ⚠️ **踩到一個只有真跑才會發現的坑**：第一版在 `MaterialApp.router` 的 `builder` 裡呼叫
  `GoRouterState.of(context)` → 那層在 Navigator 之上，`GoError: There is no GoRouterState
  above the current context`，**整個 app 變一片紅**。而 `flutter analyze` 乾淨、32 個單元測試全過。
  改成在 timer 觸發的那一刻用 `GoRouter.state`（不需 context）讀路徑；不適用時 re-arm 而非登出
- ⚠️ 已知限制：timer 靠 pointer/key 事件重置，但 iOS/Android 的軟鍵盤由 OS 畫在 Flutter view
  之上，敲鍵不一定會傳到我們的 widget tree。180 秒讓這件事極不可能發生；若現場真的踩到，
  修法是從 intake 欄位的 onChanged 也重置，**不要**拉長視窗

**驗證**：`shouldArmKioskIdleTimer` 抽成純函式 + 5 項測試（含「路徑只是含 `conversation` 字樣
不得豁免」防止寫成鬆散的 `contains('conversation')`）；`integration_test/kiosk_idle_logout_test.dart`
在 simulator 上真等 12 秒驗證**病患確實被登出且 token 從 Keychain 清除**（需 `runAsync` 才能讓
真實 Timer 觸發）；simulator 實跑 timeout=10s 等 30s 確認**醫師不被登出**。

### [x] G14–G18. 語音管線 5 條 medium — 2026-07-26 修復（PR #41）

| # | 問題 | 修法 |
|---|---|---|
| G14 | `pause()` 先送 `pause_recording` 才 `_muteVad()`。但 hard-mute 開啟中的段落會 `_endSegment(notify:true)` → `onSpeechEnd` → 送 final chunk，**後端已暫停故丟棄** → 病患講到一半的症狀消失，且 `sttProcessing` 永遠等不到結果、狀態列整場卡在「正在辨識」 | 兩行對調：先 flush 再送 pause，最後才設 `userPaused` |
| G15 | `onSpeechStart` 無硬鎖 re-assert → AI 出聲期間若段落仍開出來，沒有人補鎖 | 開頭判 `userPaused \|\| _pendingAiUnmute \|\| _pendingReplayUnmute` → `_muteVad(); return;`。**排除 soft-mute**，不誤殺未來的 barge-in（`AudioStreamService` 新增 `muteMode` getter 供判斷） |
| G16 | 狀態列無 `userPaused` 分支 → 暫停中仍顯示「請直接開始說話」，叫病患做唯一做不到的事 | `userPaused` 放最優先（使用者主動的狀態最該告知） |
| G17 | 「我說完了」是空殼：`forceEndSegment()` **零呼叫**、翻譯 `voiceControl.finishSpeaking` 早已入庫 → 每輪都白等 2 秒靜音窗 | 加第四顆按鈕 + `finishSpeaking()`；非錄音中則 disabled 而非靜默無作用 |
| G18 | `sendText` 離線時 `_ws.send` 靜默丟棄 → 假氣泡，且**該段文字不經紅旗篩檢** | 送出前檢查連線，顯示 `input.sendOffline`（key 早已入庫） |

### [~] 測試深度 — 2026-07-26 部分完成（PR #41）

- **已補**：`ws_manager` 的 backoff 與永久關閉碼抽成純函式 `wsRetryDelayMs` /
  `isPermanentCloseCode` + **9 項測試**（1s→2s→4s→8s→16s→clamp 30s、首次不可為 0
  否則瘋狂重連、`1 << 63` 溢位負值守衛、4003 forbidden_role 永久不重連、null code 要重連）
- **仍缺**：`tts_playback_controller` 的 epoch 取消與 chain 前進。`TtsPlaybackController`
  自己 `new AudioPlayer()`，unit test 無平台通道無法建構 → 要測必須先讓 player 可注入。
  這是 voice-pipeline-invariants #5 唯一沒有回歸防護的地方
- **仍缺**：`conversation_controller` 的 WS 事件→state 轉換（同樣需要注入 `_audio`/`_ws`/`_tts`）

### [x] G19–G24. auth／router／i18n 6 條 medium — 2026-07-26 修復（PR #42）

| # | 問題 | 修法 |
|---|---|---|
| G19 | `bootstrap()` 的 `TokenStore.load()` 在 try **外**。web 上 flutter_secure_storage 在非 secure context（純 http，例如院內 LAN）拋 `UnsupportedError`，而 `main()` 在 `runApp` **之前** await bootstrap → **整頁白屏、完全進不去**，而不只是「未登入」 | `load()` 搬進 try；catch 內的 `clear()` 也包一層（儲存不可用時它同樣會拋） |
| G20 | web 上 flutter_secure_storage 是「AES 加密後放 localStorage，金鑰也放同一個 localStorage」→ XSS 可解出 7 天 refresh token 且跨瀏覽器 session 留存 | `WebOptions(useSessionStorage: true)`：限定該 tab。也更符合 kiosk 語意——病患走了 session 就該結束。iOS/Android 不受影響 |
| G21 | GoRouter 無 `onException` → 無效路徑落到 go_router 內建的**未在地化英文錯誤頁**，kiosk 上不可接受（＝P3 #23 剩下的那條） | `onException` 導回帶語言前綴的 root，讓既有 guard 依角色分流。**零新增文案** |
| G22 | `complaint_management_page.dart:349` 的 `'顯示順序'` 是全碼庫唯一硬編碼中文，en/ja/ko/vi 的管理者會看到中文（＝P3 #27 剩下的那條） | 補 `admin.complaints.fieldDisplayOrder` 到 5 語系 |
| G23 | 切語言只搬 path，query／fragment 全丟（`language_bar.dart` 與 `patient_settings_page.dart` 兩處）；且病患設定頁只有 zh/en 兩個 chip，ja/ko/vi 的病患選不到自己的語言 | 兩處都改用 `uri.replace(path:)`；chip 改吃 `supportedLanguages` + beta 標記 |
| G24 | 醫師 `/settings` 直接掛 `PatientSettingsPage` → 醫師看到病患的個人資料/通知/安全分頁，而 `common.doctor.settings.*` 承諾的主題模式與音效提醒**一個都沒有** | 新 `DoctorSettingsPage`（帳號資訊／主題模式 SegmentedButton／語言／音效提醒／API 端點）。**27 個 key 早已在 5 語系檔裡**，只是頁面沒做。`themeMode` 與 `soundAlerts` 進 `settingsProvider`，`app.dart` 改讀它（原本硬寫 `ThemeMode.system`） |

### [x] G25–G28. 病患 intake ＋ 醫師死局 4 條 medium — 2026-07-26 修復（PR #43）

| # | 問題 | 修法 |
|---|---|---|
| G25 | 主訴選「其他」但沒填自述時，只是把 CTA 變灰——**畫面上零解釋**，kiosk 現場病患直接卡住 | 輸入框加 `errorText`（`selectComplaint.otherRequired` 早已入庫） |
| G26 | 病史 `stillHas` 硬寫 `true` 且無 UI → **每個已痊癒的病症都以「仍持續」送給醫師**。靜默錯誤的臨床資料比缺欄位更糟 | 每列加 Checkbox（`history.stillHas` 早已入庫） |
| G27 | web 的 SOAP PDF 匯出走 share_plus → `navigator.share(files)`，**桌面瀏覽器多不支援**、直接拋，呼叫端 catch 掉 → 醫師按了什麼都沒發生 | web 改走 blob URL + anchor download（conditional import，native 仍走 share sheet）。新增 `package:web` 依賴 |
| G28 | `canGenerate = completed && !_hasReport`——只看報告**存在與否**，所以 `failed` 的報告也讓按鈕消失＝**死局**，那場問診永遠拿不到報告 | 改存報告 `status`；抽出純函式 `canGenerateSoapReport`：`failed` 可重跑、`generating` 不給按鈕（避免重複派工）但顯示進行中提示、`generated` 才給「查看報告」 |

### [x] G29–G34. /research 投稿要件 ＋ SOAP 逐字稿 ＋ 切語言入口 — 2026-07-26 修復（PR #44）

- **G29 每張圖的 caption + footnote**：`_figure()` 加 `caption`/`footnote`。footnote 帶的是**分母**，
  正是 SAMPL 要求、也是讀者判斷比例所必需的。`<section>.subtitle`／`.footnote` 早已在 5 語系檔裡未用
- **G30 各語言子群 DataTable**（`table.*`，早已入庫未用）：森林圖背後的完整數字，審稿者要核對用。
  寬表用水平捲動而非壓縮欄寬
- **G31 Methods 對照卡**（`methods.*`，早已入庫未用）：DECIDE-AI／AMIE／triage 文獻／PDQI-9／
  統計規範＋免責聲明，投稿寫 Methods 時直接對照
- **G32 圖片匯出**：`RepaintBoundary` → PNG(3x) → `sharePngBytes`（web 走 anchor download）。
  **刻意不是 SVG**：web 版序列化 inline SVG，Flutter 這邊沒有對等物，要真向量得把每張圖重畫進
  SVG writer。PNG 3x 對審閱足夠。只截圖表本身、不含工具列
- **G33 SOAP 逐字稿分頁**（`soap.tabs.*`，早已入庫未用）：醫師可邊看報告邊比對病患原話再核准。
  逐字稿載入失敗**不致命**——報告才是這頁的重點，不可因此整頁空白
- **G34 切語言入口**：新 `LanguageAction`（AppBar 用的精簡 popup），加到 select-complaint／
  medical-info／history／forgot-password／reset-password。~~**⚠️ 刻意不加到 `/conversation`**：
  問診中切語言需要下面那條還沒做的後端守衛，加了會留下 in_progress 孤兒場次~~
  → **2026-08-18 拍板已掛**（`3877729`），見下方 G35b

⚠️ 實作時踩到與 G11 同一類的坑：`LanguageAction` 原本在 build 期呼叫 `GoRouterState.of(context)`，
導致沒有 router 祖先的 widget test 直接拋。改成**在 tap 那一刻才讀** router state——
「router state 只在需要它的地方讀」這條教訓這輪出現第三次了。

### [x] G35b. 切語言的進行中場次守衛 — 2026-07-27 完成（PR #46）

⚠️ **原始描述有誤**：後端端點 `POST /sessions/{id}/end-for-language-switch` **早就存在**
（`sessions.py:150` / `session_service.py:460`，React 也早就在用），缺的只有 Flutter 接線。
這個錯誤主張先前被我傳播到 PR #44 說明與 `LanguageAction` 的註解裡。

- 後端順帶修一個**不變式 #16 違規**：原本自帶 `(WAITING, IN_PROGRESS)` 狀態白名單，
  改為問 `is_valid_transition`（單一權威）。並改為**冪等**：已終態回 200 而非 409
  ——切語言守衛可能被重試或連點，回 409 會讓「語言切不掉」，而此時「沒有孤兒場次」
  的目的已達成。錯誤路徑的 HTTP 碼不變（`INVALID_STATUS_TRANSITION` 同為 409）
- Flutter：`sessions_api` 加方法、切語言守衛與 5 語系確認文案。
  ~~**入口仍未掛進 ConversationPage**（是否在問診中提供切語言是產品決定）~~

**2026-08-18 拍板：入口已掛上兩端問診頁**（`3877729`）。React 是 `ConversationPage.tsx`
頁首工具列的 `<LanguageSwitcher />`（compact；ConversationPage 是全螢幕路由、不在
PatientLayout 底下，Header 的那顆到不了），Flutter 是 `ConversationPage` AppBar 的
`LanguageAction`。拍板理由：走錯語言的病患一旦進了問診頁就再也換不掉，比「多一個誤觸
入口」更重；確認框本身即誤觸防線（取消＝什麼都不做，不 pop 頁面、不碰 controller，
WS 與收音完全不受影響）。

⚠️ 一併修掉確認後的導向：兩端原本都是把 `:lng` 換掉後回同一條 `/conversation/:id`
（React `syncUrlLng`／Flutter `router.go(target)`），但那場次剛被後端轉成 cancelled——
React 不會因為只換 `:lng` 就重掛元件、`currentSession` 已被 `resetSession` 清空 → 卡在
LoadingSpinner 且 WS 還連著死場次；Flutter 的 `_lngKeyed` 則會重建頁面並對 cancelled
場次再 `start()` 一次。**現在一律導向該語言的病患首頁**，也正是確認框文案
（`switchModal.description`）承諾的下一步。React 另修一個語言競態：`changeLanguage` 是
非同步的，直接 toast 會在英文首頁跳出中文字串（Playwright 實測到），改為先 await 再提示。

驗證：Playwright 29/29 ＋ 新增 `flutter_app/integration_test/patient_language_switch_test.dart`
（對真後端驗四件既有測試碰不到的事：確認框會出現而非直接切走、取消後仍停在原頁且 WS
open 還能繼續送文字收 AI 回覆、確認後 REST 成功才導頁且落在新語言病患首頁、場次確實轉
cancelled 並落 audit）。

### [x] 測試深度（TTS） — 2026-07-27 完成（PR #46）

`TtsPlaybackController` 的 player 改為可注入（production 行為不變），補 5 條回歸測試。
**mutation 驗證**：還原 G4 修法（`stopActive` 在 await 後才捕獲 `_activeStep`）→ 測試會紅。
這是不變式 #5 先前唯一沒有防護的地方。

### [x] G36 / G37 — 2026-07-27 完成（PR #46）

- **G36**：`check_translations.py` 涵蓋 `flutter_app/assets/locales`。政策：
  **「React 有但 Flutter 沒有」＝ blocking**（真移植缺口）、**「Flutter 有但 React 沒有」＝ warning**
  （不強迫往 React 塞死 key）。**這個檢查一加上就立刻抓到兩個真缺口**，見 H4
- **G37**：`usesCleartextTraffic` 之外，release 簽章缺設定時**明確失敗**而非靜默用 debug 金鑰。
  守衛放在 **task 層而非 configuration 層**（否則會連 debug build 一起擋）——已用實際
  debug build 驗證區分成立。`key.properties`／`*.jks` 確認在 gitignore 內

### [x] H4. Flutter 缺兩個 React 已有的功能（G36 抓到）— 2026-07-27 修復（PR #46）

`check_translations.py` 的 mirror 檢查一加上就報 blocking，追下去是兩個真缺口——
**若 Flutter 就這樣上線，H1 那整條修復會原地回歸**：

1. **忘記密碼仍謊稱「已寄送重設連結」**：`delivery` flag 我先前只接在 React。已補（含 onsite 分支與圖示）
2. **管理員無法重設密碼**：後端端點與 React UI 都有，Flutter 沒有。已補（按鈕＋一次性密碼 modal）

### [ ] H3. 🟢 dashboard 其餘硬寫中文標籤

`dashboard_service.py` 的 `STATUS_LABELS`／`ALERT_SEVERITY_LABELS`／`daily_trend.label`
仍由後端回中文字串。與 H2 同類，修法同樣是「回機器可讀 key、前端依語系格式化」。

### [ ] G35a. 🟢 紅旗與中止無語音播報（**待臨床拍板**）

需要 flutter_tts 依賴，且「是否為必要告知層」是臨床決定——修完 G1 後文字告知已恢復，
語音是第三層冗餘。

### [ ] H5. 🟢 `replay()` 未 await `stopActive()`（推測性，未驗證）

`conversation_controller.dart:443-449` 的 `replay()` 沒有 await `stopActive()` 就對同一個
player `enqueue`。若 just_audio 未串行化 method call，`stop()` 可能落在 `setAudioSource()`
之後 → 該 step 的 completer 永不解決 → chain 停住 → **VAD 永久硬靜音**（不變式 #5 的另一道門）。
TTS agent 回報但**未驗證**，刻意未修。要確認需實機走一輪 replay。

紅旗與中止無語音播報（flutter_tts，**且是否為必要告知層待臨床拍板**）、切語言無進行中場次守衛
（缺後端 `POST /sessions/{id}/end-for-language-switch`）、切語言入口只在 4 頁、
病史 `stillHas` 永遠 true、主訴「其他」未填無說明文字、/research 缺語言子群表與 Methods 卡與
caption/n= 與圖匯出（i18n key 全已入庫未用）、SOAP 頁無逐字稿分頁、
生成失敗的 SOAP 無法重跑（死局）、web PDF 匯出被 catch 吞掉、。

### [x] H1. 忘記密碼在生產無可行路徑 — 2026-07-26 結案（管理員當面重設；email 不採用）

2026-07-26 修掉「謊稱已寄信」之後浮現的真問題：

- 生產 `SENDGRID_API_KEY` / `SMTP_*` 全未設 → 信永遠不會寄出（`delivery="onsite"`）
- 前端現在誠實顯示「請告知現場醫護或系統管理員」，但**管理員沒有重設他人密碼的能力**：
  `backend/app/routers/admin.py` 只有 `/users`(GET/POST)、`/users/{id}`(PATCH)、
  `/users/{id}/toggle-active`、`/system/health`；`AdminUserUpdate`（`schemas/admin.py:26`）
  只有 `role` 與 `is_active`，沒有 password
- **今天唯一能重設的方式＝從 Railway log 讀 `[email:log-only]` 那行裡的 reset URL**
  （`_LoggingEmailClient` 會印完整連結含 token，TTL 30 分鐘）
- ⚠️ 連帶的安全問題：那是**明文可用的 reset token 落在 log 裡**。現在刻意保留，
  因為它是唯一路徑；下面任一項做完就該把 body_text 從 log 拿掉（或只印 token 前 6 碼）

**[x] 管理員重設能力已完成並部署驗證（2026-07-26）**
- `POST /admin/users/{id}/reset-password` → 一次性臨時密碼（12 碼、`secrets`、保證過強度規則、
  排除 0/O/o/1/l/I 因為要口頭轉達）；同時**撤銷該使用者所有 refresh token**
- 使用者管理頁每列加「重設密碼」鈕 + 一次性密碼 modal（複製鈕、只顯示一次警告）；5 語系
- 生產實測：臨時密碼登入 200、舊密碼 401、log 零筆含明文、稽核落表（含 403 嘗試）、
  對自己 403（ja-JP 在地化正確）、不存在 404、doctor 打 403
- `_LoggingEmailClient` 在 production 不再印 body（含 reset token），非 production 保留供 QA

**[x] SendGrid：不採用（2026-07-26 使用者拍板）**
- 帳號與 email 由使用者自行設定，系統不寄任何信 → `delivery` 恆為 `"onsite"`，
  前端恆顯示「請找現場人員協助重設」，重設一律走管理員當面操作。符合院內 kiosk 情境。
- **不要再提議設 SENDGRID_API_KEY / SMTP**。程式碼路徑保留即可（`is_delivery_configured()`
  已備），日後若真有遠端問診情境才需要，設了就會自動切回 email 文案、零改碼。

### [x] H2. 儀表板年月標題 — 2026-07-27 修復（PR #46）

前端改用既有的機器可讀 `month`（`YYYY-MM`）自行依當地語系格式化，兩份前端都改。
simulator 目視確認：原本「2026 年 7 月」現在顯示 `7/2026`（跟隨 en 語系）。
⚠️ 同一份 response 的 `STATUS_LABELS`／`ALERT_SEVERITY_LABELS`／`daily_trend.label`
**仍硬寫中文**，是同類問題但不在本次範圍——見下方 H3。

### [x] ~~H2 原始描述~~

- `backend/app/services/dashboard_service.py:109`：`f"{year} 年 {month} 月"` 硬寫中文，
  由 API 回傳、前端直接顯示（`dashboard_page.dart:75,83`；React 版同理）
- 後果：en-US／ja／ko／vi 的醫師看到「Monthly consultation overview … 2026 年 7 月」中英混雜
  （2026-07-26 iOS simulator 目視發現）
- **與不變式 #12 無關**：那條是「SOAP 報告固定中文」的刻意決策；儀表板標籤不在其列
- 修法二選一：(a) 後端改回傳 `month_key`（`2026-07`）讓前端各自用 `DateFormat.yM(lng)` 格式化
  ——比較對，日期格式本來就該跟隨語系；(b) 後端依 `Accept-Language` 產生標籤（已有
  `resolve_language` 與 `i18n_messages` 機制）

---

## R — 真 OpenAI 全流程驗收與修復（2026-07-27，四輪 workflow／54 agent）

> 起點是一個很單純的要求：**不用語音、全部用文字模擬，用真 OpenAI 把整條問診流程
> 確認一遍**——選主訴與年齡有沒有進到問答判斷、紅旗偵測、SOAP 報告。
>
> 第一輪真跑就發現：流程「跑得完」不代表「是對的」。四個既有 e2e 情境**全部**被
> 對抗式覆核判 FAILED，而且不是因為跑不動——是因為**斷言驗不到它宣稱驗的東西**。
>
> 修復本身經歷三次擺盪（over-trigger → under-trigger → 收斂），每一次都是同一個
> 根因：拿字串比對做臨床語意判斷、且只往單一方向加測試。§R9 記的那六條教訓
> 比任何一條個別修復都重要，**動這條管線之前先讀它們**。

**commit**：`ae2b95e` `fb85f41` `3a9e9b4` `949afbb` `7144e85` `4a125e8` `d247388`
（分支 `fix/e2e-flow-gaps`，從 `test/patient-text-e2e` 開出，未 push）
**驗收**：backend `3754 passed` 零 xfail、flutter analyze 乾淨、flutter test 76 passed、
`check_translations.py` OK、frontend build/lint/type-check 全過；
e2e 六情境 4 場 PASS、2 場掛在下方 R18／R19。

---

### 產品缺陷（已修）

### [x] R1. 🔴 intake 資料永遠進不了 SOAP — `ae2b95e`

`sessions.intake_data` 在整個 backend **只有一個讀者**（`conversation_handler`，餵對話 LLM）。
Celery SOAP 路徑自己重組 `patient_info`，只放 name/gender/age，所以 `soap_generator`
的 past_medical_history / medications / allergies / family_history 四個分支在生產路徑是**死碼**。

真跑實證（intake 填高血壓＋第二型糖尿病、aspirin、no_known_allergies、父親膀胱癌）：
SOAP 的 `family_history` 寫「未提供」——**與 intake 直接矛盾**，而那是血尿主訴 §3b 必記的風險因子。

修法：抽 `app/pipelines/patient_context.py` 當兩條路徑的唯一來源。

### [x] R2. 🟡 `Gender.MALE` enum repr 漏進 prompt — `ae2b95e`

WS 那份把 SQLAlchemy `Gender` enum 原樣 f-string，Python 3.11+ 輸出 `Gender: Gender.MALE`；
Celery 那份有 `.value` 所以是乾淨的 `male`。同一份資料兩條路徑兩種值。
⚠️ `Gender` 是 `str, Enum`，`== 'male'` 為 True，**用相等比對抓不到這個 bug**，要比渲染後字串。

### [x] R3. 🔴 三條「終態卻沒有 SOAP」的路徑 — `fb85f41`

1. 遲到 critical 紅旗的 drain 路徑只改 `sessions.status` 與 `_terminated`，不生成 SOAP、
   不送病患端 `session_status`、不廣播 dashboard——主 abort 分支這四件事都做
2. 硬上限 inline drain 送 `session_status` 時漏了 `extra={"status": ...}`（與 PR #49 修過的同一類 bug）
3. 閒置逾時 watchdog 標 completed 卻不派 SOAP

※ 病患直接關瀏覽器 → 60 分鐘後 cancelled、同樣無 SOAP：**未完成場次要不要出報告是產品決策**，刻意不動。

⚠️ **2026-08-20 補記（`116282d` EM-2／SO-3）**：同一類缺陷在 **REST 路徑**又出現一次——
`PUT /sessions/{id}/status` 的終態轉移六件事只做了一件。已補完：
`session_service._after_status_transition`（`backend/app/services/session_service.py:124-229`）
逐格實作、**做不到的格子逐格在 docstring 寫下理由**（送病患端 WS 與設行程內 `_terminated`
是跨行程限制，不是漏做），`completed` 補建 SESSION_COMPLETE 醫師通知（`_after_status_transition` 內；理由註解 `:609-613`、
`if new_status == SessionStatus.COMPLETED and session.doctor_id is not None` 在 `:614`，
區塊結束在 `:629`——`:631` 已經是 `await db.flush()`，先前記的 `~:633` 多框了四行），`end_for_language_switch` 的 cancelled 補 dashboard 廣播
（註解 `:720-724`、`if can_cancel` `:725-732`，D-8——**該處註解逐字寫「不派 SOAP」**，
cancelled 不在 `_SOAP_ON_TERMINAL` 裡）。
SOAP 觸發器共用 WS 那一支（不變式 #13），可產報告的場次終態改成
`{completed, aborted_red_flag}`——**紅旗中止是最需要報告的一類**。
真正的升級是：新增 `backend/tests/unit/test_terminal_path_six_things_matrix.py`，
AST 掃 `conversation_handler`／`session_service`／`tasks.session_timeout` 三個模組裡所有
「把場次寫成終態」的呼叫點，與 `TERMINAL_PATHS` 註冊表比對，**新增 fan-out 點沒登記就直接紅**
（`test_registry_covers_every_terminal_fanout_site`），「刻意不做」的格子刪掉程式碼註解錨點也會紅
（`test_skipped_cells_are_documented_in_code`）。這條鐵律從此不再靠人肉記憶執行。

### [x] R4. 🟡 Celery 重試設定是假的 — `ae2b95e`

宣告 `max_retries=2 / default_retry_delay=30`，但 task body 從不呼叫 `self.retry()`、
也沒設 `autoretry_for` → 任一次 OpenAI 失敗就永久 `failed`。docstring 還寫著「retry ×2」。

### [x] R5. 🔴 病患端收到醫師向的紅旗文字 — `fb85f41` / `4a125e8`

送到病患 WS 的 `red_flag_alert.description` 是醫師向臨床推理，實測含「建議立即急診評估」，
兩份前端都原樣渲染。第一次修在 render 層（不渲染 description），真跑證明 `suggestedActions`
照樣送到病患裝置並落庫。**禁字黑名單擋不住 LLM 換句話講**，最後改成後端結構性地不送。

### [x] R6. 🔴 病患端提示對病患說謊 — `fb85f41`

終止提示明說「系統已將…通知現場醫護人員」，但 high/medium 紅旗在 `doctor_id` 為 NULL 的
kiosk 場次**不會產生任何 notification**（真跑實測 notifications 表 0 筆）。

### [x] R7. 🟡 `conversation_summary` 是死 key — `fb85f41`

`red_flag_detector` 的語意層讀 `session_context["conversation_summary"]`，但全 repo
**沒有任何地方寫入它**。紅旗兩層都只看本輪單句＋主訴字串，跨輪累積型 critical
（前輪發燒＋本輪腰痛＝urosepsis）偵測不到。

### [x] R8. 🔴 規則層對真人語序 4/5 語漏偵測 — `3a9e9b4`

規則層用**相鄰複合子字串**比對（`睪丸突然`），但中/日/韓/越的真人語序會在部位詞與修飾詞
之間插入時間、方位、程度：「我左邊睪丸**兩個小時前**突然劇痛」→ zh/ja/ko/vi 四語 0 命中，
紅旗全靠 LLM 語意層獨撐。

改成「**部位詞 × 急性/嚴重度詞在同句內共現**」，語序不拘、中間可插字。五個 critical
紅旗全部覆蓋。`urinary_retention` 另開 `cross_clause`（英文最自然的講法是對比句
「平常正常，但現在尿不出來」，部位詞落在前一子句）。

### [x] R9. 🔴 §3b 家族史整串當 haystack ＝ **捏造病歷** — `949afbb`

惡性詞與泌尿詞可以來自**不同家人**就判 `answered_yes`：「母親：乳癌、父親：攝護腺肥大」
→ 判定「有泌尿癌家族史」→ 該風險因子被跳過，**而且 prompt 還叫 LLM 直接採用此資訊寫進病史**
→ SOAP 會憑空寫出病患沒有的泌尿道癌家族史。

漏問只是漏問；把病患沒有的家族史寫進醫師報告是另一個量級。改成逐筆（per relation）判定。

### [x] R10. 🟡 §3b gating 判「欄位非空」而非「值涵蓋」 — `949afbb`

用藥欄填 amlodipine（沒填 OTC aspirin）→ 抗凝血整項進禁問清單；`medical_history` 只填
高血壓 → 同時關掉「心血管疾病史」與「糖尿病」。§3b 從硬性安全不變式降級成「信任表單完整度」。

改成三態：明確的「無」→ 不問／值真的涵蓋 → 不問／**值不涵蓋或欄位空白 → 仍必問**。
判不準一律歸「仍必問」。gating 只吃本次場次 intake，不吃 `patients` 表舊資料
（回診病患會被幾個月前的紀錄擋住不問用藥）。

### [x] R11. 🔴 血尿主訴在英文下結構上問不完 — `3a9e9b4`

`gross_hematuria_heavy`（critical，會中止問診）的量詞維度混進了**純顏色詞**
（`bright red` / `bloody` / `真っ赤` / `새빨` / `đỏ tươi` / `尿血`）。heavy 的臨床定義是
**量與血塊**不是顏色。後果：

```
英文「bright red blood in my urine」→ critical → 第 2 輪 abort
中文「整泡尿是紅色的」              → high     → 不中止
```

同一個臨床情境語言不同結局不同，而**血尿是選單上的主訴 c1**——病患一講出自己的主訴就被
中止，該問診路徑在英文下永遠跑不完。顏色詞降級到 `gross_hematuria`(high) 並補共現組
（單詞 trigger 接不到 `blood in **my** urine` 的所有格，直接刪會變成完全漏報）。

### [x] R12. 🔴 SOAP `plan.patient_education` 是病患面卻含鐵律禁字 — `7144e85`

該欄位直接渲染在病患頁（React `PatientSessionDetailPage`、Flutter `patient_session_detail_page`，
Flutter model 註解就寫 `the patient-facing advice`），但 SOAP prompt 從來沒告訴 LLM 這件事。
真跑兩場都吐出「立即就醫」。prompt 約束 ＋ 出口消毒兩層都做。

判準是「**有沒有叫病患自行離場**」而不是「有沒有出現某個詞」——「醫師會為您安排急診評估」
對候診中的病患不違規。

### [x] R13. 🟡 ja/ko/vi 場次的紅旗文字仍是中文 — `4a125e8`

六個 alert 相關 key 只有 zh-TW 與 en-US，`get_message` 缺譯退回 `DEFAULT_LANGUAGE`。
`title` 因為有 `display_title_by_lang` 而正確，所以**肉眼很容易誤判成已在地化**。
已補 5 語並加結構性測試（外顯 key 必須 5 語齊全）。⚠️ 譯文待母語臨床者覆核，與 E10 同批。

### [x] R14. 🟡 收尾輪「不得發問」只有 prompt 一層防線 — `fb85f41`

真跑同一份碼會時紅時綠（DB 裡 2026-07-06 就有同型懸空結尾）。ED 場的 `effective_hard_cap`
正好與收尾輪重合、零餘裕，LLM 那一輪不從病患就 100% 看到懸空問句然後被導走。
加確定性 backstop：偵測到問句就改送制式收尾語。

---

### 驗收套件缺陷（已修，`d247388`）

> **不修這一組，前面所有修復的「驗收通過」都沒有意義。**

### [x] R15. 🔴 SOAP 輪詢等的是「有 row」不是 `status='generated'`

而那個 row 是場次結束當下就以 GENERATING、內容全空 INSERT 的佔位列。一抓到就 break，
**必現地在 Celery 完成前拍空快照**——「SOAP 全卡 GENERATING」這個生產真的出過的事故
在 e2e 上恆 pass。

### [x] R16. 🔴 一批恆真斷言與空跑報 pass

- `soap_reports.language` 比對的是 DB `server_default`
- `FIELD_HPI_IDS` 是空 tuple，`any(m in ())` 結構上不可能失敗
- post-abort 提示的 `len(set(...)) == 1` 對 n=1 恆真
- **前提未觸發卻報 pass**：AI 全場沒問過病史，「不重問病史」的斷言卻綠

加入 `pass / fail / not_applicable / precondition_not_met` 多態，未驗到不算過。

### [x] R17. 🟡 風險因子斷言是寬鬆子字串比對

`"family" in ai_text` 連「family have diabetes」都中；`"smok"` 連 AI 複述病患的話都中。
改成要求出現在問句裡並排除複述。措辭檢查原本只掃 `red_flag_alert` payload，
掃不到 SOAP `patient_education`、`suggestedActions` 與 AI 逐字稿，已抽成所有 analyzer 共用。

### [x] R22. 🔴 尿路敗血症紅旗的「熱」吃掉排尿灼熱 — 2026-08-18 臨床拍板（`7a59205`）

實證 session `dda55701`：病患講「排尿時灼熱刺痛」這類 **dysuria（排尿局部灼熱，泌尿科最
常見主訴之一）**，規則層判成 critical **尿路敗血症**並中止整場問診——病患一講出自己的主訴
就被趕走。

根因不是誤報太多，而是**詞表寫錯臨床語意**：urosepsis 的兩軸是「泌尿症狀 ×
**全身性**感染徵象」，但全身軸收了 ja 段的裸「熱」，而它同時涵蓋局部的 熱い／熱く／灼熱感；
共現組詞表又是**全語言聯集**（W1 設計），於是那一條裸「熱」連中文的「灼熱／熱熱的」一起吃掉。

> **臨床拍板（2026-08-18）：「熱」只認全身性發燒語彙（發燒／發熱／體溫／畏寒…），
> 排除灼熱／刺熱等局部症狀描述。**

⚠️ 這是**語意修正，不是 R21 意義下的抑制守衛**——局部灼熱從來就不屬於全身徵象，與 #22 對
`gross_hematuria_heavy` 的判斷同型（判準照臨床定義，不照字面）。但仍按 R-lessons 第 4 條
逐字面舉證無漏報。詞表淨變化 **−1／+19 字面**，**發燒側召回率只增不減**：

- **ja**：刪裸「熱」，改用助詞／接尾形（`熱が`／`熱も`／`熱で`／`熱を出`／`度の熱`，另補 `微熱`），
  確保「熱い」接不到而發熱用法照收
- **zh**：補口語發燒詞，並要求**全身性主體錨點**（`身體很熱`／`全身發燙`／`額頭發燙`），
  使「小便很熱」接不到而「身體很熱」接得到
- **ko／en／vi 逐條審視後維持現狀**，三個**保留在誤報側**的邊緣案例已就地記在詞表註解：
  ko `열나`（局部灼熱韓文用 화끈거리다／따갑다，實測 0 誤爆，殘餘周邊例依 R21 不動）、
  en `burning up`（要擋掉需加 `i'm`／`am` 主語錨點，會同時丟掉「the patient is burning up」
  ＝製造漏報）、vi `sốt ruột`（＝著急的慣用語同形，移除 `sốt` 會丟掉最主要的越南文發燒詞）

驗證：新增 `test_red_flag_urosepsis_fever_semantics.py`——**57 條五語雙向語料**
（MUST_FIRE／MUST_NOT_FIRE 各語言 ≥3 筆，未受改三語留對照防外溢），語料本輪新寫並由結構性
測試守住**不抄 dda55701 逐字稿與 e2e persona 台詞**（R-lessons 第 3 條），另以「把裸『熱』
加回詞表」的**注入式回歸**驗證 11 筆確實轉紅。`test_red_flag_cooccurrence_coverage.py` 的
ja 探針改為「発熱」並補上「裸『熱』不得回到本軸」的反向對照；`test_red_flag_suppression_policy.py`
就地記載本次拍板。真 OpenAI e2e：**ruleprobe 36 全過、torsion 10/10、hematuria 基線乾淨**。

---

### 未結案

> ⚠️ **2026-08-20 稽核輪的影響（R18／R19／R20／R21 四條都**不**據此結案）**：IN-3 把 supervisor
> 的來源標籤改成三態（本次 intake「（intake 已提供）」受「不得重述」限制／`patients` 表
> fallback 標「（病歷記載，過往）」且明文不套用該條款，`backend/app/pipelines/supervisor.py`），
> D-8 窄化了 `is_dont_know`（標記詞 ∧ 同句無「數值＋量詞」才算拒答）並修掉 guidance 讀取端
> 硬寫 `gu:` 前綴——**R18／R19** 的前提**可能**已改變（R20／R21 本輪完全沒碰）。
> 本輪 commit message 未宣稱解掉其中任何一條。
>
> **逐探針比對其實留了**（先前記載「沒有留下」是錯的）：`scripts/e2e_realopenai/results/`
> 裡 `intake_wiring_zh.json` 的 `analysis.i5_no_reask_intake_fields` 有完整 `gated_fields`／
> 逐欄 `reask_hits`／`persona_confirmed_reasks`／`restatements_excluded`；`dontknow_zh.json`
> 有 8 筆 `guidance_timeline`（turn 0 為 `guidance: null`）逐輪 `next_focus`，加上
> `b2_next_focus_not_refused_fields` 的逐欄 violations 與 `a_/a2_/a3_` 的 `paraphrase_reask_hits`。
>
> ⚠️ **但真正該記的是：`i5` 在現行碼上仍會飄。** `results/intake_wiring_zh.24d3083_run1_i5fail.json`
> 是**同一個 head `24d3083` 上的 i5 FAIL**（第 9 輪 AI 問「請問您以前有沒有得過尿路結石、
> 膀胱發炎，或做過泌尿科相關治療？」，病患第 10 輪回「這些我剛剛在表單上都填過了」），
> 同日稍後重跑才 PASS（FAIL 那場 `started_at 14:52:54Z / finished_at 14:55:49Z`、
> PASS 那場 `started_at 15:04:43Z / finished_at 15:08:13Z`；**寫兩個時間戳不寫「幾分鐘後」**
> ——start→start 11m49s、finish→start 8m54s、finish→finish 12m24s，沒有一種讀法是 13 分鐘）。
> ⚠️ `results/` 裡另有一份 `intake_wiring_zh.run1_i5fail.json`（**無 head 前綴**），它是
> **稽核前基線 `67cdf30`** 上的 FAIL（08-20 12:58→13:02）＝修復前的預期結果，
> **不是本條的證據**。grep `i5fail` 會同時撈到兩份，別混用。
> 所以 R18 的前提**不是**乾淨地「已改變」——它是不穩定的。
> 要結案必須重跑 `intake_wiring_zh` ＋ `dontknow_zh` **多次**並逐探針比對，不是看場次總判。

### [ ] R18. 🟢 `i5_no_reask_intake_fields` 斷言過嚴

AI 問「您以前有沒有得過膀胱炎、腎結石，或做過泌尿科方面的手術？」被判成重問 intake，
但 intake 的 `medical_history` 只有高血壓＋第二型糖尿病——**高血壓不蘊含「沒有泌尿道疾病」**，
而 `SessionIntake` 根本沒有手術史欄位，AI 非問不可。對血尿主訴問既往泌尿科病史是必要的。

對照：用藥欄有 aspirin 時問「有沒有在吃抗凝血劑」**才是**真重問（R10 已修）。
修法：收斂成「AI 問的主題被 intake 條目**實際涵蓋**時才算重問」——那是提升精確度不是放水。
**不要直接放寬讓它變綠**，那正是 §R 這四輪一直在抓的失敗模式。

### [ ] R19. 🟡 第 1 輪無 supervisor guidance 時換句話重問

病患第 1 輪答「不知道」onset，AI 下一句「那症狀是一下子出現的，還是慢慢變明顯的呢？」——
正是 `llm_conversation.py` 自己 prompt 明文禁止的換句話形式。第 1 輪還沒有 supervisor
guidance，對話 LLM 只剩靜態 prompt 可依循。

**2026-07-03 原始 baseline 就記載了這一條**（「唯一 FAIL 是第一輪無指導時換句話重問 onset 一次」），
長期缺陷，非 §R 回歸。修法方向：讓第 1 輪就有 don't-know 訊號，而不是繼續加強 prompt 文案。

### [ ] R20. 🟢 收尾後多跑一輪觸發空回應重試模板

```
AI    Thank you for sharing all of that. Please wait where you are…   ← 收尾合規
病患  Thank you.
AI    Sorry, I had trouble processing your last reply. Could you…?    ← 是個問句
      wrapup_source = deterministic_template:ws.ai_empty_retry_fallback
```

收尾之後病患說了聲謝謝，後端仍去跑了一輪、拿到空 AI 回應、觸發重試模板——而那個模板
是個問句，發給一個剛被告知「請稍候」的病患。**收尾後場次應該就終止不再處理訊息。**
範圍小，與 §R 改動無關（是新的嚴格斷言把它照出來的）。

### [~] R21. 🟢 政策接受的誤報 — **不是缺陷，不要修**

> **臨床拍板（2026-07-27）：紅旗規則層偏誤報。**
> 原文：「寧可多中止幾場。誤中止的代價是病患白等、護理師走一趟，可逆。」
> 漏報不可逆，所以規則層取寬。

據此**刻意保留**的誤報，已從 `xfail` 改寫成**正向政策測試**
（`test_red_flag_suppression_policy.py`）：

| 輸入 | 行為 |
|---|---|
| 「我朋友之前睪丸突然劇痛」／「家族が睾丸の激痛で運ばれた」 | 第三人稱轉述 → 仍觸發 critical |
| 「고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요」 | 韓文無標點、別部位誤配 → 仍觸發 |
| `my left leg feels a bit numb, my bladder is fine` | 移除英文 `(部位) is fine` 抑制的代價 → 仍觸發 |

⚠️ `xfail` 的語意是「缺陷、暫時容忍」，會誘導後人去「修好」它而**開出漏報**。
要改成不觸發，需要臨床重新拍板，**不是工程可以自行決定的**。

---

### R-lessons — 六條載重教訓（動這條管線前先讀）

> 四輪連續三次擺盪，每一次的根因都在這裡。這一節比任何一條個別修復都重要。

1. **不要用字串相鄰比對做臨床語意判斷。**
   `睪丸痛` 這種裸關鍵字會 over-trigger（`eyeball hurts` 都中）；收成 `睪丸突然`
   這種相鄰複合詞又會 under-trigger（真人語序中間插字就漏）。往哪邊調都會在另一邊出事。
   **同句共現**（部位 × 急性）這個結構天生同時解掉兩個方向。

2. **測試表必須雙向對稱。**
   第一輪只加「必須命中」→ 改出 over-trigger。第二輪只加「不該命中」→ 改出 under-trigger。
   任何偵測邏輯的改動，`MUST_FIRE` 與 `MUST_NOT_FIRE` 要同時存在，缺一邊就是在替下一次擺盪鋪路。

3. **反例措辭不得與 e2e persona 台詞雷同。**
   這是最深的一個假象：`torsion_critical_zh` 的台詞「左邊睪丸突然劇烈疼痛」剛好讓
   `睪丸突然` 相鄰，所以 e2e 全綠——**驗收套件證明的是「這句台詞會命中」，不是
   「這個臨床情境會命中」**。情境台詞與關鍵字互相配適 ＝ 拿實作配適測試。

4. **每一條抑制守衛都是潛在漏報，舉證責任在保留方。**
   否定／時態／假設／行政詢問守衛每加一條，就多一個真症狀被抹掉的面。
   保留任何一條都要能說出「為什麼它不會造成漏報」，說不出來就收窄或移除。

5. **測試的 oracle 不能是實作自己的偵測器。**
   SOAP 消毒層用自己的 regex 當判準 → 偵測器漏掉的句型測試也一定漏掉，
   結果是 2804 個 unit test 全綠但 e2e FAIL。用**獨立維護的違規句語料**。

6. **驗收斷言要能區分「驗過」與「前提未觸發」。**
   空跑報 pass 比沒有這條斷言更糟——它讓人以為驗過了。多態（含
   `precondition_not_met`）不是形式主義，是唯一能讓「其實沒驗到」現形的方式。

**注入式回歸測試**在這四輪抓到 6 個問題（把修復故意改壞，確認有測試會紅；沒紅就是
那個修復沒有測試保護）。這招值得變成常規 Gate 步驟。

---

## S — LLM 管線稽核與全數修復（2026-08-20，PR #55 `b7323ca`／9 commits ＋ 2026-08-21 第二戰役 PR #57 `3eacd50`）

> 方法：以 `.claude/skills/voice-pipeline-invariants/SKILL.md` 的不變式為基準
> （**稽核當時 27 條，本輪之後已擴到 37 條**），
> 四路靜態稽核 ＋ 真 OpenAI e2e 六場**只讀不修**先產出缺陷表，再逐項修復、逐項驗收。
>
> §R 的教訓又應驗一次：**「跑得完」不等於「是對的」**。本輪兩條 P0 都是**漏報**
> （紅旗該響沒響），而且都是既有測試**結構上看不到**的形狀——e2e 送裸 JSON 繞過前端 payload
> 組裝（IN-1 的偽造 `no_*` 從未被 e2e 照到）、紅旗 `MUST_FIRE` 語料沒有「否認前綴 ＋ 真症狀」
> 這個形狀、沒有任何測試在看「終態 × 六件事」矩陣、消毒語料缺 `urgency` enum 的時間窗族、
> §3b 涵蓋詞庫零 ja/ko/vi 語料。**測試盲區本身就是缺陷**，本輪新增的 650 條（collected 差；
> passed 差是 648，見下方總驗收）多半在補這幾面。

### 已修（索引；行為變更的條文已進 skill 與 CLAUDE.md 鐵律，細節見各 commit message）

| commit | 範圍 |
|---|---|
| `8e30bd3` | e2e 工具可攜性：路徑推導、`E2E_PORT`、HS256 測試密鑰、`ps` 解析加 `LC_ALL=C`（中文 locale 下 `verified` 恆 null ＝假性 FAIL）、`ed_zh` 回合上限 12→18 |
| `931b9b7` | Flutter intake：**IN-1**（`no_*` 只能來自明確勾選）、D-3 relation 在地化、D-10 `no_family_history` 勾選框、D-5 主訴路由改 URL query 參數 |
| `116282d` | 結束機制：**EM-1** abort 收尾缺 `return` 的降級路徑、EM-4 `end_session` 終態守衛三件套、EM-5「先標 `_terminated` 再送」、REST 六件事、SO-3 硬上限 drain 等 late alert 持久化完成才派 SOAP |
| `6fc51e3` | 紅旗偵測：**RF-1／RF-2 兩條 P0 漏報**、RF-3／RF-4 誤報字面逐條舉證收窄（**RF-3 從 `triggers` 移除裸 trigger、降進共現組**，這個 commit 移了 9 條，2026-08-21 RF-5 補上漏網的第 10 條 `blood clots`；**RF-4 從共現組的 `acuity_terms`／`site_terms` 直接刪除 12 條短字面、另補長字面替代**——兩張不同的表，**條數以 `RF3_BARE_TRIGGERS_REMOVED`／`RF4_SHORT_LITERALS_REMOVED` 兩個常數為準，別引這裡的數字**）。⚠️ 這個 commit 開出了 S7 的跨子句漏報 |
| `7e28d11` | Flutter 病患端顯示：下架未確認 ICD-10／信心分數、`patientFacingLocalized` 三態 resolver、regenerate 修通 |
| `2daa82c` | React 對稱：**EM-3** 結束問診不搶先導頁（導頁由後端終態事件驅動）、病患端顯示、`no_family_history`、regenerate body |
| `c6938c8` | SOAP 報告鏈：**SO-1** 時間窗×自行求醫消毒規則、SO-2 regenerate／FAILED 可恢復、`soap_reports.patient_facing_localized` 病患語言摘要、D-4 型別矯正、SO-5 PDF 欄位化 |
| `24d3083` | 對話層：**IN-2** §3b 涵蓋詞庫補齊五語、IN-3 來源標籤三態、D-2 配額吃過濾後的 must-ask 數、**D-1** 病患自由輸入雙層消毒、D-8（`is_dont_know` 窄化＋guidance key prefix＋壓縮歷史摘要真的進得了 LLM） |
| `fb403d6` | e2e `t5` 斷言改版：錨定「終止後零 LLM」的實質，不把其中一種合格樣態寫死成唯一樣態 |
| `3eacd50` | **第二戰役（PR #57，merge `5457b32`）**：修掉第一戰役自己造成的回歸與遺漏——**S7** 紅旗跨子句漏報（`urine_x_heavy_blood` 開 `cross_clause` ＋補 RF-3 漏網的英文 `blood clots` ＋ urosepsis 缺的 `pass water`）、**S8** SOAP prompt 補入口消毒、**S10** `sanitize_for_prompt` 行首標記剝到固定點 ＋ 補 BiDi isolates ＋ oracle 同步、**S11** 終態 AST 跳閘器改 `_terminal_writes` 十種形狀、**S12** 越南文 `tiểu` 假朋友位置排除。逐條見下方 S7／S8／S10／S11／S12 |

**總驗收**：backend unit **4602 passed / 4604 collected**（稽核前 `67cdf30` 是
**3954 collected**）。**passed 的差是 +648，不是 +650；+650 只對 collected 成立**
（4604−3954）。⚠️ 先前那句「+648 是拿 4602 **passed** 減 3954 **collected**、單位不一致」
**撤回**——+648 其實正是正確的 passed 差，那次「訂正」把單位錯換成了環境錯。
真正的陷阱是**跑法不同**：`tests/unit/pipelines/test_red_flag_cooccurrence_coverage.py` 有
兩條測試（`test_corpus_is_not_copied_from_real_transcripts`／逐字稿 critical 巡檢）在
**沒有 `scripts/e2e_realopenai/results/*.json` 的 clone 上會 `pytest.skip`**，
所以同一份碼有兩種數字：**有 results → 3954 → 4602 passed；沒有 results → 3952 → 4600 passed**，
**兩種算法的 passed 差都是 648**。「3952 → 4602」是把沒有 results 的舊數字對上有 results 的新數字，
條件不一致。引用這組數字時**一定要連跑法條件一起寫**。
注入式回歸依**七個** commit message 自報合計 **82 組**
（`931b9b7`=7、`116282d`=11、`6fc51e3`=8、`7e28d11`=11、`2daa82c`=12、`c6938c8`=24、
`24d3083`=9；只算四個 backend commit 是 52——**先前記的「54 組」不對應任何子集**）。
⚠️ **是七個不是九個**：`8e30bd3` 的 commit message 完全沒有注入字樣；`fb403d6` 自報的是
「**10 組離線注入驗證可抓違規**」——那是 e2e `t5` 判準改版的離線驗證，與 unit 層的
「注入式回歸（把修復改壞看測試會不會紅）」不是同一個類別，**刻意不計入 82**。

其餘驗收：flutter 217 tests ＋ `analyze` 零 issue、React type-check／lint／build／11 tests、
`check_translations.py` OK、真 OpenAI e2e 六情境全 PASS ＋ ruleprobe 36 ＋ preflight 10
（⚠️ 六場的 `backend_head` 皆為 `24d3083`，在第 9 個 commit `fb403d6` 之前）。

**第二戰役（`3eacd50`）的總驗收另計**：backend unit **4743 passed / 2 skipped**
（2026-08-21 在 merge `5457b32` 上實跑重現，跑法＝**有** `scripts/e2e_realopenai/results/*.json`
的工作副本——沒有 results 的 clone 會少 2 條，理由同上一段）；相對第一戰役的 4602 passed
是 **+141**，全部落在 `test_red_flag_audit_2026_08.py`（S7／S12 的雙向語料與注入測試）、
新檔 `test_soap_prompt_injection_sanitization.py`（S8，12 條）、
`test_terminal_path_six_things_matrix.py`（S11 的 `_BLIND_SPOT_INJECTIONS` 十型）、
`test_prompt_injection_sanitization.py`（S10 的固定點與零寬字元語料）。
真 OpenAI e2e 4 場全 PASS（torsion×2／`hematuria_3b_en`／新增 `injection_pseudosection_zh`）
＋ ruleprobe 36 ＋ preflight 11。**引用測試數時務必連 commit 與跑法一起寫**，
4602 與 4743 是兩個不同 HEAD 的數字，不是同一份碼的兩種算法。

**五項拍板（已落地）**：① 紅旗誤報字面逐條舉證後收窄（保留清單 `KEPT_LITERALS` 見 S1／S2）
② ICD-10 白名單全剝時保留 raw 碼並標 `icd10_verified=false` ③ 病患端下架未確認 ICD-10 與
信心分數，非中文場次另生場次語言摘要（新欄位 `soap_reports.patient_facing_localized`，
migration `20260820_1000`；**主報告與 `report.language` 仍固定 zh-TW，不變式 #12 不變**）
④ `report_ready`／`report_failed` 對 `doctor_id` NULL 場次 fan-out 全院在職醫師
⑤ e2e `t5` 斷言錨定實質而非樣態。

**順帶查證（不是本輪改的，但確認過，避免下次重查）**：React 端 intake 的三件事都已與
Flutter 對稱——**四個** `no_*` 都只來自明確勾選框 state、無空清單推斷
（`frontend/src/screens/patient/MedicalInfoPage.tsx:259` `noKnownAllergies: noAllergies`／
`:270` `noCurrentMedications: noMedications`／`:279` `noPastMedicalHistory: noHistory`／
`:291` `noFamilyHistory`；勾選框 state 在 `:172`）、
family relation 送在地化字串（`:297`）、主訴→基本資料**本來就走 URL query 參數**
（`SelectComplaintPage.tsx:239` → `MedicalInfoPage.tsx:137-141`，重整／深連結不會 422）。
D-5 那條只需 Flutter 端補，React 無事可做。

### 未結案

### [ ] S1. 🟡 待臨床拍板：`寒顫／chills／悪寒／오한／ớn lạnh` 是否從裸 trigger 降進共現組

現況：這一族**一個詞就判 urosepsis critical**（`backend/app/pipelines/prompts/shared.py` 的
`urosepsis`（`urinary_x_systemic_infection`）定義，`"寒顫"` 在 `triggers` 與
`triggers_by_lang["zh-TW"]` 兩處），與本輪拍板移除的 `高燒／高熱／고열` 同屬「單軸即 critical」
——但**不在本輪臨床覆核清單內**，依不變式 #22（收窄的舉證責任在提出方、且要逐字面）
不擅自動它。保留理由已就地寫在該定義上方的 RF-3 註解區塊，保留清單常數在
`backend/tests/unit/pipelines/test_red_flag_audit_2026_08.py` 的 `KEPT_LITERALS`。
**要改需重新臨床拍板**，不是工程可以自行決定的（同 R21）。
（本條刻意不寫行號：`shared.py` 這一區在 2026-08-21 的 S7 修復中正在變動。）

⚠️ **四語意識改變詞不在 `KEPT_LITERALS` 裡，去那裡找會找不到。** `KEPT_LITERALS`
（`test_red_flag_audit_2026_08.py:481-502`）**只有 4 個 key**：`寒顫/chills/悪寒/오한/ớn lạnh`、
`整個都是血/一大堆血`、`かたまり/덩어리`、`平熱`。四語意識改變詞（`altered consciousness`／
`意識がもうろう`／`의식이 흐려짐`／`rối loạn ý thức`）寫在
**`REMOVED_LITERAL_JUSTIFICATION["意識不清（urosepsis.triggers）"]`** 的 ⚠️ 段
（`test_red_flag_audit_2026_08.py:423-430`）——本輪移除的是中文的「意識不清」，那段 ⚠️ 是在
警告「別順手把其餘四語一起收掉」。那四個是**共現組接不住**的字面（不在 `acuity_terms`），
移除會造成真漏報，**不在本條的討論範圍**。
（`backend/app/pipelines/prompts/shared.py` 裡 `urosepsis` 定義上方那段 RF-3 註解的
「⚠️ 保留的字面與理由見 …KEPT_LITERALS」段落有同一個混淆，兩處都該改。
**本條刻意不寫行號**——見 S1 開頭的同一個理由。）

### [ ] S2. 🟡 待臨床拍板：`整個都是血`／`一大堆血` 兩個字面

`gross_hematuria_heavy` 的 `triggers` 現有四個字面（`shared.py` 的 `gross_hematuria_heavy` 定義）。`大量血尿`／`血尿很多`
自帶「血尿」＝已含泌尿軸；這兩個沒有——字面上「整個都是血」可以是任何部位的出血。
本輪未經臨床覆核，依 #22 保留並記進 `KEPT_LITERALS`。

對照：同一條紅旗的 `血塊／血の塊／혈전` 已在本輪降進 `trigger_cooccurrence.urine_x_heavy_blood`
（多要求**同句**有尿液詞——`urine_x_heavy_blood` 這一組在 `6ecf10a` HEAD 上**沒有宣告
`cross_clause`**，預設 False，**這一點請直接讀 `shared.py` 的組定義**、別去引
`_pairing_scope_ok` 的 docstring，理由見 S7 那個框；`gross_hematuria_heavy` 定義上方那段
RF-3 舉證註解寫成「同一/**相鄰子句**」是錯的，與該組當時的實際行為互斥），
舉證與實測句寫在同一段 RF-3 註解裡
（**本條與 S1 同樣刻意不寫行號**：`shared.py` 這幾區在 S7／S8 修復中正在位移）——移除的動機正是
「腳上有一塊血塊瘀青」「다리에 혈전이 생겼대요」（下肢 DVT，是**別的**急症）被判成血尿 critical。
⚠️ **這個「相鄰子句」的誤述低估了降級後的漏報面，實際已開出 S7**，見下。

### [ ] S3. 🟢 `_REPORT_FAILED_COPY` 應搬進 `app/utils/i18n_messages.py`

`backend/app/services/notification_service.py:729-747` 是一份五語硬寫拷貝。碼內已有 ⚠️ 註記
（`:723-728`）寫明這是**本輪的檔案邊界限制**（該檔由另一位執行者持有）**不是設計選擇**。
修法：改成 `notifications.report_failed.title` / `.body` 兩個 key，刪掉該 dict 與
`_REPORT_FAILED_DEFAULT_LANG`。搬之前確認文案語氣與其他 `notifications.*` 一致。

### [ ] S4. 🟡 e2e driver 沒撈 `patient_facing_localized`，措辭鐵律掃不到病患實際看到的那份文字

`scripts/e2e_realopenai/driver.py:1376-1380` 的 `soap_select` 取的是
`id, status, review_status, generated_at, subjective, objective, assessment, plan, summary`
（＋條件式的 `language, icd10_codes, icd10_verified, review_notes`，`if c in soap_cols`），
**沒有 `patient_facing_localized`**（全 `scripts/e2e_realopenai/` grep 零出現），
`_patient_facing_texts`（`:2908`）因此**永遠掃不到病患語言版的兩欄**。

後果：**非 zh-TW 場次的病患實際讀到的那份文字，沒有任何 e2e 措辭鐵律覆蓋**。消毒層確實有
目標語言規則，但只有 unit test 撐著——§R-lessons 第 5 條（oracle 不能是實作自己）講的正是
這個風險面。修法：`soap_select` 加欄 ＋ `_patient_facing_texts` 加一個 source，
並照該函式既有的多態設計，**來源缺席時記為缺席、不得當成「掃過了」**（第 6 條）。

### [ ] S5. 🟢 `generate_report(additional_notes=...)` 收下但完全未使用

`backend/app/routers/reports.py:121`／`:126` 把 body 的 `additional_notes` 傳進
`report_service.generate_report`，但 `backend/app/services/report_service.py:430` 只在簽名接住，
**函式體零引用**（全檔 grep 只有簽名那一處）。醫師在 UI 填的補充說明被**靜默丟棄**。

二選一：接進 regenerate 的 prompt／revision reason，或從 `backend/app/schemas/report.py:80`
移除欄位（移除是 API 破壞性變更，要先確認沒有 client 在送）。

### [ ] S6. 🟢 `REPORT_ELIGIBLE_SESSION_STATUSES` 與 `_SOAP_ON_TERMINAL` 是兩份清單，沒有測試釘住一致

- `backend/app/services/report_service.py:56-61`＝REST 直接產報告的閘門
- `backend/app/services/session_service.py:101-103`＝終態轉移後自動派 SOAP 的集合
- `cancelled` 的政策還散在第三處（`backend/app/tasks/session_timeout.py`）

目前三處一致（`{completed, aborted_red_flag}`，`cancelled` 不派），碼內也註明「要改政策請三處
一起改」（`session_service.py:98-100`）——但那是**註解不是跳閘器**。現有測試
（`backend/tests/unit/services/test_report_generate_regenerate.py:146-151`）只斷言前者的成員，
沒有任何測試斷言兩集合相等。

修法：加一條結構測試斷言兩者相等（若日後刻意分歧，就在測試裡逐項寫下理由），
或把三處收斂成同一個常數。這與 §S 的 `test_terminal_path_six_things_matrix.py` 同型——
**靠人肉記憶執行的一致性規則遲早會漂移，要有跳閘器**。

### [ ] S7. 🔴 紅旗跨子句漏報：`血塊` 降進共現組開出的回歸（2026-08-21 發現，**修復中**）

> ⚠️ **編號對照：本條在 `shared.py` 的碼內註解裡叫 `RF-5`。** 同一個缺陷、兩個編號
> （文件沿用 §S 序號、碼內沿用 RF-n 序號）。看到 RF-5 就是本條，別當成第七條紅旗缺陷。

`6fc51e3`（RF-3）把裸 `血塊／血の塊／혈전` 從 `gross_hematuria_heavy.triggers` 移進
`trigger_cooccurrence.urine_x_heavy_blood` 的 `acuity_terms`。但該共現組
（`backend/app/pipelines/prompts/shared.py` 的 `gross_hematuria_heavy` 定義內，
**刻意不寫行號：本檔修復中正在位移**）
**沒有宣告 `cross_clause`**（預設 False）。

> ⚠️ **判斷「哪些共現組開了 `cross_clause`」要去讀共現組資料本身**（`shared.py` 組定義裡
> 有沒有那個 key），**不要引 `red_flag_detector._pairing_scope_ok` 的 docstring**。那段
> docstring 曾把判準寫成「site×acuity 型紅旗（睪丸扭轉／尿滯留／血尿）維持不開」，但
> `urinary_retention` 的 `void_x_obstruction` **早在 2026-07-27 就是 `cross_clause: True`**
> （為英文語序「normally i pee fine, but…」開的，`shared.py` 有理由註解）——那句話在寫下時
> 就已經與資料互斥。實際判準是「**這兩個軸是不是兩個不同的觀察**」，不是紅旗的臨床分類名。
> （該 docstring 已在 RF-5 同輪訂正成「權威是資料，這裡只記判準」。）

實測（2026-08-21，規則層，`6ecf10a` HEAD）：

| 輸入 | 規則層 |
|---|---|
| `尿裡有血塊` / `我剛去上廁所，馬桶裡有血塊` / `小便有很多血塊` | `gross_hematuria_heavy(critical)` ✅ |
| **`我今天小便，然後有很多血塊`** | **`[]` ← 零紅旗** |
| **`小便的時候，血塊一直出來`** | **`[]` ← 零紅旗** |
| `我發燒到三十九度，而且小便的時候很痛` | `urosepsis(critical)`（該組才是 `cross_clause=True`） |

**這兩句是真人講大量血尿最自然的語序，降級前會命中、降級後不會**——正是不變式 #22
要求的「為什麼它不會漏報」沒守住的一面。RF-3 在 `shared.py` 的舉證註解寫的是
「多要求同一/**相鄰子句**裡有尿液詞」，那句話本身就與實作互斥，S2 也照抄了它。

修法方向（**不是直接放寬**，那會走回 §R 的老路）：要嘛替 `urine_x_heavy_blood` 開
`cross_clause` 並補雙向語料證明不開出新誤報，要嘛把「血塊」的真人語序做成長字面替代
（如 `小便…血塊` 的跨子句 pattern）。無論哪條，**MUST_FIRE 要收上表那兩句**，
且 `shared.py` 的 RF-3 舉證註解與 S2 的「相鄰子句」誤述要一併修掉。

**狀態**：已有執行者在修（工作區有未 commit 的 `shared.py` / `test_red_flag_audit_2026_08.py`
改動）。**commit ＋ 紅旗 e2e（`torsion_critical_zh` ＋ `hematuria_3b_en`）驗收之前不結案。**

**教訓（併入 §R-lessons 第 1 條的射程）**：把裸 trigger 降進共現組是「多要求一個臨床軸」，
但共現組同時還隱含「同一子句」這個**沒寫在舉證裡的第二個條件**。降級的舉證只測了同句
（「尿裡有血塊」三語），**沒測跨子句**，所以整個漏報面沒被看見。
**降級／收窄的實測句必須涵蓋跨子句語序。**

### [ ] S8. 🔴 `soap_generator.py` 的 SOAP prompt 完全沒過 `sanitize_for_prompt`（2026-08-21 發現，**修復中**）

D-1（`24d3083`）只覆蓋了**對話路徑**。在 `6ecf10a` HEAD 上，全 backend grep
`sanitize_for_prompt` 只命中 `app/pipelines/supervisor.py`、`app/pipelines/llm_conversation.py`、
`app/pipelines/prompts/shared.py`、`app/schemas/session.py`——
**`app/pipelines/soap_generator.py` 不在其中**。

`soap_generator.generate()` 把 `name` / `medical_history` / `medications` /
`allergies` / `family_history` 直接 f-string 進 `## Patient Basic Information` 區塊：

```python
patient_parts.append(f"Past medical history: {patient_info['medical_history']}")
...
user_message = f"""## Patient Basic Information
{patient_text}

## Chief Complaint
...
```

而 `patient_context.build_patient_info`（`app/pipelines/patient_context.py:131-136`）對其中
**三欄**在 intake 空白時會 fallback 到 **`patients` 表舊資料**——正是 CLAUDE.md 自己列為
「組裝層那道要涵蓋」的那條路徑（schema validator 管不到）。偽區段注入已實測重現：
病患欄位值渲染成真正的 `## Consultation Transcript` 區段標題，
**該 prompt 的 line-initial `##` 從 3 個變 4 個**——乾淨基線本來就有三個區段標題
（`## Patient Basic Information` / `## Chief Complaint` / `## Consultation Transcript`，
`soap_generator.generate()` 的 `user_message` f-string）；換個講法，
`## Consultation Transcript` 這一行從 1 個變 2 個。
（先前記的「從 2 個變 3 個」是把基線數錯了一個，注入本身可重現。）

⚠️ **fallback 是三欄不是四欄。** `medical_history` / `medications` / `allergies` 三欄
才寫成 `intake_summary[...] or format_jsonb_list(getattr(patient, ...))`（`:131-136`）；
`family_history` 是光桿的 `intake_summary["family_history"]`（`:137`），**沒有 fallback**
——因為 `backend/app/models/patient.py` 根本**沒有 `family_history` 欄位**
（只有 `medical_history` / `allergies` / `current_medications`，`:38-40`）。
`patient_context.py` 那段「上面四個扁平欄位…會在 intake 空白時 fallback 到 patients 表」的
碼內註解本身就是錯的，工作區 `soap_generator.py` 新加的 D-1b 註解 **(b)** 又照抄了一次，
**這兩處要與 S8 的修復同輪改掉**（本條不改碼，只列管）。

**這條 prompt 攻擊面最大、含 PHI 最多，卻是唯一沒被覆蓋的一條。** 附帶問題：CLAUDE.md 原本
把規則寫成「插進 LLM **system** prompt 前」，而這段是 user message，照字面讀規則不覆蓋它——
規則的字面把最危險的那條排除在外（CLAUDE.md 已於 2026-08-21 改成「system 或 user」）。

修法：`generate()` 的五個欄位（含 `chief_complaint`）過 `sanitize_for_prompt`，
並把 `soap_generator` 加進**區段結構 oracle** 的覆蓋範圍——現有的
`test_prompt_injection_sanitization.py` 與 `tests/unit/schemas/test_session_intake_sanitization.py`
**都不涵蓋它**。

**狀態**：已有執行者在修（工作區有未 commit 的 `soap_generator.py` 改動與一支新的
`backend/tests/unit/pipelines/test_soap_prompt_injection_sanitization.py`）。
**commit ＋ 驗收之前不結案。**

**教訓**：CLAUDE.md 原本把規則寫成「插進 LLM **system** prompt 前一律過消毒」，而
`soap_generator` 這段是 **user message**——照字面讀，規則**不覆蓋攻擊面最大的那條 prompt**。
規則的字面範圍要涵蓋所有進 LLM 的文字，不能只綁 system（CLAUDE.md 已於 2026-08-21 改成
「system 或 user」）。同理，「一律」這種全稱敘述若沒有跳閘器守住，會在下一個新增的
prompt 組裝點自動變成假敘述——這正是本輪三份文件校訂要處理的通病。

### [ ] S9. 🟡 `is_dont_know` 對含數詞的固定語誤判 → AI 換句話重問已拒答的欄位（2026-08-21 發現，**尚無人認領**）

`24d3083`（D-8）把 `is_dont_know` 窄化成「標記詞 ∧ 同句沒有『數值＋量詞』」，用意是別把
「我不確定，大概三天前吧」這種**帶保留的有效回答**判成拒答。但窄化的另一邊沒有語料守住：
**含數詞的固定語／成語會讓真拒答被判成有回答**。實測（`6ecf10a` HEAD，
`backend/app/pipelines/next_focus_guard.py` 的 `is_dont_know`）：

| 輸入 | `is_dont_know` |
|---|---|
| **`我不知道，反正一天比一天嚴重`** | **`False`** ← 真拒答被漏掉 |
| **`我不知道，一天到晚都在痛`** | **`False`** |
| **`記不得了，反正一天到晚跑廁所`** | **`False`** |
| `不知道幾天` / `don't know how many days` | `True` ✅（疑問數詞先被挖除，這一邊是對的） |

根因：「一天」符合 `_NUMERAL + _UNIT`，但成語裡的「一天」不是**可記錄的值**。

**後果是「重問」不是「不問」——先前文件把因果寫反了，訂正如下。** `is_dont_know` 全庫
只有一個消費端：`declined_fields_from_history`（同檔）。回 `False` ＝ 該欄**不進** declined
集合，於是：

1. `llm_conversation` 組 system prompt 時呼叫的 `build_dont_know_ban(declined_fields_from_history(history), language)`
   拿到**空集合** → **本輪不下「不得換句話重問」的硬性禁令**；
2. `effective_next_focus` 看到 `declined` 為空就**原封不動回傳那份 `next_focus`**，而它是在
   拒答**之前**算的、仍指著同一欄 → supervisor 指導繼續把 AI 推向該欄。

兩條合起來＝**AI 會換句話重問病患剛剛拒答的那一欄**（正是 R19 那個失效面，也是這整層
四層防線存在的理由）。「該欄不會再問」是相反的敘述，別再寫。

修法方向：不是放寬也不是收緊單一條件，而是把「數值＋量詞」的白名單再窄化成**可記錄的值**
（時間點／時長／次數／0–10 分），把固定語／成語的「一/半 + 量詞」形（一天到晚、一天比一天、
三天兩頭、一次又一次）排除。**動這條窄化時，上表三句要進 `MUST_FIRE`、
`不知道幾天`／`don't know how many days` 要留在 `MUST_FIRE`、
「我不確定，大概三天前吧」要留在 `MUST_NOT_FIRE`**——雙向對稱（§R-lessons 第 2 條）。
語料檔：`backend/tests/unit/pipelines/test_dont_know_concrete_value_guard.py`
（`MUST_FIRE` / `MUST_NOT_FIRE`）與 `test_next_focus_reask_guard.py`（`MUST_REPLACE` / `MUST_KEEP`）。
改動視同改管線，要跑 `dontknow_zh` e2e（不變式 #17 的保護區）。

⚠️ 這條**先前只活在 skill #8 的 ⚠️ 與缺口表裡，TODO 完全沒有對應條目**，而 TODO 檔頭又把
未結案寫成「§S 八條」——「尚無人認領」的缺陷不進待辦清單，下一輪一定漏。本輪補進來。

### [ ] S10. 🔴 `sanitize_for_prompt` 的行首 `#` 只剝一次，`'# ## X'` 剝完還是 `'## X'`（2026-08-21 發現，**修復中**）

`backend/app/pipelines/prompts/shared.py` 的 `sanitize_for_prompt` 末段用
`_LEADING_HEADING_MARKS`（`re.compile(r"^[#＃]+[ \t　]*")`）剝行首標題符號。它是 `^` 錨定的
**單次** sub：第一段 `#` 連同其後的空白被吃掉之後，**後面的 `##` 就遞補到行首**。
實測（`6ecf10a` HEAD，真函式）：

| 輸入 | 輸出 |
|---|---|
| `'## Consultation Transcript'` | `'Consultation Transcript'` ✅ |
| **`'# ## Consultation Transcript'`** | **`'## Consultation Transcript'`** ← 仍是合法的區段標題 |
| **`'#\t## Consultation Transcript'`** | **`'## Consultation Transcript'`** |
| **`'＃ ## Consultation Transcript'`** | **`'## Consultation Transcript'`**（全形 `＃` 同型） |
| `'#  ##  Chief Complaint'` | `'## Chief Complaint'` |

**這是消毒層自己的缺口，不是 S8 的一部分。** S8 把 `soap_generator` 接上
`sanitize_for_prompt` 之後，這個形狀照樣穿得過去——兩條要一起修才真的關上偽區段注入，
而且**對話 prompt（`llm_conversation` / `supervisor`，D-1 已覆蓋的那些）現在就已經露著**。

修法：剝除跑到**固定點**（`while` 到不再變化，或改成 `^(?:[#＃]+[ \t　]*)+`），
並在 `test_prompt_injection_sanitization.py` 的區段結構 oracle 補上「多段前綴」語料
（`'# ## X'`、`'#\t## X'`、`'＃ ＃＃ X'`、`'#   #   ## X'`）。⚠️ 現有兩份消毒測試
**沒有任何一條是「剝一次不夠」的案例**——這正是 §R-lessons 第 5 條講的「oracle 只認得
實作想得到的形狀」。

**狀態**：已有執行者在修。**commit ＋ 驗收之前不結案。**

### [ ] S11. 🟡 終態 AST 跳閘器的形狀覆蓋面（2026-08-21，**與本輪同一個 commit 落地**）

> ⚠️ **本條不是「HEAD 上可重現的缺陷」，別照 S7／S8／S10／S12 的格式讀。** `6ecf10a`
> HEAD 上**根本沒有 `_terminal_writes` 這支函式**（當時的掃描器只有 `_terminal_fanout_sites`
> 的三種寫死形狀），所以「掃描器漏 tuple」這件事**沒有任何已 commit 的版本可以複驗**——
> 它只在開發中的原型裡存在過。之所以還留一條，是因為**形狀覆蓋面本身是個長期議題**，
> 值得記下判準與刻意不做的部分。

`backend/tests/unit/test_terminal_path_six_things_matrix.py` 的掃描器在本輪重寫成
`_terminal_writes`，認得的形狀是一張**清單**：

- 直接對 `.status` 賦值，含 **tuple／list 多重指派**
  （`session.status, session.completed_at = SessionStatus.COMPLETED, now`）、
  巢狀 tuple、starred 解包、鏈式指派、`AnnAssign`
- `.values(status=…)` 與 **`.values({"status": …})` 位置引數 dict**
- **`setattr(obj, "status", …)`**（屬性名是變數時保守當終態）
- 低階狀態寫入 helper 呼叫（keyword／positional／指向字面值的常數變數都吃）
- 狀態值靜態解析不出來 → `<unresolved>` → 一律要求登記（保守側）

**每一型都由 `_BLIND_SPOT_INJECTIONS` 釘住**（目前 10 型）：把該寫法真的接進產品碼副本
再交給掃描器掃，`test_tripwire_trips_on_each_known_blind_spot` 斷言「掃得到 ＋ 判定為未
登記」，`test_blind_spot_injections_are_red_under_the_old_shape_only_scanner` 反向證明
舊的三形狀掃描器對它們全盲。tuple 多重指派是其中一型——原型在開發中確實漏過它
（① 分支只認 `ast.Attribute` 的 assign target），注入測試就是為了不讓它再漏回去。

⚠️ **刻意不認**的兩類（判斷寫在該檔的設計原則段，要改請連同理由一起改）：

- `.values(**payload)`（`kw.arg is None`）：`conversation_handler._update_session_status`
  自己就是這樣寫的，認了會讓**寫入 helper 本身**變成一個 `<unresolved>` 站點＝每天一個
  假警報。「噪音會讓下一個人把跳閘器關掉」比漏一種形狀更危險（不變式 #31）。
- `session.__dict__[…]`／`vars(session)[…]`／`object.__setattr__`／把 helper 綁到別名
  再呼叫／`db.execute(text("UPDATE …"))` 裸 SQL：這些是**刻意規避**，不是有人會不小心
  寫出來的慣用法。跳閘器防的是手滑，不是防內鬼。

**還沒做**：掃描器只讀 `conversation_handler.py`／`session_service.py`／`session_timeout.py`
三個檔，「第四個模組開始寫終態」沒有任何守衛（今天沒有這種模組——唯一外部呼叫
`app/routers/sessions.py:140` 走 `session_service.update_status`，但這個範圍限制本身是裸的）。

**最後一道防線仍然是人**：新增終態路徑先在 `TERMINAL_PATHS` 補一列，再讓它綠。

### [ ] S12. 🔴 越南文 `tiểu` 是假朋友：`tiểu đường`（糖尿病）× 發燒 → urosepsis critical 誤中止（2026-08-21 發現，**修復中**）

四個共現組的 vi `site_terms` 都收了裸 `tiểu`（`void_x_obstruction`／`urine_x_heavy_blood`／
`urinary_x_systemic_infection`／`urine_x_blood_present`，`backend/app/pipelines/prompts/shared.py`）。
但越南文的 `tiểu` 同時是「排尿」與「小／次要」：`tiểu đường`＝**糖尿病**、
`tiểu phẫu`＝小手術、`tiểu sử`＝簡歷、`tiểu học`＝小學。實測（規則層，`6ecf10a` HEAD）：

| 輸入（vi-VN） | 規則層 | `trigger_keywords` |
|---|---|---|
| **`tôi bị tiểu đường và hôm qua tôi bị sốt`**（我有糖尿病，昨天發燒） | **`urosepsis(critical)`** ← 誤中止 | `['tiểu', 'sốt']` |
| **`mẹ tôi bị tiểu đường, tôi hơi sốt`**（我**媽**有糖尿病，我有點發燒） | **`urosepsis(critical)`** | `['tiểu', 'sốt']` |
| **`tôi vừa làm tiểu phẫu và bị sốt nhẹ`**（剛做完小手術，有點低燒） | **`urosepsis(critical)`** | `['tiểu', 'sốt']` |
| **`bác sĩ hỏi tiểu sử bệnh, tôi đang sốt`**（醫師問**病史**，我正在發燒） | **`urosepsis(critical)`** | `['tiểu', 'sốt']` |
| `tôi sốt và tiểu buốt`（發燒＋排尿灼痛） | `urosepsis(critical)` ✅ 真陽性 | `['tiểu', 'sốt']` |
| `tôi bị tiểu đường type 2 đã mười năm`（只講糖尿病、沒有發燒詞） | `[]` ✅ | — |

⚠️ **上表刻意用 `sốt` 當急性詞**：`sốt` 只在共現組的 `acuity_terms` 裡，所以命中**一定**經過
`tiểu` 這個 site 軸，`trigger_keywords` 也逐筆證實了。**別拿 `ớn lạnh` 造反例**——
`tôi hơi ớn lạnh` 單獨一句就命中 critical（`ớn lạnh` 是 S1 那族**刻意保留**的單軸裸 trigger），
那是 S1 的議題，與 `tiểu` 無關，混在一起會讓本條的舉證失效。

**這不能用「政策接受的誤報」（#22／R21）帶過。** 糖尿病是 §3b 的必問風險因子——
`backend/app/pipelines/llm_conversation.py` 的 `_DIABETES_TERMS` 自己就收了 `tiểu đường`
（`:391`）——所以越南語病患**照著問診流程回答自己的病史**就會撞上它。這與 R22
（`熱` 讓「排尿灼熱」一講出主訴就被中止）是同一型的結構性誤報，只是換成 vi。

修法方向（照 #22 的舉證責任）：**不是刪掉 `tiểu`**（那會丟掉最主要的越南文排尿詞、開出漏報），
而是逐字面收窄成不會撞上多義的形——例如改收 `đi tiểu`／`tiểu buốt`／`tiểu rắt`／`tiểu ra máu`／
`nước tiểu`／`buồn tiểu` 等複合形，或保留裸 `tiểu` 但排除 `tiểu đường`／`tiểu phẫu`／`tiểu sử`／
`tiểu học` 這幾個已知非泌尿義的後接詞。無論走哪條，**MUST_FIRE 要留住上表最後兩列的真陽性**、
**MUST_NOT_FIRE 要收上表前四列**，四個共現組一起改。

**教訓（併入不變式 #25 的射程）**：#25 原本只要求「新字面在**其他四語**的常見句子裡不是高頻
子字串」。`tiểu` 過得了那一關（它在 zh/ja/ko/en 句子裡不出現），卻在**自己的語言裡**是多義詞根。
**短字面的檢查要多一道：在它自己的語言裡是不是多義／有無臨床上高頻的非目標義。**

**狀態**：已有執行者在修，走的是上述第二條路（保留裸 `tiểu`、改用位置排除法——
`red_flag_detector` 新增 `_TERM_FALSE_FRIENDS` 常數與一支「關鍵字出現位置是否整個落在
假朋友複合詞內」的判定，收 intake 共病與臨床報告用詞（`tiểu đường`／`tiểu cầu`／`tiểu phẫu`／
`tiểu sử`／`tiểu học`／`tiểu não`／`tiểu động mạch`／`tiểu tĩnh mạch`／`tiểu khung`／`tiểu thùy`）
加上日常詞 `tiểu thuyết`，刻意不收 `tiểu đêm`／`tiểu tiện`／`tiểu buốt`／`tiểu rắt`／`tiểu són`
這些泌尿義）。**詞表以常數本身為準，別引這裡的列舉。**

⚠️ **這條修法結構上不可能「修完」**：漢越詞「小」的構詞沒有上限，排除表是**開放式列舉**，
未收錄的「小」義複合詞仍會供給泌尿軸（已知仍在外面：`tiểu thương`／`tiểu bang`／`tiểu thư`…，
釘在 `test_red_flag_audit_2026_08.py` 的 `RF6_VI_KNOWN_OPEN_TAIL` 與
`test_rf6_false_friend_table_is_an_open_ended_list_not_a_closed_set`——那條測試**斷言誤報仍會
發生**，收進表裡就會紅，逼人同步更新）。**所以下次收到 vi 誤中止回報，第一個假設應該是
「又一個沒收錄的複合詞」，而不是「這條路已經封死了」。**

工作區未 commit，**別當成已修**。**commit ＋ 紅旗 e2e 驗收之前不結案。**

### [ ] S13. 🟠 `chief_complaint_text` 可繞過 §3b 必問安全 gate（2026-08-21 e2e 發現，**既有行為、非本輪造成**）

`conversation_handler` 組 `session_context["chief_complaint"]` 時取的是
`chief_complaint_text or 主訴顯示名`，而 §3b 的必問風險因子是拿**這個字串**去
`get_critical_risk_factors_for_complaint()` 做關鍵字比對（`backend/app/pipelines/prompts/shared.py`
的 `CRITICAL_RISK_FACTORS.complaint_keywords`）。於是自由文字一旦不含主訴語彙，K 就是 0：

| `chief_complaint` 實際值 | `get_critical_risk_factors_for_complaint` | §3b 必問題數 |
|---|---|---|
| `勃起功能障礙`（選定主訴的顯示名） | 1 組 | 3 題（心血管／糖尿病／吸菸） |
| `Consultation Transcript`（自由文字） | **0 組** | **0 題** |

也就是說 **`chiefComplaintId=<高風險主訴>` ＋ 任意 `chiefComplaintText` 的請求可以把 §3b
安全 gate 整個關掉**，而 FK 明明指著高風險主訴。2026-08-21 的 `injection_pseudosection_zh`
e2e 場次是實證：同一個 ED persona，帶自由文字時 9 輪就收尾且三個風險因子一題都沒問，
對照 `ed_zh` 是 15 輪問滿。

**生產可觸及面窄但不是零**：兩份前端送的是 `complaintText || complaintName`，自由文字只在
選「其他」sentinel 時才會是病患自填；但 API 直呼不受此限，且「其他」主訴本來就拿不到 §3b
（那是既有設計，不是本條）。

修法方向（未定案）：§3b gating 改吃**選定主訴的 canonical 名稱**（有 FK 時），自由文字只在
sentinel 情境下當唯一來源；或取兩者聯集。任一改法都動到 §3b 配額，依 skill 修改流程要跑
`ed_3b_zh` / `hematuria_3b_en`。

⚠️ 驗 §3b 時**一律用 `ed_3b_zh` / `hematuria_3b_en`**，別用帶自由文字的情境——否則 K=0
會讓「AI 沒問風險因子」看起來像 prompt 問題。已寫進 `scripts/e2e_realopenai/README.md`。
