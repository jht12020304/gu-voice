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
        # ⚠️ 2026-07-27 第四輪 Gate：共現組原本只加在 testicular_pain_severe 一個紅旗，
        #    另外 4 個 critical 仍是純相鄰複合詞。對本紅旗做 5 語 × ≥3 種真人語序的
        #    直接探針（用 `_rule_based_detect` 真跑）**16/16 全數漏報**：
        #      zh 「我從今天早上開始就完全解不出來，膀胱脹到受不了」（解不出『來』≠『小便』）
        #      zh 「小便一滴都出不來，下腹脹得很痛」（動作詞與『出不來』間插入『一滴都』）
        #      en 「I haven't been able to pee since last night…」（unable to pee 不相鄰）
        #      ja 「トイレに行っても尿が全く出ません、膀胱がパンパンです」（『尿が出ない』間に『全く』）
        #      ko 「어젯밤부터 소변이 한 방울도 안 나와서…」（『소변이 안 나와요』사이 삽입）
        #      vi 「tôi mót tiểu mà không tiểu được…」（『không đi tiểu được』thiếu『đi』）
        #    這與睪丸扭轉 (C) 是**同一個**缺陷：相鄰子字串對真人語序無效。
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
        # ⚠️ 下面標「否定詞開頭」的那幾條**不能**用共現組表達，只能是相鄰片語：
        # detector 的否定守衛只回看關鍵字**之前**的文字，所以「沒辦法／出ません」這種
        # 「病患用否定句描述自己的症狀」的講法，只有讓關鍵字**從否定詞本身開始**
        # 才不會被守衛抹掉（共現組的部位詞、急性詞、整段跨度三者都要非否定，
        # 而尿語詞永遠落在否定詞之後 → 結構上無解）。
        # 根因在 detector（`_CUE_FALSE_FRIENDS` 只認「與 cue 同起點」的假朋友，
        # 接不住「出ません」「沒辦法」這種 cue 在片語中段的形狀），已回報給該檔負責人；
        # 在那之前這幾條是唯一能接住這類真人講法的方式。
        "triggers": [
            "無法排尿",
            "尿不出來",
            "完全排不出",
            "尿滯留",
            "解不出小便",
            # 否定詞開頭（見上方註記）
            "沒辦法尿",
            "沒辦法小便",
            "沒辦法排尿",
            "沒辦法解尿",
            "沒辦法上小號",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "無法排尿",
                "尿不出來",
                "完全排不出",
                "尿滯留",
                "解不出小便",
                "沒辦法尿",
                "沒辦法小便",
                "沒辦法排尿",
                "沒辦法解尿",
                "沒辦法上小號",
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
                # 副詞が「出ません」の前に入る形（共現組では拾えない、上方註記参照）
                "全く出ません",
                "全然出ません",
                "全く出ない",
                "全然出ない",
                "一滴も出ません",
                "一滴も出ない",
                "おしっこが出ない",
                "おしっこが出ません",
                "小便が出ない",
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
        # ── 共現組：排尿動作／尿液／膀胱詞 × 完全排不出／膀胱脹痛詞 ──────
        # 臨床依據：急性尿滯留的兩個必要成分就是「想排尿的動作」與「完全排不出／
        # 膀胱過度膨脹」。單獨一項都不是急症（只有膀胱＝正常生理；只有「出不來」＝
        # 可能在講大便），兩者同一子句共現才是 AUR。這正好對應探針裡漏掉的形狀：
        # 病患把量詞／時間／副詞插在兩者中間（「小便**一滴都**出不來」「尿が**全く**
        # 出ません」「소변이 **한 방울도** 안 나와」），相鄰複合詞一條都接不到。
        #
        # 兩個方向的安全性：
        #   under：語序與插入語不再影響命中（探針 16 筆漏報全解，見上方註記）。
        #   over ：`acuity_terms` 一律要求「排不出／脹到痛」，**不含**任何純頻率或
        #     純量詞（沒有裸「很多」「次數」），所以頻尿主訴「我小便次數很多，一天
        #     十幾次」仍然 0 命中——那是本紅旗最危險的誤報面（頻尿是門診第一大主訴）。
        #     明確否認（「我沒有尿不出來的問題」）由 detector 的否定守衛照常抑制。
        # ⚠️ BPH 的排尿猶豫（「有時候尿不出來要等很久」）會命中 → 這是**刻意**的：
        #    既有的裸 trigger「尿不出來」本來就會命中，且使用者已拍板「偏誤報」。
        "trigger_cooccurrence": [
            {
                "id": "void_x_obstruction",
                # 2026-07-27 主 agent 開啟：英文（與中文）敘述尿滯留時，最自然的講法
                # 是「平常正常，**但是**現在尿不出來」——部位詞落在前一個子句、
                # 阻塞詞落在後一個子句，同子句限制會把整句漏掉。實測漏報：
                #   "normally i pee fine, but since last night nothing comes out"
                #   "usually my urine is normal, but today i cannot pass any urine at all"
                # 兩句都是教科書級尿滯留。acuity_terms 本身夠具體（nothing comes out /
                # not a drop / completely blocked / distended…），跨子句配對的誤報面
                # 有限；依 2026-07-27「偏誤報」臨床拍板，取寬。
                "cross_clause": True,
                "site_terms": [
                    # zh-TW（排尿動作／尿液／膀胱）
                    "尿", "小便", "小號", "排尿", "膀胱", "解手",
                    # ja-JP（「下腹」は膀胱膨満の訴えの定型表現なので部位側に入れる）
                    "おしっこ", "小水", "下腹", "尿意",
                    # ko-KR
                    "소변", "오줌", "배뇨", "방광",
                    # en-US（site 側は前後**両方**の詞邊界比對なので語形を列挙する。
                    #        "pee" が "people" に当たらないのはこの両側境界のおかげ）
                    "urine", "urinate", "urinated", "urinating", "urination",
                    "pee", "peed", "peeing", "bladder", "void", "voiding",
                    # vi-VN（"rặn"＝いきむ。排尿動作そのもので、
                    #        「rặn mãi mà không ra được…」の否定に潰されない唯一の足場）
                    "tiểu", "nước tiểu", "bàng quang", "rặn",
                ],
                "acuity_terms": [
                    # zh-TW：完全排不出
                    # ⚠️ 刻意**不收**「尿不出」這種切在「來」之前的殘段：detector 的
                    #    子句尾否認 pattern 允許的 filler 只有痛/腫/症狀那幾類，殘留的
                    #    「來」會擋在否認前面，於是「尿不出來倒是沒有」（後置否定，
                    #    病患在**否認**這個症狀）反而變成 critical（實測：
                    #    test_red_flag_over_trigger 的生成式反例當場紅）。
                    #    完整的「尿不出來」本來就是既有的裸 trigger，覆蓋不會少。
                    "出不來", "出不去", "解不出", "排不出", "滴不出",
                    "一滴都", "一滴也", "半滴", "尿不太出", "解不太出",
                    # zh-TW：膀胱過度膨脹（脹到痛才收，單純「有點脹」不收）
                    "脹到", "脹得", "脹痛", "很脹", "脹起來", "脹滿", "鼓鼓",
                    "硬邦邦", "撐得", "快爆",
                    # ja-JP（「出ない/出なく/出ません」は係り先が尿でなくても
                    #        site 側が尿語なので誤配は限定的）
                    "出ない", "出なく", "出ません", "全く出", "全然出", "一滴も",
                    "できません", "できていません", "できない", "張って", "張った",
                    "パンパン", "苦しい", "溜まって",
                    # ko-KR
                    "안 나와", "안 나오", "안 나옵", "나오지 않", "못 누", "못 봐",
                    "못 보", "한 방울도", "빵빵", "터질 것", "터질 듯",
                    # en-US（acuity 側は前緣のみの詞邊界＝語尾変化を拾う）
                    "nothing comes out", "nothing came out", "not a drop",
                    "haven't been able", "have not been able", "hasn't been able",
                    "unable to", "can't get any", "cannot get any",
                    # 單詞 trigger 只收了縮寫形 "can't pass urine"，接不到
                    # "cannot pass any urine at all" 這種展開＋插字的講法（實測漏報）。
                    "cannot pass", "can not pass", "can't pass", "unable to pass",
                    "won't come out", "will not come out", "completely blocked",
                    "burst", "distended", "rock hard", "hard as a rock",
                    # vi-VN
                    "không ra được", "không tiểu được", "không ra giọt",
                    "căng tức", "căng cứng", "chướng", "tức bụng",
                ],
            }
        ],
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
        # ── 共現組：尿液詞 × 大量／血塊／整片鮮紅 ────────────────
        # 2026-07-27 第四輪 Gate 探針：5 語 × 3 種真人語序 **15/15 全數漏報**
        #   zh 「今天早上尿出來整個馬桶都是血」（『整個都是血』不相鄰）
        #   zh 「小便裡面血很多」（『血尿很多』不相鄰）
        #   en 「there was a huge amount of blood in my urine this morning」
        #   ja 「尿の色が真っ赤で量もかなり多いです」（『尿が真っ赤』の間に語）
        #   ko 「오늘 아침 소변에 피가 아주 많이 섞여 나왔어요」
        #   vi 「sáng nay tôi đi tiểu ra rất nhiều máu」（chèn『rất』）
        #
        # 臨床依據：本紅旗 = 肉眼血尿(high) ＋「量大／有血塊」這個嚴重度軸。所以
        # 兩個維度就是「尿液」×「大量或血塊」，兩者共現才是 critical。
        #
        # ⚠️ 為什麼 `acuity_terms` 的**每一條都自帶「血」的語意**（血塊／都是血／
        #    ほとんど血／핏덩／máu…）而不是裸的量詞「很多／nhiều／많이」：
        #    site 側是尿液詞，若量詞不帶血，「我最近小便次數很多，一天十幾次」
        #    這句**頻尿主訴**（門診第一大主訴）就會變成 critical、第 1 輪 abort。
        #    這是本紅旗唯一真正危險的誤報面，用「量詞必須帶血」結構性關掉。
        #    保留的誤報（例：小量血尿被講成「有血」＋「一直」）屬於使用者已拍板
        #    可接受的那一類，且升級方向與 RED_FLAG_SUPERSEDES 一致（父蓋子）。
        "trigger_cooccurrence": [
            {
                "id": "urine_x_heavy_blood",
                "site_terms": [
                    # zh-TW
                    "尿", "小便", "馬桶", "尿液",
                    # ja-JP
                    "おしっこ", "小水", "トイレ",
                    # ko-KR
                    "소변", "오줌",
                    # en-US（両側詞邊界。"pee" が "people" に当たらない理由）
                    "urine", "urinate", "urinated", "urinating", "urination",
                    "pee", "peed", "peeing", "toilet", "bladder",
                    # vi-VN
                    "tiểu", "nước tiểu",
                ],
                # ⚠️ 這一組只收「量 / 血塊 / 持續出血」——critical ＝ 中止問診。
                # 純粹的**顏色或血的存在**（鮮紅、bloody、尿血、真っ赤、새빨、đỏ tươi）
                # 一律不在這裡，改掛在 gross_hematuria(high) 的 urine_x_blood_present。
                # 理由：heavy 的臨床定義是量與血塊，不是顏色；而「血尿」正是選單上的
                # 主訴 c1，用顏色詞判 critical 會讓血尿病患一講出自己的主訴就被中止，
                # 那條問診路徑在英文下結構上永遠跑不完（2026-07-27 實測 hematuria_3b_en
                # 第 2 輪 aborted_red_flag）。降級不會造成漏報——high 仍會發警示，
                # 只是不中止問診。
                "acuity_terms": [
                    # zh-TW（每一條都含「血」或血塊語意）
                    "都是血", "全是血", "滿是血", "好多血", "很多血", "血很多",
                    "一堆血", "一大堆血", "大量血", "大量的血", "血塊", "血凝塊",
                    "凝血塊", "血尿很多", "一直流血", "血一直流",
                    # ja-JP（「かたまり」「덩어리」單獨收：血塊本身就是 heavy 的臨床
                    #  判準，而病患常講「血の混じったかたまり」把血與塊拆開，
                    #  複合詞「血の塊」接不到。與 site 尿/小便 共現才成立，
                    #  誤配面（結石を「かたまり」と呼ぶ）依偏誤報政策接受。）
                    "血だらけ", "血の塊", "血のかたまり", "かたまり", "塊",
                    "血がたくさん", "血がいっぱい", "血が多", "大量の血", "血まみれ",
                    "血が止まらな",
                    # ko-KR（裸「다량」は不採用：「소변을 다량으로」＝多尿を
                    #        critical にしてしまう。必ず血語とセットで収録する）
                    "핏덩", "피떡", "피가 많", "피가 아주",
                    "피가 계속", "혈전", "다량의 피", "다량의 혈", "피가 뚝뚝",
                    # 「덩어리」單獨收：理由同 ja 的「かたまり」
                    "덩어리",
                    # en-US（前緣詞邊界＝語尾変化も拾う）
                    "lot of blood", "lots of blood", "so much blood",
                    "amount of blood", "full of blood", "all blood",
                    "blood clot", "clots", "clotting",
                    # vi-VN
                    "nhiều máu", "toàn máu", "cục máu", "máu cục", "đầy máu",
                    "ra máu nhiều", "máu đông",
                ],
            }
        ],
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
        # ⚠️ 這組 triggers 的覆蓋率是「規則層 fallback」的最後防線（不變式 #9），
        # 但它同時是**唯一一組命中即 abort 整場問診**的 critical 關鍵字，所以兩個
        # 方向的錯誤都要顧。
        #
        # (A) 漏報（2026-07-27 e2e `torsion_critical_zh` 真跑）：病患第一句是教科書級
        #     扭轉描述「大約兩小時前左邊睪丸突然劇烈疼痛，陰囊腫起來，痛到想吐，
        #     走路都有困難」，舊的 4 條 zh-TW triggers（睪丸劇痛／睪丸突然痛／蛋蛋很痛／
        #     突然睪丸）**一條都沒命中**（語序相反）→ DB alert 落成 semantic_only、
        #     trigger_keywords 空 → 6 小時黃金窗全靠語意層獨撐。
        # (B) 誤報（同日對抗式覆核，補 (A) 時自己製造出來的）：為了修 (A) 補進**裸**
        #     關鍵字「睪丸痛／睪丸疼痛／蛋蛋痛／陰囊痛」，於是
        #       「我想問睪丸痛要看哪一科」「小便會痛，睪丸痛倒是沒有」
        #       「以前睪丸痛過，但現在完全好了」
        #     全部變成 critical → 第 1 輪就 aborted_red_flag，病患白跑一趟。
        #
        # 取捨（明文）：規則層是 fallback，語意層仍獨立跑；**誤中止一整場問診的代價
        # 高於規則層漏一句**（漏了還有語意層、還有現場醫護），所以往保守收：
        #   1. 一律「部位詞 × 急性／嚴重度／發作詞」的組合，不收裸『部位＋痛』。
        #      被拿掉的「睪丸疼痛」正是系統自己的主訴標籤（見下方 related_complaints）
        #      ——病患只要複誦一次選單上的主訴名稱就會被 abort。
        #   2. 拉丁字母關鍵字（en/vi）由 red_flag_detector 的**詞邊界**比對保護，
        #      「ball hurt」不再命中「eyeball hurts」（曾實測誤觸 critical）。
        #   3. 「否認／時態／詢問假設」語氣由 red_flag_detector 的否定守衛處理，
        #      不靠關鍵字表硬擋（見該檔 `_occurrence_negated`）。
        # ⚠️ 新增任何 trigger 前，先在 tests/unit/pipelines/test_red_flag_over_trigger.py
        #    補一組「相近但不該觸發」的反例；那個檔是這條 abort 路徑的 over-trigger 防線。
        #
        # 註：en-US 的裸「testicular pain / testicle pain」是本次改動**之前**就存在、
        # 且被 E11 的五語言對照測試（denies fever, however he has testicular pain）
        # 綁住的既有行為，本輪不動它；殘餘風險記在回報的 risks。
        #
        # (C) 又漏報（2026-07-27 第三輪對抗式覆核）：為了修 (B) 的誤報，上面那組
        #     triggers 全被收成「睪丸突然」這種**相鄰複合子字串**——但 zh/ja/ko/vi
        #     的真實語序會在部位詞與修飾詞之間插入時間、方位、程度：
        #       「睪丸**兩個小時前**突然劇痛」    → 「睪丸突然」不相鄰 → 0 命中
        #       「急に**左の**睾丸が激しく痛く」  → 「急に睾丸」不相鄰 → 0 命中
        #       「갑자기 **왼쪽** 고환이 심하게」 → 「갑자기 고환」不相鄰 → 0 命中
        #       「tinh hoàn **trái** đau dữ dội」→ 不相鄰 → 0 命中
        #     e2e persona 台詞剛好是「左邊睪丸突然劇烈疼痛」（相鄰）所以測試全綠
        #     ——那是**拿實作去配適測試**，不是在測行為。
        #     修法＝下面的 `trigger_cooccurrence`：改用「部位詞 × 急性/嚴重度詞在
        #     同一子句內共現（距離上限）」，語序與插入語都不影響命中，而「有部位、
        #     無急性/嚴重度詞」的慢性主訴仍然不命中。這個結構天生同時解掉 over 與
        #     under 兩個方向，比繼續堆相鄰關鍵字清單可靠。相鄰 triggers 保留不動
        #     （其他紅旗仍在用同一套單詞比對機制）。
        "triggers": [
            "睪丸劇痛",
            "睪丸突然痛",
            "蛋蛋很痛",
            "突然睪丸",
            # ── 2026-07-27 補：真實口語（含 e2e 實測漏掉的語序）。每一條都自帶
            #    急性（突然）或嚴重度（劇/很/好/痛到/痛得/痛死）或合併腫脹（腫痛）──
            "睪丸突然",
            "睪丸很痛",
            "睪丸好痛",
            "睪丸痛到",
            "睪丸痛得",
            "睪丸痛死",
            "睪丸劇烈",
            "睪丸腫痛",
            "睪丸扭轉",
            "蛋蛋突然",
            "蛋蛋劇痛",
            "蛋蛋腫痛",
            "陰囊劇痛",
            "陰囊劇烈",
            "陰囊突然",
            "陰囊很痛",
        ],
        "triggers_by_lang": {
            "zh-TW": [
                "睪丸劇痛",
                "睪丸突然痛",
                "蛋蛋很痛",
                "突然睪丸",
                "睪丸突然",
                "睪丸很痛",
                "睪丸好痛",
                "睪丸痛到",
                "睪丸痛得",
                "睪丸痛死",
                "睪丸劇烈",
                "睪丸腫痛",
                "睪丸扭轉",
                "蛋蛋突然",
                "蛋蛋劇痛",
                "蛋蛋腫痛",
                "陰囊劇痛",
                "陰囊劇烈",
                "陰囊突然",
                "陰囊很痛",
            ],
            "en-US": [
                # ⚠️ 裸「testicular pain」與「scrotal pain」**不可放回**：它們就是
                # complaint_fallback_i18n 的 en-US 主訴標籤（Testicular pain /
                # Scrotal pain）。病患只要把選單上的主訴名稱複誦一次（「I'm here for
                # testicular pain, it's been three months」）就會在第 1 輪被
                # aborted_red_flag——慢性睪丸痛是門診最常見的良性主訴之一。
                # 這條由 test_red_flag_over_trigger.py 的
                # `test_no_critical_trigger_equals_a_chief_complaint_label` 結構性守住。
                "testicle pain",
                "sudden testicular",
                "severe scrotal pain",
                "sudden testicle",
                # 語序相反（「testicle suddenly started to hurt」）—— zh-TW 真跑漏掉的
                # 正是同一種語序問題，五語言一起補。
                "testicle suddenly",
                "testicles suddenly",
                # ⚠️ 這四條靠 red_flag_detector 的**詞邊界**比對才安全：純子字串比對時
                # 「ball hurt」會命中「my eyeball hurts a lot」→ critical → 誤中止問診
                # （2026-07-27 對抗式覆核實測）。詞邊界只檢查**前緣**，所以
                # 「my ball hurts」的字尾變化（hurt/hurts/hurting）仍照常命中。
                "testicle hurt",
                "testicles hurt",
                "ball hurt",
                "balls hurt",
                "scrotum pain",
                "pain in my testicle",
                "pain in my scrotum",
                "testicular torsion",
                # 註：刻意不收裸「swollen testicle」——無痛陰囊腫脹多為陰囊水腫/疝氣，
                # 不到 critical（會誤中止問診）；腫＋痛已由上面的 pain 系列覆蓋。
                # zh/ja/ko/vi 的腫脹詞同理，一律要求「痛」或「突然」。
            ],
            "ja-JP": [
                "睾丸の激痛",
                "突然の睾丸痛",
                "陰嚢の激しい痛み",
                "急な睾丸の痛み",
                # 「精巣」は display title でも使う正式名称。旧リストに一切無く、
                # 精巣表記の患者発話は規則層で完全に素通りしていた。
                "睾丸が痛い",
                "睾丸の痛み",
                "睾丸捻転",
                "急に睾丸",
                "突然睾丸",
                "精巣が痛い",
                "精巣の痛み",
                "精巣捻転",
                "陰嚢が痛い",
                "陰嚢の痛み",
                "陰嚢が腫れて痛",
                "急に陰嚢が腫れ",
                "キンタマが痛い",
                # ⚠️ 裸「睾丸痛」「精巣痛」は**入れない**：complaint_fallback_i18n の
                # 主訴ラベル ja-JP がちょうど「睾丸痛」——選択肢を復唱しただけの患者
                # （慢性でも）が第 1 ターンで aborted_red_flag になる。
            ],
            "ko-KR": [
                "극심한 고환 통증",
                "갑작스런 고환 통증",
                "심한 음낭 통증",
                "고환이 갑자기 아파요",
                # ⚠️ 裸「고환 통증」は入れない：complaint_fallback_i18n の主訴ラベル
                # ko-KR がちょうど「고환 통증」（上の ja-JP と同じ理由）。重症度付き
                # だけを収録する。
                "고환 통증이 심",
                "고환 통증이 너무",
                "고환이 아파",
                "고환이 너무 아파",
                "고환 꼬임",
                "고환 염전",
                "갑자기 고환",
                "음낭이 아파",
                "갑자기 음낭이 부어",
                "불알이 아파",
            ],
            "vi-VN": [
                "đau tinh hoàn dữ dội",
                "đau tinh hoàn đột ngột",
                "đau bìu dữ dội",
                "tinh hoàn đau nhói",
                # ⚠️ 裸「đau tinh hoàn」は入れない：complaint_fallback_i18n の主訴
                # ラベル vi-VN がちょうど「Đau tinh hoàn」（上と同じ理由）。
                "tinh hoàn đau",
                # 睪丸扭轉幾乎都是單側，越南文會把 bên trái/phải 插在部位與 đau 之間
                "tinh hoàn bên trái đau",
                "tinh hoàn bên phải đau",
                "tinh hoàn sưng đau",
                "bìu sưng đau",
                "xoắn tinh hoàn",
                "đau nhói ở tinh hoàn",
            ],
        },
        "related_complaints": ["睪丸疼痛"],
        # ── 共現組（見上方 (C)）──────────────────────────────
        # 語意：`site_terms` 任一詞 **且** `acuity_terms` 任一詞出現在**同一子句**
        # （逗號也算子句邊界）內、彼此間隔 ≤ `window` 字元 → 命中。順序不拘
        # （「急に…睾丸」與「睾丸…激しく」都算），中間可以插入任意時間/方位/程度詞。
        #
        # 為什麼分兩張表而不是繼續堆複合詞：複合詞的數量是 site × acuity 的乘積，
        # 而且乘積裡每一個都還要再乘上「中間可能插入的字」的組合數 → 不可能列完。
        # 拆成兩張表之後，新增一個部位詞或一個嚴重度詞是 O(1) 的維護成本。
        #
        # 兩個方向的安全性（這是本結構的重點）：
        #   under-trigger：語序/插入語不再影響命中（(C) 的四語言漏報全解）。
        #   over-trigger：`site_terms` 只有部位、`acuity_terms` 只有急性/嚴重度，
        #     **兩者都不含裸「痛」**，所以「我睪丸痛已經半年了」「testicular pain
        #     for three months」這類慢性主訴（含複誦主訴標籤）仍然不命中；
        #     子句邊界讓「我眼睛突然很痛，睪丸沒事」不會跨句配對；
        #     否定/時態/假設/行政詢問守衛照樣套用在共現的整段跨度上
        #     （見 red_flag_detector `_cooccurrence_matches`）。
        # ⚠️ 這兩張表刻意**不收**裸腫脹詞（腫/swollen/腫れ/부어/sưng）：無痛陰囊腫脹
        #    多為水腫/疝氣，不到 critical；腫＋痛的組合已由「腫痛/sưng đau/腫れて痛」
        #    這類複合詞覆蓋。
        # ⚠️ 新增任何 term 前，先確認 test_red_flag_cooccurrence.py 的雙向測試表
        #    （MUST_FIRE ∕ MUST_NOT_FIRE ∕ 插入語結構測試）仍然全綠。
        "trigger_cooccurrence": [
            {
                "id": "site_x_acuity",
                # window 不寫死：由 red_flag_detector 依書寫系統決定（CJK 16 / 拉丁 30），
                # 因為同樣的字元數在中日韓等於 2–4 倍的語素量。寫死單一值會讓韓文的
                # 「고환은 괜찮은데 오늘 아침부터 배가 심하게 아파요」把屬於「배」的
                # 「심하게」配到「고환」上（實測誤觸發 critical）。
                "site_terms": [
                    # zh-TW
                    "睪丸", "睾丸", "蛋蛋", "陰囊", "卵蛋",
                    # ja-JP（睾丸 與 zh 共用；キンタマ 為口語）
                    "精巣", "陰嚢", "キンタマ",
                    # ko-KR
                    "고환", "음낭", "불알",
                    # en-US（詞邊界比對：前後緣都要求，"eyeball"/"ballpark" 都不會命中）
                    "testicle", "testicles", "testicular",
                    "scrotum", "scrotal", "ball", "balls",
                    # vi-VN
                    "tinh hoàn", "bìu", "hòn dái",
                ],
                "acuity_terms": [
                    # zh-TW：急性發作 ∕ 嚴重度 ∕ 扭轉本身
                    "突然", "忽然", "劇痛", "劇烈", "很痛", "好痛", "超痛",
                    "痛到", "痛得", "痛死", "痛爆", "爆痛", "腫痛", "扭轉",
                    "非常痛", "痛翻", "嚴重",
                    # 「毫無預警／無預警／毫無徵兆」語意上就是「突然」的同義說法
                    # （急性發作），2026-07-27 第三輪 Gate 從真實口語敘事語序補進。
                    # 註：這幾個詞同時列在 red_flag_detector._CUE_FALSE_FRIENDS，
                    # 否則其中的「無」會被否定守衛當成否定線索、把整句抹掉。
                    "毫無預警", "無預警", "毫無徵兆",
                    # ja-JP
                    "急に", "急な", "激しい", "激しく", "激痛", "ひどい", "ひどく",
                    "すごく痛", "とても痛", "捻転", "我慢できない",
                    # ko-KR
                    "갑자기", "갑작스", "심하게", "심한", "심해", "극심",
                    "너무 아파", "너무 아프", "꼬임", "염전",
                    # en-US（前緣詞邊界，字尾變化如 suddenly/severely 照樣命中）
                    "sudden", "severe", "excruciating", "unbearable", "worst",
                    "agony", "agoniz", "intense", "extreme", "torsion",
                    # 2026-07-27 第四輪 Gate：只列 hurts/hurt 接不到進行式，
                    # 「my left testicle started **hurting so much** …that i threw up」
                    # 規則層 0 命中（critical 漏報）。詞邊界只檢查前緣，救不了這種
                    # **詞組**內部的字尾變化，只能分別列舉。
                    "hurts so much", "hurt so much", "hurting so much",
                    "really bad", "so bad",
                    # 2026-07-27 第三輪 Gate 雙向探針補：這兩個是英文病患描述急性
                    # 發作最自然的副詞，缺了就整批漏報（"came on abruptly"、
                    # "started hurting acutely"）。前緣詞邊界讓 abruptly/acutely
                    # 一併命中。
                    "abrupt", "acute",
                    # vi-VN
                    "đột ngột", "dữ dội", "đau nhói", "xoắn", "rất đau",
                    "đau lắm", "sưng đau", "quặn",
                    # 2026-07-27 第三輪 Gate 雙向探針補：口語的「突然」與「很嚴重」。
                    # 刻意**不收**「tự nhiên」——它同時是「自然（地）」的常用義，
                    # 單看共現太容易誤配；那些句子多半另有 dữ dội 接得住。
                    "bỗng nhiên", "bỗng dưng", "kinh khủng",
                ],
            }
        ],
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
        # ── 共現組：泌尿症狀／腎區 × 發燒‧畏寒 ───────────────────
        # 2026-07-27 第四輪 Gate 探針：5 語 × 3 種真人語序 **14/15 漏報**
        # （唯一命中的是剛好講出「오한」的那句，靠既有裸關鍵字）：
        #   zh 「我發燒到三十九度而且小便的時候很痛」（『發燒加排尿痛』不相鄰）
        #   en 「I have had a fever of thirty nine since yesterday and burning when I pee」
        #   ja 「昨夜から三十八度台の熱が続いていて排尿のときに痛みがあります」（『高熱』ではない）
        #   ko 「어제부터 열이 삼십구도까지 오르고 소변볼 때 아파요」（『고열』이 아님）
        #   vi 「từ tối qua tôi sốt gần bốn mươi độ và tiểu buốt」（『sốt cao』không liền）
        # 真實病患幾乎不會說「高燒」「고열」這種書面詞，他們報**度數**（「燒到 39 度」）
        # 或用口語（發冷發抖／熱っぽい／rét run）。既有 4 條裸關鍵字接不到任何一種。
        #
        # ⚠️ 本紅旗本質是**跨症狀組合**（全身性感染徵象 ＋ 泌尿感染源），所以兩個維度
        #    不是「部位 × 嚴重度」而是「泌尿症狀 × 發燒/畏寒」。共現組因此比別的紅旗
        #    更容易把兩段不同時間點的敘述配在一起（「上週發燒」＋「今天頻尿」）。
        #    **這在偏誤報政策下是刻意接受的**：專案 memory 記載 urosepsis under-triage
        #    曾經是真實事故成因，誤中止一場問診的代價（護理師走一趟）遠低於漏掉一個
        #    敗血症。距離上限與子句邊界仍然套用，跨句敘述本來就配不起來。
        # 註：明確否認（「我沒有發燒也沒有畏寒」「denies fever and chills」）與時態否定
        #    （「三年前得過腎盂腎炎有發燒，後來完全好了」）仍由 detector 的守衛抑制，
        #    共現組不繞過那些守衛（部位、急性、整段跨度三者都要非否定）。
        "trigger_cooccurrence": [
            {
                "id": "urinary_x_systemic_infection",
                # 跨症狀組合（泌尿症狀 ＋ 全身性感染徵象）＝兩個**不同的**症狀，
                # 病患本來就會講成相鄰兩句（「我發燒到三十九度，而且小便的時候很痛」）。
                # 2026-07-27 第四輪 Gate 實測：有標點版全漏、去標點才命中，純粹是
                # `_pairing_scope_ok` 的子句邊界限制。見該函式的 cross_clause 說明。
                "cross_clause": True,
                "site_terms": [
                    # zh-TW（泌尿症狀與感染源部位；腰／腎區＝腎盂腎炎）
                    "小便", "尿", "排尿", "尿道", "膀胱", "腰", "側腰", "腎",
                    # ja-JP
                    "おしっこ", "排尿", "尿", "膀胱", "腎", "背中", "腰",
                    # ko-KR
                    "소변", "오줌", "배뇨", "방광", "옆구리", "신장",
                    # en-US（両側詞邊界なので語形を列挙）
                    "urine", "urinate", "urinated", "urinating", "urination",
                    "urinary", "pee", "peed", "peeing", "dysuria", "flank",
                    "kidney", "kidneys", "bladder", "catheter",
                    # vi-VN
                    "tiểu", "nước tiểu", "bàng quang", "thận", "hông",
                ],
                # ⚠️ 這一軸是「**全身性**感染徵象」，不是「任何熱的感覺」。
                # 2026-08-18 臨床拍板（session dda55701 實證）：裸「熱」把
                # 「尿完刺刺熱熱」「解尿灼熱感」——排尿局部灼熱（dysuria，泌尿科
                # 最常見主訴之一）——判成 critical 尿路敗血症並中止問診。
                # 病患一講出自己的主訴就被趕走，與 #22 對 gross_hematuria_heavy
                # 的判斷同型（判準要照臨床定義，不是照字面）。
                # 修法：本軸只收**全身性發燒語彙**（發燒/發熱/體溫/畏寒…），
                # 局部灼熱描述（灼熱/刺熱/熱い/熱く/灼熱感）一律不算。
                # 這是**語意修正**不是抑制守衛——規則本意一直是「泌尿症狀 ＋
                # 全身感染徵象」，裸「熱」從來就不是全身徵象。但仍按 #22 舉證：
                # 每個被移除的字面都在下方註明「為什麼不會造成漏報」。
                "acuity_terms": [
                    # zh-TW：發燒（含口語與報度數）／畏寒
                    # 口語體溫上升一律要求**全身性主體錨點**（身體/全身/渾身/額頭），
                    # 這樣「小便很熱」「尿道熱熱的」接不到，而「身體很熱」接得到。
                    "發燒", "高燒", "燒到", "燒起來", "燒了", "在燒",
                    "發熱", "度的燒", "體溫",
                    "身體很熱", "身體熱", "全身很熱", "全身熱",
                    "渾身很熱", "渾身熱",
                    "身體發燙", "全身發燙", "額頭發燙",
                    "畏寒", "寒顫", "發冷", "打冷顫", "冷到發抖", "忽冷忽熱",
                    "全身發抖", "意識不清",
                    # ja-JP：裸「熱」は 2026-08-18 に削除（「熱い/熱く/灼熱感」＝
                    # 排尿時の局所灼熱感を全部拾ってしまう。しかも本表は**全言語の
                    # 和集合**なので、中国語の「灼熱／熱熱的」まで巻き込んでいた）。
                    # 発熱用法は助詞・接尾を付けて個別収録する（「熱い」は助詞が
                    # 付かないので確実に外れる）。
                    "発熱", "高熱", "微熱", "熱っぽ",
                    "熱が", "熱も", "熱で", "熱です", "熱でした", "熱を出",
                    "度の熱",
                    "悪寒", "寒気", "震え", "体温", "ふるえ",
                    # ko-KR（裸「열」は「열쇠/열심히」に当たるので助詞付きで収録）
                    # 2026-08-18 五語審視：**現状維持**。排尿時の局所灼熱は韓国語では
                    # 화끈거리다／따갑다／쓰라리다／작열감 で表現され、「열감」も
                    # 「열이/열도/열은/열나」のどれにも当たらない（実測 0 誤爆）。
                    # 残余の周辺例（「열나는 느낌」「열이 나는 것처럼 화끈」）は
                    # 判断がつかないので #22 に従い**触らない**（誤報側に倒す）。
                    "열이", "열도", "열은", "열나", "고열", "발열", "미열",
                    "오한", "한기", "떨리", "몸살", "덜덜",
                    # en-US（前緣詞邊界：fever/fevers/feverish、chill/chills、shiver/shivering）
                    # 2026-08-18 五語審視：**維持現狀**。dysuria 的英文說法
                    # （burning when I pee / burning sensation / stings / hot）
                    # 一律不在本表（實測 0 誤報）。`burning up` 只有在
                    # 「my urethra is burning up」這種造作語序才會誤配；要擋掉必須
                    # 加主語錨點（i'm / am），那會同時丟掉「the patient is burning up」
                    # 「he's burning up」＝製造漏報，舉證責任（#22）過不了 → 保留。
                    "fever", "febrile", "chill", "shiver", "shaking", "rigor",
                    "temperature", "hot and cold", "burning up", "sepsis",
                    "septic", "confused and",
                    # vi-VN
                    # 2026-08-18 五語審視：**維持現狀**。局部灼熱是 `nóng rát`／`rát`／
                    # `buốt`，而裸 `nóng` 本來就不在表內（只收複合的 `nóng lạnh`
                    # ＝忽冷忽熱），實測 0 誤報。殘餘的 `sốt ruột`（＝著急，不是發燒）
                    # 屬於**慣用語同形**不是局部灼熱同型，且本比對引擎沒有排除語法，
                    # 移除 `sốt` 會把最主要的越南文發燒詞整個丟掉 → 保留。
                    "sốt", "ớn lạnh", "rét", "run lạnh", "lạnh run", "nóng lạnh",
                    "nhiễm trùng",
                ],
            }
        ],
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
        # ── 共現組：膀胱功能障礙 × 鞍區感覺異常／下肢無力 ──────────
        # 2026-07-27 第四輪 Gate 探針：5 語 × 3 種真人語序 **15/15 全數漏報**
        #   zh 「屁股跟大腿內側這兩天都麻麻的，小便也開始會漏出來」（『會陰麻木』是書面詞）
        #   zh 「腰痛得很厲害兩隻腳越來越沒力昨天開始尿失禁」（『下肢無力』→『腳沒力』）
        #   en 「my inner thighs have gone numb and I have been leaking urine since yesterday」
        #   ja 「お尻の周りがしびれていて昨日から尿を漏らすようになりました」
        #   ko 「엉덩이랑 사타구니가 저리고 어제부터 소변이 새요」
        #   vi 「vùng bẹn tê bì và từ hôm qua tôi bị són tiểu」
        # 病患不會講「會陰」「下肢」「鞍區」，他們講屁股／大腿內側／胯下／腳沒力。
        #
        # 臨床依據：馬尾症候群的紅旗定義本身就是**組合**——鞍區感覺異常或下肢無力，
        # **合併**新發的膀胱功能障礙（失禁或滯留）。所以兩個維度就照這個定義切：
        #   site_terms  = 膀胱功能障礙（失禁／漏尿／尿不出）
        #   acuity_terms = 神經缺損（麻木／感覺變差／無力）
        # 單獨一邊都不是本紅旗（單純尿失禁＝主訴選單上的常見良性主訴；單純腳麻＝骨科），
        # 兩者同一子句共現才是需要緊急 MRI 的形狀。
        #
        # ⚠️ site_terms 含「尿失禁／요실금／tiểu không tự chủ」＝主訴選單標籤，這在
        #    testicular_pain_severe 是被結構性禁止的；本紅旗不同，因為配對的另一維度
        #    （神經缺損）**不在**任何主訴標籤裡，病患複誦主訴標籤不可能單獨觸發。
        #    對應的結構不變式改寫成「兩張表至少有一張完全不含主訴標籤」，
        #    見 test_red_flag_cooccurrence_coverage.py。
        # ⚠️ 「cannot control / can't control / no control」刻意收進 site：
        #    「I cannot control my bladder」裡的 bladder 被「not 」否定守衛抹掉，
        #    只有讓詞條**從否定詞本身開始**才接得住（與 urinary_retention 同一道理）。
        "trigger_cooccurrence": [
            {
                "id": "bladder_dysfunction_x_neuro_deficit",
                # 跨症狀組合（膀胱功能障礙 ＋ 神經學缺損）——同 urinary_x_systemic_infection
                # 的理由：「腰痛得很厲害，兩隻腳越來越沒力，昨天開始尿失禁」是最自然的
                # 講法，兩個維度天生落在不同子句。
                "cross_clause": True,
                "site_terms": [
                    # zh-TW（膀胱功能障礙）
                    "尿失禁", "小便失禁", "大小便失禁", "失禁", "漏尿", "漏出來",
                    "尿褲子", "尿在褲", "憋不住", "尿不出來", "解不出",
                    # ja-JP
                    "尿失禁", "失禁", "漏らす", "漏らし", "尿漏れ", "漏れて",
                    "おもらし",
                    # ko-KR
                    "요실금", "실금", "소변이 새", "소변을 지", "지렸", "소변을 못",
                    # en-US
                    "incontinence", "incontinent", "leaking", "leaked",
                    "wet", "wetting", "accidents", "bladder",
                    "cannot control", "can't control", "no control",
                    "lost control", "losing control",
                    # vi-VN
                    "són tiểu", "tiểu không tự chủ", "rỉ nước tiểu", "tiểu dầm",
                    "không nhịn được tiểu", "không giữ được nước tiểu",
                    "mất kiểm soát",
                ],
                "acuity_terms": [
                    # zh-TW（鞍區感覺異常／下肢無力。裸「麻」不收——「很麻煩」會誤配）
                    "麻木", "麻掉", "發麻", "麻麻", "麻痺", "麻了", "麻感",
                    "腳麻", "腿麻", "手麻", "沒知覺", "沒有知覺", "感覺遲鈍",
                    "感覺變差", "無感覺", "無力", "沒力", "使不上力", "軟腳",
                    "癱", "站不穩",
                    # ja-JP
                    "しびれ", "痺れ", "麻痺", "感覚が鈍", "感覚がにぶ", "感覚がない",
                    "力が入らな", "脱力", "動かしにく", "ふらつ",
                    # ko-KR
                    "저림", "저리", "감각이 없", "감각이 둔", "감각 이상", "감각이 이상",
                    "힘이 빠", "마비", "무감각", "다리에 힘",
                    # en-US（前緣詞邊界：numb/numbness、weak/weakness、tingl/tingling）
                    "numb", "tingl", "pins and needles", "no feeling",
                    "loss of sensation", "weak", "giving way", "buckl",
                    "paralys", "saddle",
                    # vi-VN
                    "tê", "mất cảm giác", "yếu", "liệt", "châm chích",
                    "không có cảm giác",
                ],
            }
        ],
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
        # 顏色詞與「血的存在」掛在 high 這一層（不中止問診，只發警示）。
        # 這一組同時補掉單詞 trigger 接不到的語序：en 的 "blood in **my** urine"
        # 所有格、zh 的「尿裡面有一點血」等中間插字的說法。量與血塊在
        # gross_hematuria_heavy(critical)，RED_FLAG_SUPERSEDES 會讓父蓋子。
        "trigger_cooccurrence": [
            {
                "id": "urine_x_blood_present",
                "site_terms": [
                    # zh-TW
                    "尿", "小便", "馬桶", "尿液",
                    # ja-JP
                    "おしっこ", "小水", "トイレ",
                    # ko-KR
                    "소변", "오줌",
                    # en-US
                    "urine", "urinate", "urinated", "urinating", "urination",
                    "pee", "peed", "peeing", "toilet",
                    # vi-VN
                    "tiểu", "nước tiểu",
                ],
                "acuity_terms": [
                    # zh-TW — 顏色／血的存在（不是量）
                    "整片紅", "整個都紅", "尿血", "血水", "有血", "帶血",
                    "混著血", "鮮紅", "紅色",
                    # ja-JP
                    "真っ赤", "血の混じ", "血が混", "赤い",
                    # ko-KR
                    "새빨", "피가 섞", "피가 나", "빨개", "붉",
                    # en-US
                    "bright red", "dark red", "completely red", "bloody",
                    "gross blood", "blood", "red",
                    # vi-VN
                    "đỏ tươi", "đỏ sẫm", "có máu", "ra máu", "đỏ",
                ],
            }
        ],
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


# =============================================================================
# 紅旗父子關係（父命中 → 抑制子）
# =============================================================================
# 問題：同一句「大量血尿」同時命中 gross_hematuria_heavy(critical) 與
# gross_hematuria(high)——兩者是**同一個臨床實體的兩個嚴重度**，但 canonical_id
# 不同，`_merge_and_deduplicate` 以 canonical_id 為 key 故不會合併 → 兩筆 DB 列、
# 兩則 WS 事件、dashboard 兩條未確認警示、research analytics 的紅旗計數灌水。
#
# 安全性（為何不會漏掉真紅旗）：被抑制的一律是**同一實體中較低嚴重度**的那筆，
# 且僅在較高嚴重度的父紅旗同輪已經命中、會被持久化+廣播時才抑制。護理站看到的
# 是嚴重度較高、處置更積極的那則，臨床行動不會因此變少（子紅旗的 suggested_actions
# 會併入父紅旗，避免處置建議掉字）。
# ⚠️ 只可放「子 ⊂ 父、且父的處置涵蓋子」的組合；不同器官/機轉的紅旗絕不可放進來。
RED_FLAG_SUPERSEDES: dict[str, tuple[str, ...]] = {
    # 大量血尿(critical) 涵蓋 肉眼血尿(high)：同為血尿，前者只是量更大/有血塊。
    "gross_hematuria_heavy": ("gross_hematuria",),
}


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
