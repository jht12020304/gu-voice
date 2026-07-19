# 問診 × SOAP 改進：實作追蹤

> 建立日期：2026-07-06
> 方案來源：`docs/consultation_soap_improvement_proposal.md`
> 原則：**本地實作 → 單元/整合測試 → 量測「真的有提升」→ 才 push 雲端**。每項記錄改動、測試、before/after 證據與 push 決策。

## 狀態總表

| ID | 改動 | 檔案 | 測試 | 量測到提升? | Push? |
|---|---|---|---|---|---|
| **A2** | **即時 SOAP 路徑接上 `red_flags`（修死代碼安全底線）** | `conversation_handler.py` | ✅ 191 passed | ✅ **e2e：critical→urgency er_now（前為 24h/this_week）** | 🟢 建議推 |
| **A3** | **目錄 severity floor（critical 不被語意層降級）** | `red_flag_detector.py` | ✅ +6 例 | ✅ **e2e：testicular_pain_severe high→critical→abort** | 🟢 建議推 |
| **A1** | **規則層否定感知（修「沒有血尿」誤觸，含長列舉）** | `red_flag_detector.py` | ✅ 21 例 | ✅ **6→0 誤觸、漏報 0；e2e 否定轟炸正常完成** | 🟢 建議推 |
| P0-1 | Supervisor 餵完整 intake（不重問已填項） | `supervisor.py` | ✅ 14 passed | ⚠️ 溫和(1/6→0/6) | 🟢 建議推 |
| P0-2 | Structured Outputs strict schema | — | — | ❌ 基線偏差~0，無 headroom | ✋ 不推(保險非改善) |
| P0-3 | under-triage 主要安全 KPI（量測面） | `research_service.py` | ⬜ | 待排 | ⬜ |

> **方向（使用者拍板）**：量測發現典型問診 schema 偏差~0、SOAP 忠實度~99% → 改走**對抗性壓測找真破綻**。Sonnet 電池（15 場真實對抗問診）找出 A2/A3/A1 三個真失效，皆已修＋測＋e2e 驗證。**A2 影響所有場次**（安全底線先前是死代碼）。
>
> **殘留 gap（未修，誠實）**：
> - **淡化危急偵測 recall**：語意層在**極度淡化**下偵測不穩定（downplay 兩次跑一次 critical、一次 0 偵測）。這與 A3（deterministic floor）正交——沒偵測到就無從 floor。需**依主訴強制篩查**（如年輕男性陰囊腫脹一律 torsion rule-out）或降低偵測門檻，屬**臨床決策**（含「無痛陰囊腫脹是否為必報紅旗」的臨床判定），不宜擅自實作。
> - **SOAP 未標矛盾**：contradiction 情境 SOAP 靜默採信較晚版本、未依自身 prompt 第5條標矛盾。屬正確性，prompt 層待調。

---

## P0-1 Supervisor 餵完整 intake ✅

**問題**：`supervisor.py` 組 `patient_info_str` 時只取 age/gender，但 `analyze_next_step` 早已收到完整 `patient_info`（含 medical_history/medications/allergies/family_history，由 `conversation_handler` `_validate_session` 組好，與 `build_system_prompt` 同源）。Supervisor 因看不到 intake，可能用 `next_focus` 重問 intake 已填的病史/用藥/手術/過敏/家族史。

**改動**：
- `supervisor.py`：抽出純函式 `build_patient_info_str(patient_info)`，把四類 intake 欄位（非空才加）以「（intake 已提供）」標註帶入背景字串；`analyze_next_step` 改呼叫它。
- `SUPERVISOR_SYSTEM_PROMPT` 加護欄：next_focus **不得**要求病患重述標註「intake 已提供」的病史/用藥/過敏/家族史。

**測試**：`tests/unit/pipelines/test_supervisor_intake.py`（5 例：prompt 護欄存在、intake 有值帶入、缺項不塞、空字串/None 略過但「無」保留、age/gender fallback）。既有 `test_supervisor_prompt.py` 9 例無破壞 → **14 passed**。

**量測 before/after**（真 OpenAI gpt-5.4-mini、逗引情境「血尿 + intake 已提供高血壓/糖尿病/攝護腺刮除手術/amlodipine/metformin」、HPI 已大致問完、各 6 次）：
- 舊版（age/gender only、無護欄）：next_focus 重問 intake 已提供項 **1/6**（「請詢問血尿前是否有外傷、運動或手術史」——手術史 intake 已載）。
- 新版（intake + 護欄）：**0/6**。
- → **方向正確、有下降**。惟基線本就低（Conversation 端 prompt 已有 intake 與 no-repeat），絕對效果溫和。腳本：`scratchpad/e2e/ab_p0_1.py`。

**Push 決策**：低風險**一致性/正確性修復**，機制由單元測試證明、A/B 方向正確。屬安全可 push；建議與 P0-2 一起 push（單獨效益溫和）。⬜ 待與 P0-2 綁定後 push。

---

## P0-2 Structured Outputs（strict json_schema）— ⚠️ 先量測基線，發現無 headroom

**實作前基線量測**（40 場真實 batch 的 `uvicorn.log`，`json_object` 寬鬆模式）：
- `urgency invalid` fallback：**0**
- red-flag `urgency escalation`（LLM under-triage 被硬升）：**0**
- SOAP JSON 解析失敗：**0**
- （`output language mismatch`：8 —— 屬語言問題，strict schema 修不了）

→ **gpt-4o + 現行強 prompt 的 schema 偏差率已 ~0**，Structured Outputs 在正常資料上**不會有可量測提升**，價值是「保證/保險」（防罕見或對抗性輸入偏離），非指標改善。依「只 push 真的有提升」原則，**暫不當改善項推**。

## 附帶量測：SOAP 忠實度 headroom（P1-3 價值評估）

VeriFact 式抽查 8 場 zh-TW SOAP（HPI 各欄 + DDx reasoning 共 82 條，對逐字稿判 supported/not_supported，judge=gpt-4o）：
- 未被支持 **3/82 = 3.7%**；但其中 2 條是 judge 誤判（DDx 引用「年齡較大」，年齡在 patient_info/intake、不在逐字稿，SOAP 合法引用——量測只餵逐字稿故誤標）。
- **扣除誤判，真正過度陳述 ≈ 1/82 ≈ 1.2%**（且屬邊界：「無手術背景」）。

→ **現況 SOAP 忠實度 ~99%**，防幻覺 prompt 已很有效；P1-3 在乾淨資料上 headroom 亦低。腳本：`scratchpad/e2e/measure_faithfulness.py`。

**結論**：典型問診上管線已很強（schema 偏差 ~0、忠實度 ~99%）。真正可量測的 headroom 更可能在**對抗性/雜訊輸入**（矛盾、語言混用、超長、答非所問、敵意）——需先壓測找破綻，才有「真的有提升」可證。待與使用者確認方向。

---

## A2 即時 SOAP 路徑接上 `red_flags`（修死代碼安全底線）🟢

**問題（對抗性電池 #1，最高影響）**：`conversation_handler.py` 的即時 SOAP 生成呼叫 `generator.generate(...)` **未傳 `red_flags`**（該參數預設 `None`）→ `_enforce_red_flag_urgency` 開頭 `if not red_flags: return report` → **緊急度安全底線在即時生成路徑恆為 no-op、影響所有場次**。Celery 重生路徑（`report_queue.py:199-221`）則有正確查 `red_flag_alerts` 並傳入。實測（電池）：codeswitch_zh01 有 critical 紅旗在案，SOAP `plan.urgency` 卻是 `this_week`（未升 er_now）。這也解釋先前 40 場 batch「escalation=0」不是不需要，是**根本沒跑**。

**改動**：即時路徑在早期存在性檢查同一 DB session 內查 `RedFlagAlert`（比照 `report_queue`），組 `red_flags` 傳入 `generate(...)`。

**測試**：全 pipelines 191 passed；import sanity OK。

**量測 before/after（e2e，真 OpenAI）**：可靠睪丸扭轉 → critical 紅旗 → **SOAP `plan.urgency=er_now`**（修前同類 critical 場只拿到 LLM 自評的 24h/this_week）。downplay1（run1）critical 場亦 er_now。

**Push 決策**：🟢 **強烈建議推**——這是影響所有場次的安全接線 bug，修好讓 under-triage 安全底線真正生效。

---

## A3 目錄 severity floor（critical 不被語意層降級）🟢

**問題（對抗性電池 #2，安全）**：語意層(LLM)自評 severity 可能低於內建目錄。實測 `testicular_pain_severe`（目錄=critical）被語意層評 **high** → 未達 abort 門檻 → 睪丸扭轉樣症狀**未中止、未升 er_now**＝真正 under-triage。

**改動**（`red_flag_detector.py`）：`_floor_severity_to_catalog`——命中內建 catalogue 的紅旗，severity = max(LLM 自評, 目錄定義)（只升不降，fail-open 方向）。語意層組 alert 時套用 + log 警告。

**測試**：`tests/unit/pipelines/test_red_flag_severity_floor.py`（6 例：critical 目錄 floor 升級、LLM 較高不下修、medium→high、所有 critical canonical 被 high 自評都升回、未知 canonical 不動）。

**量測 before/after（e2e）**：downplay1（run1）+ 可靠睪丸扭轉：`testicular_pain_severe` 自評 high → **floor 升 critical → abort → er_now**（修前停 high、不 abort）。

**Push 決策**：🟢 **建議推**（deterministic、安全方向、只升不降）。⚠️ 注意其效果**取決於語意層先偵測到**紅旗；極度淡化下語意層 recall 不穩（見狀態表殘留 gap），floor 救不了 0 偵測。

---

## A1 規則層否定感知（修「沒有血尿」誤觸紅旗）🟢

**問題**：`red_flag_detector.py:295` 規則層用裸 substring `keyword.lower() in text_lower`，「血尿」在「沒有血尿」裡也命中 → 否定句誤觸 rule_based 紅旗（灌水 red_flag_rate、對護理站發不必要警示）。Fable 總驗收與對抗性分析均確認。

**改動**（`red_flag_detector.py`）：新增 `_keyword_present_non_negated(keyword, text_lower)`——關鍵字**每個出現位置都被否定才抑制**，有任一非否定出現仍觸發（**保留 fail-open**，真紅旗必有非否定提及故不被抑制，語意層仍為第二層）。多語否定線索（zh/en/vi 前置）；轉折詞（但/可是/but）與句尾標點重置否定範圍（「沒有發燒但有血尿」→ 血尿仍觸發）；list 分隔不切斷（「沒有血尿、發燒、腰痛」整串抑制）。**ja/ko 後置否定（血尿はありません）暫未處理，待對抗性電池證據再定。**

**長列舉強化（對抗性電池 e2e 發現的殘留 gap）**：初版 45 字回看對「沒有血尿、發燒、…、尿滯留」這種**極長單一否定列舉**仍漏（尿滯留距句首「沒有」>45 字）。修正：回看放寬至 **120 字**（runaway 上限），並區分 **list 連接詞（、，,以及/及/和/與/或/還有）不重置**（同否定下並列）vs **轉折/接續/追加子句（但/然後/而且…）才重置**。安全考量：規則層有語意層並行後備，可較積極抑制否定誤觸以減少誤 abort。**ja/ko 後置否定（血尿はありません）仍暫未處理**（電池顯示 ja/ko 語言穩定，未在該情境觸發）。

**測試**：`tests/unit/pipelines/test_red_flag_negation.py`（**21 例**：zh/en/vi 否定、轉折/接續/追加重置、極長列舉、list 連接詞不重置、單一非否定仍觸發、句尾切斷、fail-open 預設觸發）。全 pipelines **191 passed**。

**量測 before/after**：
- 真 fallback 規則集（`scratchpad/e2e/measure_negation.py`）：否定轟炸 **OLD 誤觸 6 → NEW 0**、真實提及**漏報 0**、轉折句只觸發血尿。
- **e2e（真 OpenAI）**：否定轟炸病患（含極長列舉 P2 原句）→ **0 rule_based 誤觸、session 正常 completed**（修前該場被 critical 尿滯留誤觸 → 第 1 輪 aborted）。

**Push 決策**：🟢 **建議推**——明確可量測提升（6→0 誤觸、0 漏報、e2e 不再誤 abort）、有測試、fail-open 保留。

---

## P0-3 under-triage 主要安全 KPI

（待對抗性電池回報後，與其他安全性失效一併排。）
