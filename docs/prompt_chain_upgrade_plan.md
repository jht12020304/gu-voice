# Prompt 鏈完整更新規劃

> 目標：修復 Conversation → Supervisor → SOAP / Red Flag 四個 pipeline 之間的資訊流斷鏈，讓四份 prompt 共享一致的 ontology、欄位語彙、紅旗知識與模型能力配置。
>
> 建立日期：2026-04-15
> 適用範圍：`backend/app/pipelines/` 下的四個 LLM pipeline
> 前置狀態：已完成 `feat: upgrade conversation LLM to gpt-5.4-mini` 與 `feat: rewrite SOAP and red-flag prompts with urology-specific guidance`

---

## 執行進度

| Phase | 內容 | 狀態 | Commit | 備註 |
|---|---|---|---|---|
| 0 | 共用常數 `shared.py` + 單元測試 | ✅ 完成 | `41c4882` | 16/16 tests passing |
| 1 | Supervisor 升級 gpt-5.4 + 單問題約束 | ✅ 完成 | `08ccbb3` | 22/22 tests passing;修 P0-A、P1-C、P2-F |
| 3 | Red Flag detector 改吃共用常數 | ✅ 完成 | _pending_ | 29/29 tests passing;修 P2-E |
| 2 | Conversation 擴充 HPI 10 欄 + 補問 FH/SH/RoS | 🚧 進行中 | — | 修 P0-B、P1-D |
| 4 | SOAP confidence_score 不扣 FH/SH/RoS 分 | ⬜ 待做 | — | P0-B 收尾 |

執行順序調整為 **0 → 1 → 3 → 2 → 4**:Phase 3(red flag)很單純且獨立,先做完後 Phase 2 再 consume 新的 `render_red_flags_for_conversation`。

---

## 0. 背景與現況

### 四個 LLM Pipeline
| # | Pipeline | 檔案 | 模型 | 觸發時機 |
|---|---|---|---|---|
| 1 | Conversation | `llm_conversation.py:143` | `gpt-5.4-mini` | 每輪病患語音後即時生成 AI 回應 |
| 2 | Supervisor | `supervisor.py:21` | `gpt-4o` (default) | 背景每 N 輪分析整段對話,寫 Redis |
| 3 | SOAP Generator | `soap_generator.py:20` | `gpt-4o` | 對話結束後一次性產出報告 |
| 4 | Red Flag Detector | `red_flag_detector.py:24` | `gpt-4o-mini` | 每輪 user text 並行規則+語意雙層偵測 |

### 資料流
```
病患說話
   ↓
[1] Conversation LLM ──並行── [4] Red Flag Detector
   ↓                                  ↓
AI 回應                          alerts 推送醫師
   ↓
[2] Supervisor(背景)
   └── next_focus 寫 Redis ──注入──▶ [1] 下一輪 system prompt
   ↓
... 對話循環 ...
   ↓
對話結束
   ↓
[3] SOAP Generator (整段 transcript → 結構化報告)
```

---

## 1. 斷鏈問題彙總

| ID | 嚴重度 | 問題 | 影響範圍 |
|---|---|---|---|
| **P0-A** | 高 | Supervisor `next_focus` 可能包含多個問題,違反 Conversation「一次只問一個問題」硬性規則 | 對話節奏崩壞、AI 自我矛盾 |
| **P0-B** | 高 | Conversation 從不追問 `family_history` / `social_history` / `review_of_systems`,但 SOAP schema 有這 3 個欄位 | SOAP 這 3 欄永遠 null,`confidence_score` 自評被拖累 |
| **P1-C** | 中 | Supervisor 模型停在 `gpt-4o`,Conversation 已升 `gpt-5.4-mini`,督導能力反而追不上被督導者 | 背景臨床推理品質有限 |
| **P1-D** | 中 | Conversation 的 HPI 為 9 步(合併 Aggravating/Relieving),SOAP 的 `hpi` 為 10 欄(拆成兩欄) | 不壞,但語意對齊不精確 |
| **P2-E** | 低 | Conversation prompt 的 `RED_FLAGS_BY_COMPLAINT` 與 Red Flag pipeline 的紅旗清單各自維護,漂移風險 | 長期知識庫不一致 |
| **P2-F** | 低 | `supervisor.py:56` fallback 字串 `"gpt-5.4"` 與 `config.py:103` default `"gpt-4o"` 不一致 | 誤導後續維護者 |
| **P2-G** | 低 | Red Flag `title` 對齊清單(剛加上)寫死於 prompt,若 DB 新增 custom rule 會漂移 | 合併去重不完整 |

---

## 2. 設計原則

執行修改前先確立共通原則,避免改到後面失焦:

1. **單一知識源 (Single Source of Truth)**:紅旗清單、HPI 框架、SOAP 欄位定義應各自只有一處 Python 定義,prompt 透過字串注入。
2. **Prompt 契約最小化**:prompt 只決定**輸出語意**,schema 硬性限制由 Python 驗證器與 Pydantic model 守護。
3. **Pipeline 間共享 ontology**:HPI 九步、紅旗分級、問題類型等概念應在所有四個 prompt 中用**相同名詞與順序**。
4. **能力梯度合理**:Supervisor ≥ SOAP > Conversation > Red Flag(推理深度排序)。
5. **降階失敗優先於誤判**:所有 LLM 輸出都要有 Python 端的 fallback 與 validator。

---

## 3. 共用常數模組(新檔)

所有修改都建立在這個基礎上,**第一步必做**。

### 3.1 新增 `backend/app/pipelines/prompts/shared.py`

```python
"""
跨 pipeline 共用的 prompt 常數與 ontology。

這是 Single Source of Truth — conversation / supervisor / soap / red_flag
四個 pipeline 都從這裡 import,確保:
1. HPI 步驟命名與順序一致
2. 紅旗分級與 title 命名一致
3. SOAP schema 欄位清單一致(給 prompt 內嵌用)
"""

# ── HPI 九步框架 ──────────────────────────────────────
# conversation / supervisor 的 HPI 收集目標,與 SOAP hpi 10 欄位對應
HPI_STEPS: list[dict[str, str]] = [
    {"id": "onset",               "zh": "Onset(發生時間)",       "desc": "何時開始?突然還是漸進式?"},
    {"id": "location",            "zh": "Location(位置)",        "desc": "確切的不適部位?"},
    {"id": "duration",            "zh": "Duration(持續時間)",    "desc": "持續多久?持續性還是間歇性?"},
    {"id": "characteristics",     "zh": "Characteristics(特徵)", "desc": "症狀的性質(如疼痛的類型)?"},
    {"id": "severity",            "zh": "Severity(嚴重度)",     "desc": "1-10 分或描述性評估"},
    {"id": "aggravating_factors", "zh": "Aggravating(加重因素)", "desc": "什麼會使症狀加重?"},
    {"id": "relieving_factors",   "zh": "Relieving(緩解因素)",   "desc": "什麼會使症狀緩解?"},
    {"id": "associated_symptoms", "zh": "Associated(伴隨症狀)",  "desc": "其他伴隨症狀?"},
    {"id": "timing",              "zh": "Timing(時間模式)",     "desc": "什麼時候特別明顯?(夜間、排尿時等)"},
    {"id": "context",             "zh": "Context(背景)",         "desc": "症狀發生的背景脈絡?"},
]

def render_hpi_checklist() -> str:
    """把 HPI 步驟渲染成 prompt 可讀的條列清單"""
    return "\n".join(
        f"{i + 1}. **{step['zh']}**:{step['desc']}"
        for i, step in enumerate(HPI_STEPS)
    )

HPI_FIELD_IDS: list[str] = [step["id"] for step in HPI_STEPS]  # 給 SOAP validator 用


# ── 紅旗統一清單 ──────────────────────────────────────
# 供 red_flag_detector、llm_conversation、soap_generator 共用
# title 欄位必須與 fallback_rules 的 name 對齊(影響語意/規則去重合併)
URO_RED_FLAGS: list[dict] = [
    {
        "title": "急性尿滯留",
        "severity": "critical",
        "description": "病患可能出現急性尿滯留,需要緊急處理",
        "triggers": ["無法排尿", "完全排不出", "尿滯留", "解不出小便"],
        "related_complaints": ["排尿困難", "頻尿"],
    },
    {
        "title": "大量血尿",
        "severity": "critical",
        "description": "嚴重血尿,需評估出血原因與血流動力學",
        "triggers": ["大量血尿", "血塊", "整個都是血"],
        "related_complaints": ["血尿"],
    },
    {
        "title": "睪丸劇痛",
        "severity": "critical",
        "description": "可能為睪丸扭轉,6 小時內處理以避免壞死",
        "triggers": ["睪丸劇痛", "突然睪丸痛", "蛋蛋很痛"],
        "related_complaints": ["睪丸疼痛"],
    },
    {
        "title": "尿路敗血症",
        "severity": "critical",
        "description": "尿路感染合併全身性感染徵象,可能為尿路敗血症",
        "triggers": ["高燒", "寒顫", "意識不清", "發燒加排尿痛"],
        "related_complaints": ["頻尿", "排尿困難", "血尿"],
    },
    {
        "title": "肉眼血尿",
        "severity": "high",
        "description": "肉眼可見血尿,需進一步檢查排除惡性腫瘤",
        "triggers": ["尿是紅色", "紅色的尿", "尿裡有血"],
        "related_complaints": ["血尿"],
    },
    {
        "title": "腎絞痛合併發燒",
        "severity": "high",
        "description": "腎結石合併感染,可能需要緊急引流",
        "triggers": ["腰痛加發燒", "側腹痛加燒"],
        "related_complaints": ["腰痛"],
    },
    {
        "title": "不明原因體重下降",
        "severity": "high",
        "description": "不明原因體重急速下降,需排除惡性腫瘤",
        "triggers": ["體重下降", "變瘦", "體重減輕"],
        "related_complaints": ["血尿", "腰痛"],
    },
    # 新增:神經學紅旗
    {
        "title": "疑似馬尾症候群",
        "severity": "critical",
        "description": "會陰麻木、下肢無力合併尿失禁/滯留,疑似脊髓壓迫",
        "triggers": ["會陰麻木", "下肢無力", "新發尿失禁", "背痛加麻木"],
        "related_complaints": ["排尿困難", "腰痛"],
    },
]

def get_red_flags_for_complaint(chief_complaint: str) -> list[dict]:
    """依主訴篩出相關紅旗;若無匹配回全部"""
    matches = [
        f for f in URO_RED_FLAGS
        if any(cc in chief_complaint for cc in f["related_complaints"])
    ]
    return matches if matches else URO_RED_FLAGS

def render_red_flag_titles_for_prompt() -> str:
    """產生 red_flag prompt 中『title 命名對齊』段落"""
    return "\n".join(f"- 「{f['title']}」" for f in URO_RED_FLAGS)

def render_red_flags_by_severity() -> str:
    """產生三層臨床情境清單(給 red_flag prompt)"""
    by_sev = {"critical": [], "high": [], "medium": []}
    for f in URO_RED_FLAGS:
        by_sev.setdefault(f["severity"], []).append(f)
    lines = []
    for sev, label in [("critical", "Critical(危急)"), ("high", "High(嚴重)"), ("medium", "Medium(中等)")]:
        if by_sev[sev]:
            lines.append(f"\n### {label}")
            for f in by_sev[sev]:
                lines.append(f"- **{f['title']}**:{f['description']}")
    return "\n".join(lines)

def render_red_flags_for_conversation(chief_complaint: str) -> str:
    """給 conversation prompt 的紅旗提醒(依主訴過濾)"""
    flags = get_red_flags_for_complaint(chief_complaint)
    return "\n".join(f"- {f['title']}:{f['description']}" for f in flags)


# ── 單一問題約束(跨 pipeline 共用) ─────────────────
SINGLE_QUESTION_RULE = """【每輪輸出的硬性限制】
- **一次只追問一個問題**,絕對不可在同一輪塞多個問題讓病患一次回答。
- 每次回覆最多 2 句話,保持口語、簡潔。
- 不使用 markdown、不用 bullet、不用條列。
"""
```

### 3.2 新增 `RedFlagRule` table 的 migration(選配 P2-G)

目的:讓紅旗規則真正從 DB 讀,而不是 hardcode 在 Python + prompt。
延後至 P2 階段再做,先用 `URO_RED_FLAGS` 常數過渡。

---

## 4. 修改計畫(依優先級分階段)

### Phase 0:前置重構(commit 1)

**目標**:建立共用常數,不動任何現有行為。

- [ ] 新增 `backend/app/pipelines/prompts/__init__.py`(空檔)
- [ ] 新增 `backend/app/pipelines/prompts/shared.py`(上述第 3.1 節內容)
- [ ] 單元測試 `backend/tests/pipelines/test_shared_prompts.py`
  - `test_render_hpi_checklist_has_10_steps`
  - `test_render_red_flag_titles_contains_all`
  - `test_get_red_flags_for_complaint_filter_by_haematuria`
  - `test_render_red_flags_by_severity_returns_three_buckets`
- [ ] 跑 `pytest backend/tests/pipelines/test_shared_prompts.py` 通過

**Commit message**:
```
refactor: extract shared prompt constants (HPI steps, red flags)

Add app/pipelines/prompts/shared.py as the single source of truth
for the HPI framework, urology red-flag catalogue, and cross-
pipeline output rules. No behaviour change yet — downstream
pipelines will migrate in follow-up commits.
```

---

### Phase 1:修 P0-A(Supervisor 單問題約束)+ P1-C(Supervisor 模型升級)(commit 2)

**目標**:讓 supervisor 產出的 `next_focus` 符合 conversation 的一問一答規則,並升級到 gpt-5.4 以取得更好的臨床推理。

#### 4.1.1 修改 `backend/app/core/config.py`

```diff
-    OPENAI_MODEL_SUPERVISOR: str = "gpt-4o"
+    OPENAI_MODEL_SUPERVISOR: str = "gpt-5.4"
+    # 背景督導任務,不影響對話延遲;medium reasoning 讓它做真正的臨床推理。
+    # none  → 無推理(退回 chat completions 基本模式)
+    # low   → 輕量推理
+    # medium→ 適合督導類任務(預設)
+    # high  → 極深推理,延遲較長
+    OPENAI_REASONING_EFFORT_SUPERVISOR: str = "medium"
```

#### 4.1.2 修改 `backend/.env.example`

```diff
-OPENAI_MODEL_CONVERSATION=gpt-5.4-mini
+OPENAI_MODEL_CONVERSATION=gpt-5.4-mini
+OPENAI_MODEL_SUPERVISOR=gpt-5.4
+OPENAI_REASONING_EFFORT_SUPERVISOR=medium
```

#### 4.1.3 修改 `backend/app/pipelines/supervisor.py`

1. 移除 fallback 字串 `"gpt-5.4"` 的誤導
2. 在 system prompt 加上「單一問題」硬性約束
3. 呼叫 API 時帶 `reasoning_effort`

```python
from app.pipelines.prompts.shared import HPI_STEPS, SINGLE_QUESTION_RULE, render_hpi_checklist

SUPERVISOR_SYSTEM_PROMPT = f"""你是一位泌尿科資深主治醫師(Supervisor)。你的任務是在背景監督你的 AI 實習醫師與病患的問診過程。

## 背景資訊
- 病患基本資訊:{{patient_info_str}}
- 主訴:{{chief_complaint}}

## 實習醫師的問診任務(HPI 九步框架)
{render_hpi_checklist()}

## 你的任務
閱讀下方的【當前對話紀錄】,評估實習醫師目前已經收集到哪些 HPI 資訊,還有哪些「關鍵且尚未收集」的資訊。
請給出明確指令告訴實習醫師「下一步具體該問什麼」,讓他在下一句話中執行。

## next_focus 書寫的硬性規則(極重要)
- **只能是一個問題**,不可把多個問題塞在同一條 next_focus 裡讓病患一次回答。
- 必須是具體、可立即執行的指示,而非抽象建議(❌「請更深入詢問疼痛」→ ✅「請詢問疼痛是否會放射到鼠蹊部」)。
- 若目前 HPI 某一項已達成目標,才移動到下一項。
- 若實習醫師問錯方向,next_focus 要明確拉回正確方向。
- 最大長度 60 個中文字以內。

{SINGLE_QUESTION_RULE}

## 回覆格式
請嚴格以下列 JSON 回覆,不可包含其餘文字:

{{{{
  "next_focus": "string(單一具體指令,最多 60 字)",
  "missing_hpi": ["string(還缺少的 HPI 項目 id,例如 'severity', 'associated_symptoms')"],
  "hpi_completion_percentage": 0
}}}}

## missing_hpi 的合法值
必須使用以下 id 字串(snake_case):onset、location、duration、characteristics、severity、aggravating_factors、relieving_factors、associated_symptoms、timing、context
"""

class SupervisorEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL_SUPERVISOR  # gpt-5.4
        self._reasoning_effort = settings.OPENAI_REASONING_EFFORT_SUPERVISOR  # medium
        # gpt-5.4 + reasoning_effort != "none" → 不能帶 temperature
        logger.info(
            "SupervisorEngine 初始化 | model=%s, reasoning_effort=%s",
            self._model, self._reasoning_effort,
        )

    async def analyze_next_step(self, ...):
        ...
        create_kwargs = {
            "model": self._model,
            "messages": [...],
            "response_format": {"type": "json_object"},
        }
        if self._reasoning_effort != "none":
            create_kwargs["reasoning_effort"] = self._reasoning_effort
        else:
            create_kwargs["temperature"] = 0.2
        response = await self._client.chat.completions.create(**create_kwargs)
```

#### 4.1.4 驗證
- 單元測試 `test_supervisor_prompt_renders_hpi_from_shared`:斷言 HPI_STEPS 的 10 項都在 SUPERVISOR_SYSTEM_PROMPT 中。
- 手動測試:跑一個 mock session,檢查 Redis `session:<id>:supervisor_guidance` 的 `next_focus` 確實只有一個問題。

**Commit message**:
```
feat: upgrade supervisor to gpt-5.4 with medium reasoning effort

Also enforce "next_focus must be a single question" in the
supervisor prompt to prevent it from issuing multi-question
directives that would break the conversation engine's
"one question at a time" rule. missing_hpi now uses the
shared HPI step ids for downstream analytics.
```

---

### Phase 2:修 P0-B(Conversation 補問 FH/SH/RoS)+ P1-D(HPI 10 欄對齊)(commit 3)

**目標**:讓 conversation 能在 HPI 完整度高時補問社會/家族史/系統回顧,填滿 SOAP 需要的欄位。

#### 4.2.1 修改 `backend/app/pipelines/llm_conversation.py`

改用 shared 常數,並擴充問診任務到 10 欄 + 條件式補問:

```python
from app.pipelines.prompts.shared import (
    HPI_STEPS,
    render_hpi_checklist,
    render_red_flags_for_conversation,
    SINGLE_QUESTION_RULE,
)

def build_system_prompt(self, chief_complaint: str, patient_info: dict[str, Any]) -> str:
    ...
    hpi_section = render_hpi_checklist()
    red_flags_section = render_red_flags_for_conversation(chief_complaint)
    
    system_prompt = f"""你是一位專業的泌尿科 AI 問診助手,負責協助進行初步問診。

## 角色定位
- 你是泌尿科門診的 AI 問診助手
- 使用繁體中文與病患溝通
- 語氣親切、專業且具同理心

## 病患資訊
{patient_section}

## 主訴
{chief_complaint}

## 主要問診任務(HPI 十欄框架)
根據病患的主訴「{chief_complaint}」,依序收集:
{hpi_section}

## 次要補問(HPI 完整度 > 70% 後才進入)
當上述 HPI 十欄已大致問完,請視對話狀況補問下列資訊(每次補問仍只問一題):
- 過往泌尿科相關疾病或手術史
- 目前服用中的藥物(特別是抗凝血劑、利尿劑、攝護腺藥物)
- 已知藥物過敏
- 家族是否有泌尿道癌症、腎結石或攝護腺疾病史
- 相關生活習慣(僅限與主訴有關聯時,例如飲水量、咖啡因、吸菸)
- 其他系統的不適(review of systems,僅在臨床相關時補問)

若病患於 intake 表單已提供上述資訊,則不需重複詢問,直接進入 HPI。

## 問診準則
- 避免過度使用醫學專業術語
- 若病患的回答不夠明確,可進行追問以釐清
- 適時表達關心與同理心
- 不做診斷或治療建議,僅進行症狀收集

{SINGLE_QUESTION_RULE}
- 不說「好的」「了解」等空洞開場白,直接進入問題
- 若偵測紅旗,在句尾加上「這個症狀需要盡速就醫,請不要等待。」

## 紅旗症狀注意
請特別留意以下可能需要緊急處理的紅旗症狀:
{red_flags_section}

## 回覆格式
- 使用自然、口語化的繁體中文
- 每次回覆簡潔明瞭,通常 1-3 句話
- 不使用 markdown 格式或特殊符號
"""
    return system_prompt
```

#### 4.2.2 驗證
- 單元測試:斷言 system_prompt 中包含所有 10 個 HPI 步驟名稱與 "次要補問" 段落。
- 手動測試:跑一個血尿 session,確認 HPI 完成後 AI 會開始問 family_history 等。

**Commit message**:
```
feat: expand conversation prompt to 10-step HPI + social history

Previously the conversation only collected the 9-step HPI
(merging aggravating & relieving factors), leaving the SOAP
generator with permanent nulls for family_history,
social_history, and review_of_systems. Now:

1. HPI is sourced from shared.HPI_STEPS (10 items) so it
   matches the SOAP hpi schema exactly.
2. After HPI >= 70% complete, the agent enters a "secondary
   intake" mode that asks one follow-up per turn about
   family history, relevant social history, and RoS.
3. Red-flag reminders are now pulled from the shared
   URO_RED_FLAGS catalogue via
   render_red_flags_for_conversation(), eliminating the
   duplicate maintenance burden with the red-flag pipeline.
```

---

### Phase 3:修 P2-E(紅旗知識去重)(commit 4)

**目標**:讓 red_flag_detector 的 prompt 與 fallback rules 都從 shared.URO_RED_FLAGS 產生,DB 規則仍保留主導地位。

#### 4.3.1 修改 `backend/app/pipelines/red_flag_detector.py`

```python
from app.pipelines.prompts.shared import (
    URO_RED_FLAGS,
    render_red_flag_titles_for_prompt,
    render_red_flags_by_severity,
)

_SEMANTIC_SYSTEM_PROMPT = f"""你是具急診與泌尿科分流經驗的臨床安全偵測助理,任務是從病患對話中辨識需要高度警覺的紅旗症狀。

## 你的角色
...(原本的角色定位保留)...

## 需重點辨識的泌尿科高風險情境
{render_red_flags_by_severity()}

## title 命名對齊(重要,影響系統去重)
本系統的規則層會先偵測以下內建紅旗;若你的語意判斷落在同一類情境,**請使用完全相同的 title 名稱**:
{render_red_flag_titles_for_prompt()}

...(原本的判斷原則、輸出格式、硬性限制全部保留)...
"""

@staticmethod
def _get_fallback_rules() -> list[dict[str, Any]]:
    """從 shared.URO_RED_FLAGS 產生 fallback 規則(DB 不可用時)"""
    fallback = []
    for f in URO_RED_FLAGS:
        fallback.append({
            "id": None,
            "name": f["title"],
            "severity": f["severity"],
            "category": f["title"],  # 暫用 title 當 category
            "keywords": f["triggers"],
            "regex_pattern": None,   # 純關鍵字,不配 regex
            "description": f["description"],
            "suggested_actions": ["立即通知醫師", "評估是否需要急診處置"],
        })
    return fallback
```

#### 4.3.2 驗證
- 單元測試:斷言 `_get_fallback_rules()` 與 `URO_RED_FLAGS` 的長度相同、title 對齊。
- 跑現有的 red_flag 相關測試,確認規則層偵測結果不變。

**Commit message**:
```
refactor: red-flag detector now pulls from shared catalogue

Both the LLM prompt's severity tables/title alignment list
and the Python fallback_rules are now generated from
shared.URO_RED_FLAGS, eliminating the drift risk between
the two knowledge bases. DB-stored rules still take
precedence when available.
```

---

### Phase 4:修 P1-B 剩餘部分(SOAP prompt 不再扣分)(commit 5)

**目標**:SOAP prompt 明確告訴 LLM,若 FH/SH/RoS 等欄位確實沒收集到是正常的,不應以此壓低 confidence_score。

#### 4.4.1 修改 `backend/app/pipelines/soap_generator.py`

在「頂層欄位」段落的 `confidence_score` 說明旁加一條:

```
- confidence_score:0.0-1.0 浮點數,反映對話對 **HPI 十欄與鑑別診斷依據** 的完整度。
  family_history / social_history / review_of_systems 若未於對話收集到,屬於正常情況
  (由醫師現場補問),不應以此壓低分數。主要扣分項為:HPI 缺漏、主訴模糊、鑑別診斷
  無法合理推論。
```

#### 4.4.2 驗證
- 手動檢查:同一段 transcript 在修改前後,confidence_score 是否明顯提升(理論上應該)。

**Commit message**:
```
fix: SOAP confidence_score should not penalise missing FH/SH/RoS

The SOAP prompt now explicitly tells the model that
family/social/review-of-systems fields being null is a
normal outcome (those are collected by the physician in
person) and should not reduce the confidence self-assessment.
Scoring is now anchored to HPI completeness and differential
diagnosis defensibility.
```

---

### Phase 5:驗證與監控(無 commit,操作步驟)

**目標**:在 production 確認四個 pipeline 的行為符合預期。

#### 5.1 E2E 測試腳本(跑在 staging / local)

建立 `backend/tests/e2e/test_prompt_chain.py`:

```python
async def test_full_prompt_chain_blood_in_urine():
    """
    模擬一個血尿病人完整走完四個 pipeline:
    1. Conversation 收集 HPI 十欄 + 補問 FH/SH
    2. Supervisor 每 3 輪產生 next_focus,且一定只有一個問題
    3. Red Flag 在病患提到「尿是紅色的、有血塊」時觸發 critical
    4. SOAP 生成後:
       - hpi 十欄有 >= 8 個非 null
       - differential_diagnoses 至少 3 項
       - confidence_score >= 0.7
       - icd10_codes 包含 R31.x
    """
    ...
```

#### 5.2 監控指標(加 Prometheus / Sentry breadcrumb)

| 指標 | 目標值 |
|---|---|
| `supervisor.next_focus_question_count` | 幾乎 100% 為 1 |
| `soap.confidence_score.avg` | 升級後應從 ~0.6 提升到 ~0.8 |
| `soap.hpi_fields_filled_count.avg` | >= 8/10 |
| `red_flag.rule_semantic_merge_rate` | 語意層與規則層重疊時應合併為 combined 而非兩筆 |
| `conversation.turns_before_session_end.avg` | 應略增(因補問 FH/SH) |

#### 5.3 Playwright UI 驗證
- 跑 `frontend` 的病患問診 flow,確認 conversation 在 HPI 問完後開始補問家族史。
- 檢查 `/reports/:sessionId` 頁面,確認 SOAP 各節點都正常顯示(特別是 FH/SH 不是「—」佔位)。

---

### Phase 6:選配 — P2-G DB 化紅旗規則(未來工作,不在本次範圍)

**目標**:讓紅旗清單完全由 DB 驅動,prompt 與 fallback 都變成 DB 的投影。

- 建立 migration 把 `URO_RED_FLAGS` seed 進 `red_flag_rules` 表
- Red flag prompt 改為運行時動態生成(從 DB 讀)
- Admin 頁面新增紅旗規則 CRUD
- 此階段涉及前端 admin UI,**不在本規劃範圍**。

---

## 5. Commit 時序總覽

| # | Commit | Phase | 影響檔案 | 風險 |
|---|---|---|---|---|
| 1 | `refactor: extract shared prompt constants` | 0 | 新增 `prompts/shared.py` + test | 極低(純新增) |
| 2 | `feat: upgrade supervisor to gpt-5.4 with medium reasoning` | 1 | `config.py` `.env.example` `supervisor.py` | 中(模型升級需驗費用與延遲) |
| 3 | `feat: expand conversation prompt to 10-step HPI + social history` | 2 | `llm_conversation.py` | 中(對話行為改變,須測節奏) |
| 4 | `refactor: red-flag detector now pulls from shared catalogue` | 3 | `red_flag_detector.py` | 低(輸出結構不變) |
| 5 | `fix: SOAP confidence_score should not penalise missing FH/SH/RoS` | 4 | `soap_generator.py` | 極低(純 prompt 微調) |

每個 commit 獨立、可單獨 revert。建議 commit 1 → 2 → 3 → 4 → 5 依序 push,每次 push 後在 Railway 觀察 5-10 分鐘錯誤率。

---

## 6. 回滾策略

若任一 phase 出問題:
- **Commit 1 / 4 / 5** (refactor/fix):直接 revert 該 commit,無資料面影響。
- **Commit 2** (supervisor 升級):revert 後,`OPENAI_MODEL_SUPERVISOR` 會自動 fallback 回舊值,Redis 中的 next_focus 會在下一輪被新值覆蓋,無殘留。
- **Commit 3** (conversation 擴充):revert 後,進行中的 session 會在下一輪切回舊版 prompt,病患感受到的是 AI 突然不再問家族史,不影響既有資料。

---

## 7. 完成定義(DoD)

- [ ] Phase 0-4 五個 commit 全部 push 到 main
- [ ] Railway 與 Vercel 部署成功,無 error log
- [ ] 在 production 跑一個完整的血尿問診 E2E,SOAP 報告的:
  - `hpi` 十欄至少 8 個有值
  - `family_history` 或 `social_history` 至少一個有值(表示補問機制有作用)
  - `confidence_score >= 0.75`
  - `differential_diagnoses` >= 3 項
  - `recommended_tests` >= 3 項且都有 `clinical_reasoning`
- [ ] Red flag 在同一段 transcript 產生合理警示,且與規則層正確合併為 `combined` 類型
- [ ] Supervisor 的 `next_focus` 全部都是單一問題
- [ ] `docs/prompt_chain_upgrade_plan.md` 標記為 **已完成**

---

## 8. 未解決的問題(留待後續)

1. **語音對話的打斷策略**:目前 barge-in 模式(`audioStream.ts` setMuted('soft'))會在病患說話時打斷 AI,但 conversation prompt 沒有「被打斷後該怎麼接話」的指引。未來若要支援更自然的打斷,需要在 prompt 加 state-aware 處理。
2. **多主訴情境**:目前 RED_FLAGS_BY_COMPLAINT 與 shared.URO_RED_FLAGS 都是單主訴驅動。若病人同時提兩個主訴(例如血尿 + 腰痛),過濾邏輯會只顯示第一個命中的紅旗清單。
3. **中英文主訴**:若未來 i18n 引入英文病患,所有紅旗 trigger keyword 都需要多語版本。建議後續把 URO_RED_FLAGS 改為 `triggers_zh` / `triggers_en` 分欄。
4. **Supervisor 呼叫頻率**:目前每 N 輪呼叫一次(N 在 conversation_handler 中設定)。升級到 gpt-5.4 後成本顯著提高,需要重新評估 N 值(從 3 輪改為 5 輪可能更合理)。
