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
# canonical_id (E8-4，原 TODO-E6):
#   - 跨語言穩定的 snake_case 標識符;DB RedFlagRule.canonical_id 需對應此值。
#   - dedup 以 canonical_id 為 key(不再以 title 為 key),以便未來多語言
#     版本(同一紅旗跨 zh-TW / en-US)能正確合併。
# display_title_by_lang (E8-4，原 TODO-E6):
#   - 依 session.language 選對應語言 title,由 red_flag_detector 偵測時
#     解析、conversation_handler 持久化/廣播前再次防禦性解析(見兩檔內
#     E8-4 註記)。5 語(zh-TW/en-US/ja-JP/ko-KR/vi-VN)皆已補齊翻譯。
#   - title 欄位保留為 zh-TW 版本(與語意層 prompt / legacy DB name 對齊)。
# triggers_by_lang (TODO-M8 / W1):
#   - 按 BCP-47 分層儲存 trigger keywords;`has_locale_coverage` 用此欄位
#     判斷 session.language 是否有覆蓋——若無 → confidence=uncovered_locale,
#     自動 escalate(僅影響語意層 confidence 分級,與下面規則比對用途不同)。
#   - triggers 欄位維持向後相容(等於 triggers_by_lang["zh-TW"])。
#   - W1:規則比對層(`_rule_based_detect` / `_get_fallback_rules`)**不**
#     依 session.language 篩選 keywords,而是用
#     `_collect_all_language_keywords` 取所有語言 triggers 的聯集比對
#     (病患可能混用語言;fail-open 精神下,漏報風險 > 誤報風險,見該函式
#     docstring)。目前 en-US 8 條全齊;ja-JP/ko-KR/vi-VN 已補上初版翻譯,
#     待醫療術語稽核。
# =============================================================================

URO_RED_FLAGS: list[dict[str, Any]] = [
    {
        "canonical_id": "urinary_retention",
        "title": "急性尿滯留",
        "display_title_by_lang": {
            "zh-TW": "急性尿滯留",
            "en-US": "Acute Urinary Retention",
            "ja-JP": "急性尿閉",
            "ko-KR": "급성 요폐",
            "vi-VN": "Bí tiểu cấp tính",
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
            # W1：ja/ko/vi 補齊(待稽核 agent 覆核醫療術語準確度)。
            "ja-JP": [
                "尿閉",
                "尿が出ない",
                "排尿できない",
                "全く排尿できない",
            ],
            "ko-KR": [
                "요폐",
                "소변이 안 나와요",
                "소변을 볼 수 없어요",
                "전혀 배뇨가 안 돼요",
            ],
            "vi-VN": [
                "bí tiểu",
                "không đi tiểu được",
                "không thể đi tiểu",
                "bí tiểu cấp tính",
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
            "ja-JP": "高度肉眼的血尿",
            "ko-KR": "다량의 육안적 혈뇨",
            "vi-VN": "Tiểu máu đại thể lượng nhiều",
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
            "ja-JP": [
                "大量の血尿",
                "血の塊",
                "尿が真っ赤",
                "血だらけの尿",
            ],
            "ko-KR": [
                "다량의 혈뇨",
                "혈전",
                "피가 섞인 소변이 많아요",
                "새빨간 소변",
            ],
            "vi-VN": [
                "tiểu ra nhiều máu",
                "cục máu đông trong nước tiểu",
                "nước tiểu toàn máu",
                "tiểu máu nhiều",
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
            "ja-JP": "重度の精巣痛",
            "ko-KR": "심한 고환 통증",
            "vi-VN": "Đau tinh hoàn dữ dội",
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
            "ja-JP": [
                "睾丸の激痛",
                "突然の睾丸痛",
                "陰嚢の激しい痛み",
                "急な睾丸の痛み",
            ],
            "ko-KR": [
                "극심한 고환 통증",
                "갑작스런 고환 통증",
                "심한 음낭 통증",
                "고환이 갑자기 아파요",
            ],
            "vi-VN": [
                "đau tinh hoàn dữ dội",
                "đau tinh hoàn đột ngột",
                "đau bìu dữ dội",
                "tinh hoàn đau nhói",
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
            "ja-JP": "尿路性敗血症",
            "ko-KR": "요로 패혈증",
            "vi-VN": "Nhiễm khuẩn huyết đường tiết niệu",
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
            "ja-JP": [
                "高熱",
                "悪寒",
                "意識がもうろう",
                "発熱と排尿痛",
            ],
            "ko-KR": [
                "고열",
                "오한",
                "의식이 흐려짐",
                "발열과 배뇨통",
            ],
            "vi-VN": [
                "sốt cao",
                "ớn lạnh",
                "rối loạn ý thức",
                "sốt kèm tiểu buốt",
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
            "ja-JP": "馬尾症候群の疑い",
            "ko-KR": "마미증후군 의심",
            "vi-VN": "Nghi ngờ hội chứng đuôi ngựa",
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
            "ja-JP": [
                "会陰部のしびれ",
                "下肢の脱力",
                "新たな尿失禁",
                "しびれを伴う背部痛",
            ],
            "ko-KR": [
                "회음부 감각 이상",
                "다리 힘 빠짐",
                "새로운 요실금",
                "저림을 동반한 등 통증",
            ],
            "vi-VN": [
                "tê vùng đáy chậu",
                "yếu chân",
                "tiểu không tự chủ mới xuất hiện",
                "đau lưng kèm tê",
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
            "ja-JP": "肉眼的血尿",
            "ko-KR": "육안적 혈뇨",
            "vi-VN": "Tiểu máu đại thể",
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
            "ja-JP": [
                "肉眼的血尿",
                "尿が赤い",
                "赤い尿",
                "尿に血が混じる",
            ],
            "ko-KR": [
                "육안적 혈뇨",
                "소변이 빨개요",
                "붉은 소변",
                "소변에 피가 섞여요",
            ],
            "vi-VN": [
                "tiểu máu đại thể",
                "nước tiểu đỏ",
                "tiểu ra máu",
                "nước tiểu có máu",
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
            "ja-JP": "発熱を伴う腎疝痛",
            "ko-KR": "발열을 동반한 신산통",
            "vi-VN": "Cơn đau quặn thận kèm sốt",
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
            "ja-JP": [
                "腰痛と発熱",
                "側腹部痛と発熱",
                "疝痛と発熱",
            ],
            "ko-KR": [
                "허리 통증과 발열",
                "옆구리 통증과 발열",
                "산통과 발열",
            ],
            "vi-VN": [
                "đau lưng kèm sốt",
                "đau hông kèm sốt",
                "cơn đau quặn kèm sốt",
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
            "ja-JP": "原因不明の体重減少",
            "ko-KR": "원인 불명의 체중 감소",
            "vi-VN": "Sụt cân không rõ nguyên nhân",
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
            "ja-JP": [
                "体重減少",
                "痩せてきた",
                "食欲不振",
                "原因不明の体重減少",
            ],
            "ko-KR": [
                "체중 감소",
                "살이 빠졌어요",
                "식욕 부진",
                "원인 불명의 체중 감소",
            ],
            "vi-VN": [
                "sụt cân",
                "giảm cân",
                "chán ăn",
                "sụt cân không rõ nguyên nhân",
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

    E8-2 防禦:呼叫端理論上該保證傳入字串,但曾因 fallback 邏輯誤傳
    ChiefComplaint ORM 物件進來,`cc in chief_complaint` 對非字串/不可疊代
    物件會直接 TypeError,炸掉整個問診 WS 開場。這裡對非 str 一律轉字串,
    避免上游任何一次疏漏就讓病患完全連不上問診。
    """
    if not chief_complaint:
        return list(URO_RED_FLAGS)
    if not isinstance(chief_complaint, str):
        chief_complaint = str(chief_complaint)

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
# 特定高風險主訴的「關鍵風險因子」(與 HPI 十欄同級必問) — §3b
# =============================================================================
# 根因(稽核 §3b):血尿 / PSA / ED 的關鍵風險因子被 conversation prompt 歸為
# 「次要補問」(HPI 達 7 成才問),而 Supervisor 又「不因次要未問完壓低完整度」,
# 導致核心十欄一填滿就收尾、永遠觸不到這些對惡性 / 心血管分層最關鍵的問題:
#   - 無痛肉眼血尿:吸菸史(膀胱 / 泌尿上皮癌最大可控危險因子)、抗凝血 / 抗血小板藥、
#     泌尿道癌家族史 → 決定是否需膀胱鏡 / 影像的惡性風險分層。
#   - PSA 升高:吸菸史、泌尿 / 攝護腺癌家族史(同群惡性風險)。
#   - 勃起功能障礙(ED):常為心血管疾病前哨,需問心血管危險因子。
#
# 設計:
#   - complaint_keywords 為「多語聯集」(比照紅旗 triggers_by_lang 精神),因 session
#     的 chief_complaint 是**場次語言的在地化字串**(可能為 en/ja/ko/vi),只認中文會漏。
#   - 與紅旗的 fail-open 相反:風險因子只在**明確匹配**主訴時注入(避免把心血管 / 吸菸
#     問題硬塞給無關主訴);無匹配 → 回空,維持既有行為(不變式:不亂加問題)。
#   - factors 為 conversation(必問) / supervisor(收尾前 gate)共用的單一來源。
# =============================================================================

CRITICAL_RISK_FACTORS: list[dict[str, Any]] = [
    {
        "id": "hematuria_malignancy",
        "label": "血尿／PSA 惡性風險分層",
        "complaint_keywords": [
            # zh-TW / ja-JP(血尿 同漢字)/ 通用
            "血尿",
            "psa",
            # en-US
            "hematuria",
            "haematuria",
            "blood in urine",
            # ko-KR
            "혈뇨",
            # vi-VN
            "tiểu máu",
            "tiểu ra máu",
            "nước tiểu có máu",
        ],
        "factors": [
            "吸菸史(目前或過去;無痛肉眼血尿最重要的膀胱 / 泌尿上皮癌可控危險因子)",
            "抗凝血劑或抗血小板藥物使用(如 warfarin、aspirin、NOAC)",
            "泌尿道惡性腫瘤(膀胱癌、腎癌、攝護腺癌)家族史",
        ],
    },
    {
        "id": "ed_cardiovascular",
        "label": "勃起功能障礙心血管風險",
        "complaint_keywords": [
            # zh-TW(勃起 同時涵蓋 ja 勃起不全 / 勃起障害)
            "勃起",
            "陽痿",
            # en-US
            "erectile",
            "impotence",
            # ko-KR
            "발기부전",
            "발기 장애",
            # vi-VN
            "rối loạn cương",
            "cương dương",
        ],
        "factors": [
            "心血管疾病史(高血壓、冠狀動脈疾病、心肌梗塞、腦中風)",
            "糖尿病",
            "吸菸史與血脂異常",
        ],
    },
]


def get_critical_risk_factors_for_complaint(
    chief_complaint: Any,
) -> list[dict[str, Any]]:
    """
    依主訴挑出「與 HPI 十欄同級必問」的關鍵風險因子群組(多語聯集、大小寫不敏感)。

    與 get_red_flags_for_complaint 的 fail-open 相反:只在**明確匹配**時回傳對應群組;
    無匹配回空 list(不把心血管 / 吸菸問題硬塞給不相關主訴,保守不亂加問題)。

    防禦:比照 get_red_flags_for_complaint,對非 str 一律轉字串,避免上游偶爾誤傳
    ORM 物件時炸掉問診開場。
    """
    if not chief_complaint:
        return []
    if not isinstance(chief_complaint, str):
        chief_complaint = str(chief_complaint)
    haystack = chief_complaint.lower()
    matched: list[dict[str, Any]] = []
    for group in CRITICAL_RISK_FACTORS:
        if any(kw.lower() in haystack for kw in group["complaint_keywords"]):
            matched.append(group)
    return matched


def render_critical_risk_factor_items(chief_complaint: Any) -> str:
    """
    把匹配主訴的關鍵風險因子渲染成條列(無匹配回空字串)。

    conversation(必問段)與 supervisor(收尾前 gate 段)共用此單一來源,各自在外層
    包不同的標題與規則說明,避免必問清單兩邊漂移。
    """
    groups = get_critical_risk_factors_for_complaint(chief_complaint)
    if not groups:
        return ""
    return "\n".join(f"- {f}" for g in groups for f in g["factors"])


def count_critical_risk_factors_for_complaint(chief_complaint: Any) -> int:
    """
    本主訴「與 HPI 十欄同級必問」的關鍵風險因子總題數(K)；無匹配回 0。

    §3b：conversation_handler 用此數值把高風險主訴的回合硬上限動態抬高
    (effective cap = base + K + BUFFER),讓 HPI 十欄問完後仍有回合能問到這些
    風險因子,不再被 base=10 砍掉。與 render_* 共用同一 ontology,避免題數漂移。
    """
    return sum(
        len(g["factors"]) for g in get_critical_risk_factors_for_complaint(chief_complaint)
    )


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
