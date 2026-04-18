"""
跨 pipeline 共用的 prompt 常數與 ontology。

此模組是 Single Source of Truth — conversation / supervisor / soap /
red_flag 四個 pipeline 都從這裡 import,確保:

1. HPI 步驟命名與順序一致(conversation 收集 ↔ supervisor 評估 ↔ soap 填欄)
2. 紅旗分級與 title 命名一致(規則層 fallback ↔ 語意層 prompt ↔ 對話提醒)
3. SOAP schema 的 hpi 子欄位 id 可由 HPI_FIELD_IDS 單一來源取得

修改本檔後,四個 pipeline 會自動同步 — 不需要再手動對齊 prompt 文字。
"""

from typing import Any

# =============================================================================
# HPI 十欄框架
# =============================================================================
# Conversation 依序收集、Supervisor 評估缺漏、SOAP hpi 子欄位對應。
#
# 這裡把 Aggravating 與 Relieving 拆成兩項(與 SOAP schema 對齊),
# conversation prompt 產生的 HPI 清單會是 10 步而非舊版 9 步。
# =============================================================================

HPI_STEPS: list[dict[str, str]] = [
    {
        "id": "onset",
        "zh": "Onset(發生時間)",
        "desc": "何時開始?突然還是漸進式?",
    },
    {
        "id": "location",
        "zh": "Location(位置)",
        "desc": "確切的不適部位在哪裡?",
    },
    {
        "id": "duration",
        "zh": "Duration(持續時間)",
        "desc": "持續多久?持續性還是間歇性?",
    },
    {
        "id": "characteristics",
        "zh": "Characteristics(特徵)",
        "desc": "症狀的性質(如疼痛的類型)?",
    },
    {
        "id": "severity",
        "zh": "Severity(嚴重度)",
        "desc": "以 1-10 分或描述性文字評估嚴重程度",
    },
    {
        "id": "aggravating_factors",
        "zh": "Aggravating(加重因素)",
        "desc": "什麼會使症狀加重?",
    },
    {
        "id": "relieving_factors",
        "zh": "Relieving(緩解因素)",
        "desc": "什麼會使症狀緩解?",
    },
    {
        "id": "associated_symptoms",
        "zh": "Associated(伴隨症狀)",
        "desc": "是否有其他伴隨的症狀?",
    },
    {
        "id": "timing",
        "zh": "Timing(時間模式)",
        "desc": "症狀在什麼時候特別明顯?(如夜間、排尿時)",
    },
    {
        "id": "context",
        "zh": "Context(背景)",
        "desc": "症狀發生的背景脈絡?(如受傷、手術後)",
    },
]

# 給 SOAP validator 與 supervisor missing_hpi 合法值檢查用
HPI_FIELD_IDS: list[str] = [step["id"] for step in HPI_STEPS]


def render_hpi_checklist() -> str:
    """把 HPI 步驟渲染成 prompt 可讀的條列清單(1-indexed)。"""
    return "\n".join(
        f"{i + 1}. **{step['zh']}**:{step['desc']}"
        for i, step in enumerate(HPI_STEPS)
    )


# =============================================================================
# 泌尿科紅旗統一清單
# =============================================================================
# 供 red_flag_detector(語意 prompt + fallback rules)與 llm_conversation
# (主訴相關紅旗提醒)共用。
#
# canonical_id (TODO-E6):
#   - 跨語言穩定的 snake_case 標識符;DB RedFlagRule.canonical_id 需對應此值。
#   - dedup 以 canonical_id 為 key(不再以 title 為 key),以便未來多語言
#     版本(同一紅旗跨 zh-TW / en-US)能正確合併。
# display_title_by_lang (TODO-E6):
#   - 依 Accept-Language / session.language 選對應語言 title 顯示到 UI。
#   - title 欄位保留為 zh-TW 版本(與語意層 prompt / legacy DB name 對齊)。
# triggers_by_lang (TODO-M8):
#   - 按 BCP-47 分層儲存 trigger keywords;若目前 session.language 無此
#     紅旗的對應 keywords → confidence=uncovered_locale,自動 escalate。
#   - triggers 欄位維持向後相容(等於 triggers_by_lang["zh-TW"])。
# =============================================================================

URO_RED_FLAGS: list[dict[str, Any]] = [
    {
        "canonical_id": "urinary_retention",
        "title": "急性尿滯留",
        "display_title_by_lang": {
            "zh-TW": "急性尿滯留",
            "en-US": "Acute Urinary Retention",
        },
        "severity": "critical",
        "description": "病患可能出現急性尿滯留,需要緊急處理",
        "triggers": [
            "無法排尿",
            "尿不出來",
            "完全排不出",
            "尿滯留",
            "解不出小便",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "無法排尿",
                "尿不出來",
                "完全排不出",
                "尿滯留",
                "解不出小便",
            ],
            "en-US": [
                "cannot urinate",
                "unable to pee",
                "urinary retention",
                "can't pass urine",
            ],
        },
        "related_complaints": ["排尿困難", "頻尿"],
        "suggested_actions": [
            "立即通知醫師",
            "準備導尿管",
            "安排緊急就診",
        ],
    },
    {
        "canonical_id": "gross_hematuria_heavy",
        "title": "大量血尿",
        "display_title_by_lang": {
            "zh-TW": "大量血尿",
            "en-US": "Heavy Gross Hematuria",
        },
        "severity": "critical",
        "description": "嚴重血尿合併血塊,需評估出血原因與血流動力學",
        "triggers": [
            "大量血尿",
            "血塊",
            "整個都是血",
            "血尿很多",
            "一大堆血",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "大量血尿",
                "血塊",
                "整個都是血",
                "血尿很多",
                "一大堆血",
            ],
            "en-US": [
                "heavy bleeding",
                "blood clots",
                "lots of blood",
                "clot in urine",
            ],
        },
        "related_complaints": ["血尿"],
        "suggested_actions": [
            "立即通知醫師",
            "監測生命徵象",
            "準備血液檢查",
        ],
    },
    {
        "canonical_id": "testicular_pain_severe",
        "title": "睪丸劇痛",
        "display_title_by_lang": {
            "zh-TW": "睪丸劇痛",
            "en-US": "Severe Testicular Pain",
        },
        "severity": "critical",
        "description": "可能為睪丸扭轉,需要在 6 小時內處理以避免壞死",
        "triggers": [
            "睪丸劇痛",
            "睪丸突然痛",
            "蛋蛋很痛",
            "突然睪丸",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "睪丸劇痛",
                "睪丸突然痛",
                "蛋蛋很痛",
                "突然睪丸",
            ],
            "en-US": [
                "testicular pain",
                "testicle pain",
                "sudden testicular",
                "severe scrotal pain",
            ],
        },
        "related_complaints": ["睪丸疼痛"],
        "suggested_actions": [
            "立即通知泌尿科醫師",
            "安排緊急超音波",
            "準備手術可能",
        ],
    },
    {
        "canonical_id": "urosepsis",
        "title": "尿路敗血症",
        "display_title_by_lang": {
            "zh-TW": "尿路敗血症",
            "en-US": "Urosepsis",
        },
        "severity": "critical",
        "description": "尿路感染合併全身性感染徵象,可能為尿路敗血症",
        "triggers": [
            "高燒",
            "寒顫",
            "意識不清",
            "發燒加排尿痛",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "高燒",
                "寒顫",
                "意識不清",
                "發燒加排尿痛",
            ],
            "en-US": [
                "high fever",
                "chills",
                "altered consciousness",
                "fever with dysuria",
            ],
        },
        "related_complaints": ["頻尿", "排尿困難", "血尿"],
        "suggested_actions": [
            "立即通知醫師",
            "安排血液培養",
            "準備抗生素",
        ],
    },
    {
        "canonical_id": "cauda_equina_suspected",
        "title": "疑似馬尾症候群",
        "display_title_by_lang": {
            "zh-TW": "疑似馬尾症候群",
            "en-US": "Suspected Cauda Equina Syndrome",
        },
        "severity": "critical",
        "description": (
            "會陰麻木、下肢無力合併新發尿失禁或尿滯留,疑似脊髓壓迫 / 馬尾症候群,"
            "需緊急神經科與泌尿科會診"
        ),
        "triggers": [
            "會陰麻木",
            "下肢無力",
            "新發尿失禁",
            "背痛合併麻木",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "會陰麻木",
                "下肢無力",
                "新發尿失禁",
                "背痛合併麻木",
            ],
            "en-US": [
                "saddle anesthesia",
                "leg weakness",
                "new incontinence",
                "back pain with numbness",
            ],
        },
        "related_complaints": ["排尿困難", "腰痛"],
        "suggested_actions": [
            "立即通知神經外科",
            "安排緊急 MRI",
            "評估是否需手術減壓",
        ],
    },
    {
        "canonical_id": "gross_hematuria",
        "title": "肉眼血尿",
        "display_title_by_lang": {
            "zh-TW": "肉眼血尿",
            "en-US": "Gross Hematuria",
        },
        "severity": "high",
        "description": "肉眼可見血尿,需進一步檢查排除惡性腫瘤",
        "triggers": [
            "肉眼血尿",
            "尿是紅色",
            "紅色的尿",
            "血尿",
            "尿裡有血",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "肉眼血尿",
                "尿是紅色",
                "紅色的尿",
                "血尿",
                "尿裡有血",
            ],
            "en-US": [
                "gross hematuria",
                "blood in urine",
                "red urine",
                "hematuria",
            ],
        },
        "related_complaints": ["血尿"],
        "suggested_actions": [
            "安排尿液檢查",
            "考慮膀胱鏡檢查",
            "通知主治醫師",
        ],
    },
    {
        "canonical_id": "renal_colic_with_fever",
        "title": "腎絞痛合併發燒",
        "display_title_by_lang": {
            "zh-TW": "腎絞痛合併發燒",
            "en-US": "Renal Colic with Fever",
        },
        "severity": "high",
        "description": "腎結石合併感染,可能需要緊急引流",
        "triggers": [
            "腰痛加發燒",
            "側腹痛加燒",
            "絞痛加發燒",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "腰痛加發燒",
                "側腹痛加燒",
                "絞痛加發燒",
            ],
            "en-US": [
                "flank pain with fever",
                "back pain with fever",
                "colic with fever",
            ],
        },
        "related_complaints": ["腰痛"],
        "suggested_actions": [
            "安排影像檢查",
            "抽血檢查發炎指數",
            "通知泌尿科醫師",
        ],
    },
    {
        "canonical_id": "unexplained_weight_loss",
        "title": "不明原因體重下降",
        "display_title_by_lang": {
            "zh-TW": "不明原因體重下降",
            "en-US": "Unexplained Weight Loss",
        },
        "severity": "high",
        "description": "不明原因體重急速下降,需排除惡性腫瘤",
        "triggers": [
            "體重下降",
            "變瘦",
            "吃不下",
            "體重減輕",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "體重下降",
                "變瘦",
                "吃不下",
                "體重減輕",
            ],
            "en-US": [
                "weight loss",
                "losing weight",
                "poor appetite",
                "unintentional weight loss",
            ],
        },
        "related_complaints": ["血尿", "腰痛"],
        "suggested_actions": [
            "安排全面檢查",
            "考慮腫瘤篩檢",
            "通知主治醫師",
        ],
    },
]


def get_display_title(canonical_id: str, language: str | None) -> str:
    """
    依 canonical_id 與 language 查找 display title;找不到時依序退到更通用的語言。

    Fallback 順序:
        requested language → en-US → zh-TW → catalogue name → canonical_id

    先試 en-US 再試 zh-TW，是因為:ja-JP / ko-KR / vi-VN 若某紅旗無對應翻譯,
    改送英文「Heavy Gross Hematuria」比送中文「大量血尿」對病患更友善。

    用於 alert serializer 按 Accept-Language / session.language 解析 title。
    """
    for flag in URO_RED_FLAGS:
        if flag.get("canonical_id") == canonical_id:
            by_lang = flag.get("display_title_by_lang", {})
            if language and language in by_lang:
                return by_lang[language]
            if "en-US" in by_lang:
                return by_lang["en-US"]
            if "zh-TW" in by_lang:
                return by_lang["zh-TW"]
            return flag.get("title", canonical_id)
    return canonical_id


def has_locale_coverage(canonical_id: str, language: str | None) -> bool:
    """
    檢查某 canonical_id 在指定 language 是否有 trigger keywords 覆蓋。

    回 False → RedFlagDetector 會把 confidence 設為 uncovered_locale、
    自動 escalate 為 physician review。
    """
    if not language:
        return True  # 沒 language 視為 zh-TW(預設)
    for flag in URO_RED_FLAGS:
        if flag.get("canonical_id") == canonical_id:
            by_lang = flag.get("triggers_by_lang", {})
            keywords = by_lang.get(language, [])
            return bool(keywords)
    return False


def get_red_flags_for_complaint(chief_complaint: str) -> list[dict[str, Any]]:
    """
    依主訴篩出相關紅旗;若主訴為空或無匹配,回傳全部紅旗。

    注意:這裡用 substring match(而非嚴格相等),讓「血尿持續三天」也能
    命中 related_complaints 中的「血尿」。
    """
    if not chief_complaint:
        return list(URO_RED_FLAGS)

    matches = [
        f
        for f in URO_RED_FLAGS
        if any(cc in chief_complaint for cc in f["related_complaints"])
    ]
    return matches if matches else list(URO_RED_FLAGS)


def render_red_flag_titles_for_prompt() -> str:
    """產生 red_flag prompt 中『title 命名對齊』段落。"""
    return "\n".join(f"- 「{f['title']}」" for f in URO_RED_FLAGS)


def render_red_flags_by_severity() -> str:
    """
    產生三層臨床情境清單(給 red_flag prompt 用)。

    輸出格式:
        ### Critical(危急)
        - **<title>**:<description>
        ...
        ### High(嚴重)
        ...
    """
    severity_order = [
        ("critical", "Critical(危急,建議立即急診評估)"),
        ("high", "High(嚴重,建議優先由醫師評估,不宜久候)"),
        ("medium", "Medium(中等,需補問與人工複核)"),
    ]
    by_sev: dict[str, list[dict[str, Any]]] = {
        "critical": [],
        "high": [],
        "medium": [],
    }
    for f in URO_RED_FLAGS:
        by_sev.setdefault(f["severity"], []).append(f)

    lines: list[str] = []
    for sev, label in severity_order:
        if not by_sev[sev]:
            continue
        lines.append(f"\n### {label}")
        for f in by_sev[sev]:
            lines.append(f"- **{f['title']}**:{f['description']}")
    return "\n".join(lines).strip()


def render_red_flags_for_conversation(chief_complaint: str) -> str:
    """
    給 conversation prompt 的紅旗提醒段落(依主訴過濾)。

    輸出格式(條列):
        - <title>:<description>
    """
    flags = get_red_flags_for_complaint(chief_complaint)
    return "\n".join(f"- {f['title']}:{f['description']}" for f in flags)


# =============================================================================
# 跨 pipeline 共用的輸出規則
# =============================================================================
# conversation / supervisor 都要求「單一問題」,寫在一起避免兩邊漂移。
# =============================================================================

SINGLE_QUESTION_RULE = """【每輪輸出的硬性限制】
- **一次只追問一個問題**,絕對不可在同一輪塞多個問題讓病患一次回答。
- 每次回覆最多 2 句話,保持口語、簡潔。
- 不使用 markdown、不用 bullet、不用條列符號。
"""
