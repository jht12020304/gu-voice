# 問診結構 × SOAP 生成：改進方案（文獻＋GitHub＋程式碼三方對照）

> 建立日期：2026-07-06
> 範圍：`backend/app/pipelines/` 的 `llm_conversation.py`、`supervisor.py`、`soap_generator.py`（＋ `prompts/shared.py`）
> 方法：深讀現況程式碼 → 上網查文獻（23 篇實查論文）與 GitHub（12+ repo）→ 三方對照 → 扣行號的可落地改法
> 前置：本方案建立在已完成的四管線 prompt 鏈升級（`docs/prompt_chain_upgrade_plan.md` Phase 0–4）之上，延續其「**prompt 只決定輸出語意、schema 由驗證器守護**」原則。

---

## 0. 現況速寫（改法都扣這裡）

| 管線 | 檔案 | 現況 | 模型 |
|---|---|---|---|
| Conversation | `llm_conversation.py:61` `build_system_prompt` | 單 agent、prose prompt、每輪注入上一輪 Supervisor `next_focus`（含 no-repeat 護欄 `:226-233`）、串流、每輪一問 | gpt-5.4-mini |
| Supervisor | `supervisor.py:125` `analyze_next_step` | 背景非同步、`json_object` 輸出 `{next_focus, missing_hpi, hpi_completion_percentage}`、self-report 完整度驅動自動結束 | gpt-5.4-mini |
| SOAP | `soap_generator.py:245` `generate` | **單次生成**（`json_object` 非 strict schema `:341`）＋ `_validate_and_fill` `:547` ＋ `_enforce_red_flag_urgency`（deterministic 安全底線 `:436`）＋ ICD-10 白名單 `:359` | gpt-4o |
| Red-flag | `red_flag_detector.py` | 規則層 + 語意層雙層、critical→abort | gpt-4o-mini |

**程式碼盤點出的 6 個結構性弱點**（下文每條都對應改法）：
1. Supervisor 只收 age/gender（`supervisor.py:150-154`），**拿不到完整 intake**（PMH/藥物/過敏）→ 可能重問 intake 已填項。
2. `hpi_completion_percentage` 是**單一 LLM 自評純量**，卻驅動自動結束（安全相關）。
3. Supervisor 分析的是**上一輪**狀態（看不到病患對當前問題的回答）→ 結構性重複。
4. `next_focus` 依 **HPI 固定順序 + 紅旗提醒**選題，**無資訊增益/鑑別診斷價值排序**。
5. SOAP 用 `json_object` 寬鬆模式 → 大量防禦性正規化；enum（urgency/likelihood）靠事後 coerce。
6. SOAP `confidence_score` 為 **LLM 自評**、無 grounding、**無 citation、無 self-critique 忠實度查核**。

---

## 1. 文獻與 GitHub 的關鍵收斂

三方（程式碼弱點 ⇄ 文獻 ⇄ 開源實作）指向兩條主線：

**主線一：問診「選題與停止」應由不確定性/資訊增益驅動，且自評信心不可直接採信。**
- **MediQ**（NeurIPS 2024, arXiv:2406.00922）：直接叫 LLM 自己提問反而降準確率 11–22%；加「棄權模組」估自身信心決定是否再問，+20%。→ 佐證「獨立 Supervisor」架構正確，但**自評門檻不可靠**。
- **LLM 不確定性校準**（medRxiv 2024.06.06.24308399）：LLM 自陳信心普遍**過度自信**，**sample-consistency**（多次採樣一致性）才是最佳指標。
- **UoT**（NeurIPS 2024, arXiv:2402.03271）／**Dr.APP**（arXiv:2502.07143）／**CA-BED**（arXiv:2606.01182）：以**預期資訊增益 / 熵最小化**選下一題，醫療診斷任務 +20~38%。
- **AMIE**（Nature 2025, arXiv:2401.05654 + arXiv:2505.04653）：出題前先產**內部推理鏈**、以**診斷不確定性**做 state-aware 階段轉換。
- **開源**：MEDDxAgent（DDxDriver 三態分派）、MDAgents（複雜度決定協作規模）、Multi-Agent-Medical-Assistant（confidence-based handoff）都把「問更多/升級/停止」當**顯式決策節點**。

**主線二：SOAP 生成應結構化約束 + grounding + 逐句忠實度查核，不可信任「像人寫的就是對的」。**
- **PDQI-9 ambient note 評估**（Frontiers in AI 2025）：LLM note 幻覺率 31% vs 醫師手寫 20%——**連醫師手寫都會幻覺**。
- **VeriFact**（arXiv:2501.16672, 2025）：拆句逐一對病歷判 Supported/Not-Supported/Not-Addressed，92.7% 與醫師一致，**超過醫師間一致率**。
- **醫療幻覺植入測試**（arXiv:2503.05777, 2025）：逐字稿植入假事實，模型**延續杜撰最高 83%**，緩解 prompt 只能減半。
- **ICD-10 準確度落差**（medRxiv 2025.07.30.25330916）：真實資料 GPT-4 exact match **ICD-10 僅 33.9%**，會生成「相近但不精確甚至杜撰」代碼。
- **Ontology-constrained generation**（arXiv:2411.15666）／**evidence-based ICD span**（arXiv:2603.15270）：約束解碼 + 每碼附逐字稿 span。
- **PDSQI-9**（arXiv:2501.08977, 2025）：LLM 病歷專屬 9 維品質量表，特別新增 **Citation（可溯源）**維度。
- **開源**：g-AMIE（分段 S→O→A→P constrained decoding、生成後才產病患訊息）、phlox（ChromaDB **RAG grounding 指引**）、openmed-agent（**ICD-10 做 function-call 查真實術語庫**而非自由生成）。

---

## 2. 修改方案（依「價值/成本」分三批）

### 🟢 批次一：Quick wins（低成本、直接消除已知弱點）

#### P0-1 Supervisor 餵完整 intake（弱點 1）
- **現況**：`supervisor.py:150-154` 只組 `年齡/性別`。Conversation 端 `build_system_prompt` 卻有完整 PMH/藥物/過敏/家族史。
- **改法**：把 `patient_info` 的 `medical_history/medications/allergies/family_history` 與 `intake_data` 一併組進 Supervisor 的 `patient_info_str`（比照 `llm_conversation.py:96-116`）。並在 prompt 明示「intake 已提供者不列入 missing、不要 next_focus 指向」。
- **依據**：MedKGI 顯式狀態追蹤避免冗問；一致性。
- **成本**：**極小**（單一函式的字串組裝）。**建議先做。**

#### P0-2 SOAP／Supervisor 改用 Structured Outputs（strict `json_schema`）（弱點 5）
- **現況**：`soap_generator.py:341` 與 `supervisor.py:192` 都用 `response_format={"type":"json_object"}`（寬鬆）；靠 `_validate_and_fill` `:547-656` 與 `_coerce_urgency` `:508` 事後補救 enum/結構。
- **改法**：改用 `response_format={"type":"json_schema","json_schema":{...,"strict":true}}`，schema 由 Pydantic model 產生（`likelihood ∈ {high,moderate,low}`、`urgency ∈ {er_now,24h,this_week,routine}` 直接列 enum）。gpt-4o 支援 Structured Outputs。**保留** `_enforce_red_flag_urgency` 安全底線與 ICD 白名單（strict schema 管格式、這兩層管臨床安全）。
- **依據**：Ontology-constrained generation（約束解碼杜絕格式外產出）；延續 prompt_chain_upgrade_plan §74「schema 由驗證器守護」原則——Structured Outputs 是其自然下一步。
- **成本**：中（定義 schema + 迴歸測試）。**移除一整類 enum/結構 bug，投報比高。**

#### P0-3 Under-triage 設為主要安全 KPI（弱點對應：評估）
- **現況**：research analytics 已有 urgency 分佈與紅旗率，但驗收未以 under-triage 為紅線。
- **改法**：在既有 `docs/research_analytics.md` 的安全區與驗收準則，明訂**嚴重 under-triage 率**（偵測層 critical/high，但 SOAP `plan.urgency` 低於安全底線的比例）為主要安全 KPI；`_enforce_red_flag_urgency` 已在程式面兜底，此處是**量測與迴歸**面。
- **依據**：triage 安全文獻（arXiv:2604.00215、Scand J Prim Health Care 2026）主張以 severe under-triage rate 而非整體準確率為安全指標；呼應既有 E7 保守預設。
- **成本**：小（一個聚合指標 + 驗收條目）。

---

### 🟡 批次二：核心強化（中成本、顯著提升安全與品質）

#### P1-1 停止準則：自評純量 → 結構化覆蓋 + 顯式棄權判斷（弱點 2）
- **現況**：Supervisor 回單一 `hpi_completion_percentage`，`_should_auto_conclude` 以門檻判斷結束。
- **改法**（兩選一或並行）：
  - (a) **結構化覆蓋**：Supervisor 改輸出**每欄狀態** `{field: covered|patient_unknown|missing}`（10 欄 + 紅旗候選），完整度在 **Python 端 deterministic 計算**（可稽核、也讓 research 頁 HPI 完整度更可靠）。
  - (b) **顯式棄權/停止決策**（MediQ abstention）：另出 `ready_to_conclude: bool` + 理由，且**硬性 gate 在「所有 active 紅旗候選已 rule-in/out」**才允許結束。
- **依據**：MediQ（+20%）、校準文獻（自評不可信）、DDO（ask-vs-stop 顯式決策）。
- **成本**：中（Supervisor schema + 消費端門檻邏輯 + 測試）。**安全相關，優先。**

#### P1-2 next_focus：固定順序 → 資訊增益 / 紅旗優先排序（弱點 4）
- **現況**：`supervisor.py` prompt 要求「某欄未完成就繼續問該欄、完成才移下一欄」＝固定順序。
- **改法**：改指示 Supervisor 從**未覆蓋候選**中，優先選「**最可能改變紅旗判斷或 urgency 分級**」的問題（而非永遠先 onset 後 severity）；可要求它先產一小段候選比較推理再給單一 `next_focus`（AMIE chain-of-reasoning，但**留在背景 Supervisor、不拖慢即時 Conversation**）。
- **依據**：UoT / CA-BED / Dr.APP（資訊增益/熵最小化 +20~38%）、AMIE、MEDDxAgent DDxDriver。
- **成本**：中（Supervisor prompt 重寫；先做輕量版「紅旗/urgency 優先」再考慮完整 EIG）。

#### P1-3 SOAP 忠實度查核 pass（VeriFact 式）（弱點 6）
- **現況**：`soap_generator.generate` 單次生成即回，**無驗證**；防幻覺純靠 prompt `:47-55`。
- **改法**：生成後加一道 verifier（同模型第二次呼叫，SOAP 為**非同步後生成、可容忍額外延遲**）：把 HPI 各欄、每條 `differential_diagnoses.reasoning`、紅旗陳述**逐句對逐字稿**判 `Supported / Not-Supported / Not-Addressed`；Not-Supported 的欄位**標記**（存 metadata + 前端 badge 供醫師快核），並據以下修 confidence。
- **依據**：VeriFact（92.7% 一致）、幻覺植入（延續杜撰達 83%）、PDSQI-9 Citation、g-AMIE guardrail。
- **成本**：中高（多一次呼叫 + schema + 前端 badge）。**安全相關。**

#### P1-4 confidence_score：LLM 自評 → grounded/一致性（弱點 6）
- **現況**：`confidence_score` 由 LLM 自吐（`:110-113`）。
- **改法**：改由 Python 依「結構化 HPI 覆蓋率（P1-1）＋ DDx 是否有逐字稿佐證（P1-3）＋忠實度 pass 通過率」**計算**；或用 **sample-consistency**（少數幾次採樣的 DDx/urgency 一致度）。取代或並列 LLM 自評，讓 research 頁的 `ai_confidence` 才有意義。
- **依據**：校準文獻（sample-consistency > 自陳信心）。
- **成本**：中（綁 P1-1/P1-3 一起做最省）。

#### P1-5 ICD-10：自由生成 → RAG 候選約束 + span（弱點 6 / 準確度）
- **現況**：LLM 自由吐 `icd10_codes` → `validate_icd10_codes` 白名單 + symptom 對映（已是不錯的防禦層）。
- **改法**：升級為**先以 symptom_id/DDx 檢索官方 ICD-10 候選集合**，讓 LLM 只能從候選挑（function-calling / structured candidates），並要求**每碼附逐字稿 span**；罕見/低頻碼標記待人工複核。既有白名單是此設計的部分版本，往「檢索候選 + span」演進。
- **依據**：ICD-10 準確度落差（真實資料 exact match <50%）、evidence-based ICD span、openmed-agent（ICD 做 tool 查詢）、ontology-constrained。
- **成本**：中高（需 ICD-10 候選來源；可先用現有 `icd10_symptom_map` 擴充為候選庫）。

---

### 🔵 批次三：進階/基礎建設（較高成本、長期品質）

#### P2-1 SOAP 兩階段：先 grounded 抽事實 → 再寫 note
- **改法**：Stage 1 從逐字稿抽**帶 span 的結構化事實**；Stage 2 只依「抽出的事實」寫 SOAP（不再看原始逐字稿）→ 從源頭 grounding。可與 P1-3/P1-5 共用 span 基礎設施。
- **依據**：g-AMIE 分段 constrained decoding、evidence-based ICD span。
- **成本**：高（兩次呼叫 + 事實中介層）。SOAP 非同步、延遲可接受。

#### P2-2 Assessment/Plan 的 RAG grounding（指引庫）
- **改法**：以向量庫（如 phlox 的 ChromaDB 模式）檢索泌尿科臨床指引，餵給 Assessment/Plan 生成，降低鑑別診斷與處置建議的幻覺。
- **依據**：phlox、meditron 指引語料。
- **成本**：高（需策展指引庫 + RAG 基礎設施）。

#### P2-3 評估基礎建設（支撐上述所有改動安全上線）
- **固定假名化逐字稿夾具 + PDQI-9/PDSQI-9 rubric**（OpenScribe/phlox fixture harness 模式）：每次改 prompt/模型都跑同一組 case 比對品質。
- **幻覺植入迴歸集**（arXiv:2503.05777 方法）：逐字稿故意植入假 vitals/症狀，驗 SOAP 不延續杜撰。
- **Patient-simulator 壓力測試**：**已有 `scratchpad/e2e/batch_runner.py`**（40 場5語言真實問診批次）可直接擴為合成情境覆蓋器（Awesome-LLM-Patient-Simulators、MedAgentSim experience replay）。
- **QUEST 五原則 + 情境化 OSCE 盲測**（npj Digital Medicine 2024、g-AMIE）：人評骨架。
- **成本**：中（大部分是把既有 E2E/研究頁指標系統化為固定迴歸集）。

---

## 3. 建議落地順序

```
第 1 步（本週可做，低風險）：P0-1 Supervisor 餵 intake、P0-2 Structured Outputs、P0-3 under-triage KPI
第 2 步（核心安全，綁一起做）：P1-1 結構化停止 + P1-4 grounded confidence + P1-3 忠實度 pass（共用 span/覆蓋基礎）
第 3 步（品質提升）：P1-2 資訊增益選題、P1-5 ICD RAG 候選
第 4 步（長期）：P2-1 兩階段生成、P2-2 指引 RAG、P2-3 評估迴歸基礎建設
```

**設計不變式（沿用既有原則，改動時勿破壞）**：
- 每輪一問、病患友善語氣（Dr.APP 證實與結構化提問不衝突）。
- 紅旗 fail-open、`_enforce_red_flag_urgency` 只升不降的安全底線**恆保留**（Structured Outputs 管格式、它管臨床安全）。
- 多語一致：schema/enum 用 snake_case、輸出語言由語言規則鎖定（勿因改 schema 破壞 ja/ko/vi 對齊）。
- prompt 只決定語意、硬約束交給 schema/驗證器（本方案把「驗證器」升級為 Structured Outputs + 忠實度 pass）。

---

## 4. 文獻與 repo 索引

**問診結構**：AMIE（arXiv:2401.05654 / Nature 2025；arXiv:2505.04653）、MediQ（arXiv:2406.00922, NeurIPS 2024）、UoT（arXiv:2402.03271, NeurIPS 2024）、CA-BED（arXiv:2606.01182）、Dr.APP（arXiv:2502.07143）、MedKGI（arXiv:2512.24181）、DDO（arXiv:2505.18630）、MIND（arXiv:2603.03677）、LLM 校準（medRxiv 2024.06.06.24308399）、症狀檢查器紅旗召回（BMC HSR 2025）。
**SOAP/note**：PDQI-9 ambient（Frontiers in AI 2025）、PDSQI-9（arXiv:2501.08977）、VeriFact（arXiv:2501.16672）、Ontology-constrained（arXiv:2411.15666）、ICD-10 review（medRxiv 2025.07.30.25330916）、evidence-based ICD span（arXiv:2603.15270）、triage 安全（arXiv:2604.00215、Scand J Prim Health Care 2026）、醫療幻覺（arXiv:2503.05777）、ambient scribe RCT（NEJM AI 2025）、多平台 scribe 品質（Mayo Clin Proc Dig Health 2025）、QUEST（npj Digital Medicine 2024）。
**GitHub**：meddxagent、MDAgents、MedAgentSim、Multi-Agent-Medical-Assistant、phlox、OpenScribe、openmed-agent、ai-medical-chatbot、Awesome-LLM-Patient-Simulators、meditron、MedLLMsPracticalGuide；設計參考 g-AMIE（arXiv:2507.15743，無公開 repo）。

> ⚠️ 引用注意：核心建議由**已確立文獻**支撐（AMIE 2024/2025、MediQ/UoT NeurIPS 2024、VeriFact 2025、PDQI-9/PDSQI-9、ICD-10 review）。部分 2026 年 arXiv 條目為研究 agent 網路查得、較前沿，**正式投稿前請再獨立覆核** DOI/arXiv 有效性與數據。
