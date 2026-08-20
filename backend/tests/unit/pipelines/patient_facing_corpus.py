"""
病患面措辭語料庫 —— **獨立於實作**的測試 oracle。

## 為什麼要有這個檔

前一輪的測試用實作自己的 regex（`_PATIENT_FACING_RESIDUAL`）當判準，
變成循環斷言：偵測器漏掉的句型，測試也一定跟著漏掉。結果 2804 個 unit test
全綠，真跑 `torsion_critical_zh` 的 t8 照樣 FAIL（LLM 寫成
「需立即進行超音波檢查和泌尿科急診評估」，副詞與地點相隔 11 字，
`{0,8}` 的距離上限接不住）。

所以本檔的判準是**手寫的字面片語清單**（`LEAVE_SITE_MARKERS`），
不 import 任何 `app.pipelines.soap_generator` 的規則。實作換 regex、換策略，
這份清單都不會跟著變——這才是獨立 oracle。

## 判準（跟實作註解一致，但這裡是人工維護的字面清單）

違規 ＝「要病患**離開現場、自己跑去別的地方求醫**」或「自己叫救護車」。
不違規 ＝ 描述**院方／現場醫護會做什麼**。
    「醫師會為您安排急診評估」→ 合規（沒有叫他離場）
    「需立即前往急診評估」    → 違規
裸詞「急診 / 急診評估 / 응급 / cấp cứu」**不列入** marker——
把它一律當違規會誤傷「已通知急診團隊」「醫師會安排急診評估」這類合規句。

### 裸名詞的取捨（一個已知且刻意的不對稱）

marker 清單裡仍收了幾個裸英文／日文名詞（`emergency room`、`emergency department`、
`急診室`、`救急外来`）。理由是後端在**自己的輸出**上採保守立場——
`scripts/e2e_realopenai/driver.py` 的 `SELF_REFERRAL_RULES` 註解明文記載這個
分工：驗收端不收裸名詞（否則「已通知急診室」會被判違規），後端消毒層收。

代價是：「The urologist will come to the emergency department shortly.」這種
**院方施事**的良性句含字面 marker，放進 `COMPLIANT_CORPUS` 會讓
「反例不含 marker」與「marker 命中即違規」兩個判準互相矛盾。
所以這類句子不進本檔語料，改由 `test_clinic_side_movement_verbs_are_not_violations`
單獨斷言（實作對它走施事者豁免、不會改寫）。

## 語料來源標記（provenance）

`realrun`   逐字取自 `scripts/e2e_realopenai/results/*.json` 的 SOAP 欄位，
            或第一輪覆核記錄下來的真跑輸出。
`paraphrase` 本輪新寫：同一個違規語意、**刻意換一套措辭**（更長的插入語、
            同義副詞、被動句、跨小句），用來證明規則涵蓋的是「句型族」
            而不是被實作配適出來的特定字串。這些句子不存在於
            `scripts/e2e_realopenai/driver.py` 的任何腳本台詞或斷言清單裡。
`minimalpair` 與某條違規句只差一個施事者標記的良性句，用來釘住
            「有沒有叫他離場」這條界線不會因為收緊/放寬規則而漂移。
"""

# ══════════════════════════════════════════════════════════
# 獨立 oracle：出現在病患面欄位就是違規的字面片語
# ══════════════════════════════════════════════════════════
#
# 人工維護。新增規則時**不准**為了讓測試過而刪這裡的項目——
# 要刪必須先說明為什麼這個片語對候診中的病患不再是「叫他離場」。
LEAVE_SITE_MARKERS: tuple[str, ...] = (
    # zh — 叫他自己去求醫
    "立即就醫", "立刻就醫", "馬上就醫", "盡速就醫", "儘速就醫", "盡快就醫",
    "儘快就醫", "趕快就醫", "趕緊就醫", "從速就醫", "盡早就醫", "儘早就醫",
    "立即就診", "盡速就診", "盡快就診", "立即求診", "盡速求診",
    "立即看醫生", "趕快看醫生", "馬上找醫生",
    # zh — 叫他自己去某個地點
    "前往急診", "至急診", "到急診", "去急診", "掛急診", "轉往急診",
    "立即急診", "立刻急診", "馬上急診", "盡快急診", "儘快急診",
    "趕快去醫院", "馬上去醫院", "立即前往醫院", "盡速前往醫院",
    "自行前往", "自行就醫", "自行就診", "自己去醫院",
    # zh — 叫他自己叫救護車
    "叫救護車", "呼叫救護車", "撥打119", "撥打 119", "打119",
    # en
    "seek immediate medical", "seek urgent medical", "seek emergency",
    "immediate medical attention", "urgent medical attention",
    "go to the er", "go to the emergency", "head to the emergency",
    "emergency room", "emergency department",
    "call 911", "dial 911", "call an ambulance",
    # ja
    "直ちに受診", "ただちに受診", "すぐに受診", "至急受診", "早急に受診",
    "救急外来", "救急車を呼",
    # ko
    "즉시 진료를 받", "바로 진료를 받", "빨리 진료를 받",
    "응급실로 가", "응급실에 가", "119에 신고", "구급차를 부르",
    # vi
    "đi khám ngay", "đến bệnh viện", "đi cấp cứu", "đến khoa cấp cứu",
    "gọi xe cấp cứu",
    # ── SO-1（2026-08-20）：時間窗型離場指示 ──────────────
    # `plan.urgency` 的四個 enum 被 LLM 翻成白話後的等價句。稽核實測 6/6 放行：
    # 前一版的 marker 只收「急迫副詞 + 求醫動詞」，接不住「請於 24 小時內就醫」
    # 這種把急迫度寫成**時間窗**的版本。指定時限叫病患自己去求醫，
    # 對候診中的病患一樣是叫他離場。
    # 片語刻意留成「時間窗尾 + 求醫動詞」的形狀（如「小時內就醫」），
    # 才能同時吃到「24 小時內就醫」「48小時內就醫」等變體。
    "小時內就醫", "小時內就診", "小時內求診",
    "天內就醫", "天內就診", "天內看醫生",
    "週內就醫", "週內就診", "周內就醫", "周內就診",
    "當天就醫", "當天就診", "今天就醫", "今日就醫", "明天就醫",
    "聯絡您的家庭醫師", "聯繫您的家庭醫師", "聯絡家庭醫師",
    "see a doctor within", "see your doctor within", "visit a clinic this week",
    "contact your family doctor within", "see a doctor today",
    # ⚠️ 刻意**不收**裸的「今週中に」「이번 주 안에」——那是純時間詞，
    # 「今週中は激しい運動を控え…」「이번 주 안에는 무리한 운동을 피해…」
    # 都是合規衛教，收了會讓 oracle 與反例語料互相矛盾。
    # 時間窗只有**接上求醫動作**才是禁語。
    "時間以内に受診", "以内に受診",
    "시간 이내에 진료", "주 안에 진료",
    "đi khám trong vòng", "gặp bác sĩ trong tuần",
)


def leave_site_markers_in(text: str) -> list[str]:
    """獨立 oracle 本體：回傳文字中命中的『叫病患離場』片語（不碰實作 regex）。"""
    low = (text or "").lower()
    return [m for m in LEAVE_SITE_MARKERS if m.lower() in low]


# 消毒後**必須**出現的「找現場醫護」指向詞。
#
# 為什麼要有這一條：上面的 `LEAVE_SITE_MARKERS` 只能抓字面禁語，但本輪修的
# 那一族違規（「需立即進行超音波檢查和泌尿科急診評估」「to be seen by a
# urologist at a hospital without delay」）根本不含任何字面禁語——只驗
# 「消毒後沒有禁語」的話，消毒層什麼都不做也會過。所以正例要雙向驗：
#   (a) 沒有殘留 LEAVE_SITE_MARKERS，且
#   (b) 真的被導向現場醫護（下面這串字面）。
# 這串字是**病患畫面上的產品文案**，本來就不該無聲漂移；改文案要連這裡一起改。
ON_SITE_REDIRECT_MARKERS: dict[str, str] = {
    "zh-TW": "現場醫護人員",
    "en-US": "on-site clinical staff",
    "ja-JP": "現場の医療スタッフ",
    "ko-KR": "현장 의료진",
    "vi-VN": "nhân viên y tế tại chỗ",
}


# ══════════════════════════════════════════════════════════
# 正例：**必須**被消毒的句子
# ══════════════════════════════════════════════════════════
# (provenance, language, text)
LEAVE_SITE_CORPUS: tuple[tuple[str, str, str], ...] = (
    # ── 真跑輸出（逐字）──────────────────────────────────
    (
        "realrun",
        "zh-TW",
        "30歲男性患者，主訴左邊睪丸突然劇烈疼痛，伴隨陰囊腫脹和噁心，症狀持續約兩小時。"
        "高度懷疑睪丸扭轉，需立即進行超音波檢查和泌尿科急診評估。",
    ),  # torsion_critical_zh summary — 就是這句讓 t8 FAIL
    (
        "realrun",
        "zh-TW",
        "若出血加重或出現疼痛、頭暈、排尿困難，立即就醫。",
    ),  # hematuria_3b_en plan.patient_education[0]
    (
        "realrun",
        "zh-TW",
        "解釋血尿可能的原因及重要性，強調需立即就醫。",
    ),  # intake_wiring_zh plan.patient_education（第一輪）
    (
        "realrun",
        "zh-TW",
        "30歲男性，主訴左邊睪丸突然劇烈疼痛，伴隨陰囊腫脹和噁心，症狀開始於兩小時前。"
        "紅旗徵象顯示可能為睪丸扭轉，需立即急診評估。",
    ),  # torsion_critical_zh summary（第一輪短版）

    # ── 新寫的改述：同語意、不同措辭 ─────────────────────
    # 重點在「副詞與地點之間塞很長的插入語」——距離上限式規則一定漏。
    (
        "paraphrase",
        "zh-TW",
        "考量症狀有缺血壞死的風險，建議儘速安排至鄰近設有泌尿科的醫療院所接受評估。",
    ),
    (
        "paraphrase",
        "zh-TW",
        "由於病情可能急速惡化，請於離開本院後第一時間前往設有 24 小時服務的急診室。",
    ),
    (
        "paraphrase",
        "zh-TW",
        "若夜間症狀復發而門診已關閉，請自行前往鄰近醫院掛號。",
    ),
    (
        "paraphrase",
        "zh-TW",
        "疼痛若在返家途中加劇，請家屬立即協助您到大醫院就診。",
    ),
    (
        "paraphrase",
        "zh-TW",
        "萬一出現昏厥或意識改變，請家人撥打 119 求助。",
    ),
    (
        "paraphrase",
        "zh-TW",
        "此症具時效性，越快越好地接受泌尿科醫師診療對保住睪丸功能至關重要。",
    ),
    (
        "paraphrase",
        "en-US",
        "Because torsion is time-critical, please arrange without delay to be seen "
        "by a urologist at a hospital.",
    ),
    (
        "paraphrase",
        "en-US",
        "Should the bleeding become heavier overnight, proceed to the nearest "
        "emergency department for assessment.",
    ),
    (
        "paraphrase",
        "en-US",
        "If you lose consciousness at home, have a family member dial 911.",
    ),
    (
        "paraphrase",
        "ja-JP",
        "症状が長引く場合は、できるだけ早く泌尿器科のある医療機関を受診してください。",
    ),
    (
        "paraphrase",
        "ja-JP",
        "夜間に激しい痛みが再発したときは、救急外来までお越しください。",
    ),
    (
        "paraphrase",
        "ko-KR",
        "통증이 다시 심해지면 지체 없이 비뇨의학과가 있는 병원에서 진료를 받으시기 바랍니다.",
    ),
    (
        "paraphrase",
        "ko-KR",
        "밤사이 상태가 나빠지면 가까운 응급실로 가세요.",
    ),
    (
        "paraphrase",
        "vi-VN",
        "Vì tình trạng này diễn tiến nhanh, xin hãy đến bệnh viện có chuyên khoa "
        "tiết niệu càng sớm càng tốt.",
    ),
    (
        "paraphrase",
        "vi-VN",
        "Nếu cơn đau tái phát vào ban đêm, hãy gọi xe cấp cứu.",
    ),

    # ── 第二批改述：又換一輪措辭（敬語、被動、裸祈使、跨小句）──
    ("paraphrase", "zh-TW", "如果今天下午症狀沒有改善，麻煩您到附近的醫院再看一次。"),
    ("paraphrase", "zh-TW", "建議您結束今天的看診後，儘早至泌尿專科醫院安排手術評估。"),
    ("paraphrase", "zh-TW", "病情變化快速，請不要等待，直接掛急診。"),
    ("paraphrase", "zh-TW", "如有發燒合併腰痛，應立即至醫院急診接受抗生素治療。"),
    ("paraphrase", "zh-TW", "若您無法在本院候診，也請務必當天到其他醫院就醫。"),
    ("paraphrase", "zh-TW", "症狀復發時請直接前往急診。"),  # 裸祈使、無急迫副詞
    (
        "paraphrase",
        "en-US",
        "If the pain returns tonight, seek urgent medical care at your nearest hospital.",
    ),
    (
        "paraphrase",
        "en-US",
        "Symptoms like these warrant immediate evaluation at an emergency room.",
    ),
    (
        "paraphrase",
        "en-US",
        "Have a family member drive you to the hospital right away.",
    ),
    (
        "paraphrase",
        "en-US",
        "Come to the emergency room immediately if you feel faint.",
    ),
    ("paraphrase", "ja-JP", "痛みが強まる場合は、大至急、近くの病院へ行ってください。"),
    ("paraphrase", "ko-KR", "증상이 계속되면 즉시 가까운 병원에서 진료를 받으십시오."),
    (
        "paraphrase",
        "vi-VN",
        "Nếu tiểu ra máu nhiều hơn, hãy đi khám ngay tại bệnh viện gần nhất.",
    ),

    # ══ SO-1（2026-08-20 稽核）：時間窗型離場指示 ═══════════
    #
    # 判準沒有變——依然是「有沒有叫病患自行離場」——變的是 LLM 的措辭：
    # 它把 `plan.urgency` 的 enum 直接翻成白話塞進病患面欄位。
    # 這一族**成組**穿透了消毒層（稽核實測 6/6 放行），因為舊規則只認
    # 「立即／盡速」這類副詞，不認「24 小時內／本週內／當天」這類時間窗。
    # 下面按 enum 分組列出，確保四個 urgency 值的自然語言等價句都有覆蓋。

    # ── urgency=er_now 的白話版（時間窗＝當天／今天）──
    ("paraphrase", "zh-TW", "這種情況屬於急症，請當天就醫，不要拖到明天。"),
    ("paraphrase", "zh-TW", "今天就醫對保住睪丸功能至關重要，不要等到症狀自行緩解。"),
    # ── urgency=24h 的白話版 ──
    ("paraphrase", "zh-TW", "請於 24 小時內就醫，讓醫師評估是否需要進一步處置。"),
    ("paraphrase", "zh-TW", "建議在 24 小時內就診泌尿科，以免延誤治療。"),
    ("paraphrase", "zh-TW", "若明天早上仍有血尿，請於一天內就醫檢查。"),
    # ── urgency=this_week 的白話版 ──
    ("paraphrase", "zh-TW", "建議本週內就診，安排尿液細胞學檢查。"),
    # ⚠️ 無祈使詞的陳述句：不靠「請／建議」那條 HARD 規則，
    # 只靠「時間窗 × 自行求醫」的共現組。注入式回歸驗過——把
    # 「本週內」從 `_ZH_DEADLINE` 拿掉，只有這一句會紅。
    ("paraphrase", "zh-TW", "本週內就診可以及早排除膀胱腫瘤的可能。"),
    ("paraphrase", "zh-TW", "48 小時內就醫是這種疼痛的標準處理方式。"),
    ("paraphrase", "zh-TW", "請在這週內找醫生做進一步追蹤。"),
    ("paraphrase", "zh-TW", "建議三天內就醫複查尿液，確認血尿是否已經改善。"),
    # ── urgency=routine 的白話版：轉介到別的醫療提供者 ──
    ("paraphrase", "zh-TW", "請盡速聯絡您的家庭醫師安排後續追蹤。"),
    ("paraphrase", "zh-TW", "後續請聯絡您的家庭醫師，於下週內安排尿液複檢。"),
    (
        "paraphrase",
        "en-US",
        "Please see a doctor within 24 hours if the bleeding continues.",
    ),
    (
        "paraphrase",
        "en-US",
        "Contact your family doctor within the next two days to arrange follow-up.",
    ),
    (
        "paraphrase",
        "en-US",
        "You should visit a clinic this week for a repeat urine test.",
    ),
    ("paraphrase", "ja-JP", "血尿が続く場合は、24時間以内に受診してください。"),
    ("paraphrase", "ja-JP", "今週中に泌尿器科を受診するようにしてください。"),
    (
        "paraphrase",
        "ko-KR",
        "증상이 계속되면 24시간 이내에 진료를 받으시기 바랍니다.",
    ),
    ("paraphrase", "ko-KR", "이번 주 안에 비뇨의학과에서 진료를 받으세요."),
    (
        "paraphrase",
        "vi-VN",
        "Nếu tình trạng kéo dài, xin hãy đi khám trong vòng 24 giờ.",
    ),
    (
        "paraphrase",
        "vi-VN",
        "Bạn nên gặp bác sĩ trong tuần này để kiểm tra lại nước tiểu.",
    ),
)


# ══════════════════════════════════════════════════════════
# 反例：**一個字都不准動**的句子
# ══════════════════════════════════════════════════════════
COMPLIANT_CORPUS: tuple[tuple[str, str, str], ...] = (
    # ── 真跑輸出（逐字，全部合規）────────────────────────
    (
        "realrun",
        "zh-TW",
        "建議患者記錄每日排尿次數和飲水量，以便醫師進一步評估。",
    ),  # dontknow_zh
    ("realrun", "zh-TW", "解釋頻尿可能的原因及檢查的重要性。"),  # dontknow_zh
    (
        "realrun",
        "zh-TW",
        "68 歲男性患者主訴頻尿，白天排尿約 10 到 12 次，夜間起床上廁所約 3 次。"
        "無尿急、尿痛、血尿或發燒。症狀在久坐後加重。考慮良性前列腺增生可能性較高，"
        "建議進行尿液分析、PSA 檢測及膀胱超音波以進一步評估。",
    ),  # dontknow_zh summary
    (
        "realrun",
        "zh-TW",
        "請稍候等待看診，若症狀加重，請立即告知現場醫護人員。",
    ),  # ed_3b_zh / intake_wiring_zh / torsion_critical_zh patient_education
    (
        "realrun",
        "zh-TW",
        "若出現疼痛、頭暈、排尿困難，請立即告知現場醫護人員。",
    ),  # intake_wiring_zh patient_education[1]
    ("realrun", "zh-TW", "建議減少抽菸，並注意控制血壓及血糖。"),  # ed_3b_zh
    (
        "realrun",
        "zh-TW",
        "55 歲男性，主訴勃起功能障礙，持續一年，伴有高血壓及長期抽菸史。"
        "症狀在壓力大時加重，需進一步檢查心血管及心理因素。",
    ),  # ed_3b_zh summary
    (
        "realrun",
        "zh-TW",
        "61歲男性患者主訴3天前開始出現肉眼血尿，無疼痛或其他症狀。"
        "患者有長期吸煙史，無泌尿道問題或手術史，無家族癌症史。"
        "需進行尿液分析及膀胱鏡檢查以排除膀胱癌等嚴重病因。",
    ),  # hematuria_3b_en summary
    (
        "realrun",
        "zh-TW",
        "76歲男性，主訴三天前開始出現肉眼血尿，無疼痛或其他伴隨症狀。"
        "病史包括高血壓、第二型糖尿病，並有膀胱癌家族史。病患長期抽菸。"
        "建議進行尿液分析、泌尿系統超音波及膀胱鏡檢查以排除腫瘤可能。",
    ),  # intake_wiring_zh summary

    # ── minimal pair：與正例只差一個「施事者是院方」的標記 ──
    (
        "minimalpair",
        "zh-TW",
        "醫師會為您安排急診評估，請在原位稍候。",
    ),  # 覆核點名：裸詞「急診評估」不該被替換
    (
        "minimalpair",
        "zh-TW",
        "現場醫護人員會立即為您安排超音波檢查與泌尿科急診評估。",
    ),  # 對照「需立即進行超音波檢查和泌尿科急診評估」
    (
        "minimalpair",
        "zh-TW",
        "本院會儘速為您安排檢查，請留在候診區等待叫號。",
    ),  # 對照「建議儘速安排至鄰近…醫療院所接受評估」
    (
        "minimalpair",
        "zh-TW",
        "我們已通知急診團隊，稍候會有人員帶您過去。",
    ),
    (
        "minimalpair",
        "en-US",
        "The on-site clinical team will arrange an urgent urology assessment for you; "
        "please wait here.",
    ),
    (
        "minimalpair",
        "ja-JP",
        "現場の医療スタッフが救急の評価を手配いたしますので、そのままお待ちください。",
    ),
    (
        "minimalpair",
        "ko-KR",
        "현장 의료진이 응급 평가를 준비하고 있으니 이곳에서 기다려 주세요.",
    ),
    (
        "minimalpair",
        "vi-VN",
        "Nhân viên y tế tại chỗ sẽ sắp xếp đánh giá khẩn cho bạn, xin vui lòng chờ đến lượt.",
    ),

    # ── 其他合規衛教（新寫）──────────────────────────────
    ("paraphrase", "zh-TW", "多喝水（每日 2000ml 以上），避免劇烈運動，並觀察尿液顏色變化。"),
    ("paraphrase", "zh-TW", "睪丸扭轉是需要緊急處理的情況，若不及時處理可能導致睪丸壞死。"),
    ("paraphrase", "zh-TW", "請留在候診區，不要自行離開，以免錯過叫號。"),
    ("paraphrase", "zh-TW", "住院期間的飲食與活動安排，會由病房護理師另行說明。"),
    ("paraphrase", "zh-TW", "下次門診回診時，請把這段期間的排尿紀錄一併帶來。"),
    ("paraphrase", "en-US", "Drink at least 2000 ml of water daily and avoid strenuous exercise."),
    ("paraphrase", "en-US", "This intake is complete. Please wait here; the on-site staff will call you."),

    # ── 誤觸防線：裸數字、裸名詞不得被當成違規 ─────────────
    ("paraphrase", "zh-TW", "血壓 119/79 mmHg，屬正常範圍。"),
    ("paraphrase", "en-US", "Your blood pressure was 119/79 mmHg, which is within the normal range."),
    ("paraphrase", "en-US", "Creatinine 911 µmol/L was recorded at the outside clinic."),
    ("paraphrase", "ko-KR", "혈압은 119/79 mmHg로 정상 범위입니다."),
    (
        "paraphrase",
        "vi-VN",
        "Tình trạng này đã được nhân viên y tế tại chỗ ghi nhận là cần cấp cứu.",
    ),

    # ── 第二批反例：與上面第二批正例配對的「院方施事」與「非離場」句 ──
    # 每一條都刻意含有正例規則裡的關鍵詞（急診／醫院／病院／병원／bệnh viện／
    # hospital／盡快／促迫副詞），用來釘死「有關鍵詞 ≠ 違規」這條界線。
    ("paraphrase", "zh-TW", "醫師會盡快為您診療，請在候診區稍候。"),
    ("paraphrase", "zh-TW", "檢查結果會由醫師在門診時向您說明。"),
    ("paraphrase", "zh-TW", "本院泌尿科今日有門診，護理師會協助您安排掛號。"),
    ("paraphrase", "zh-TW", "如果住院期間有任何不適，請按鈴通知護理師。"),
    ("paraphrase", "zh-TW", "這項檢查在本院急診就能完成，不需要另外跑一趟。"),
    ("paraphrase", "zh-TW", "急診評估的結果會併入今天的病歷。"),
    ("paraphrase", "zh-TW", "戒菸是降低膀胱癌風險最有效的方式，建議盡快開始。"),
    ("paraphrase", "zh-TW", "請盡快完成尿液採檢，檢體桶就在洗手間旁邊。"),
    ("paraphrase", "zh-TW", "若您已在其他醫院做過超音波，請提供報告供醫師參考。"),
    ("paraphrase", "zh-TW", "下次回到醫院複診時，請帶著這份報告。"),
    ("paraphrase", "zh-TW", "我們已經聯繫急診團隊，稍候會有人員陪同您過去。"),
    ("paraphrase", "zh-TW", "至少每天喝水 2000 毫升。"),
    ("paraphrase", "en-US", "The urologist will review your results shortly."),
    ("minimalpair", "en-US", "A nurse will come and collect you for the scan."),
    # ⚠️「The urologist will come to the emergency department shortly.」這類
    # 「院方施事 ＋ 裸英文 ER 名詞」的句子**刻意不放進本清單**：它含字面
    # marker `emergency department`，會與 `LEAVE_SITE_MARKERS` 互斥（見上面
    # 「裸名詞的取捨」）。該行為由 test_soap_patient_facing_wording.py 的
    # test_clinic_side_movement_verbs_are_not_violations 單獨釘住。
    ("paraphrase", "en-US", "Your ultrasound has been booked in this hospital for later today."),
    (
        "paraphrase",
        "en-US",
        "Please discuss your smoking history with the doctor during today's visit.",
    ),
    ("paraphrase", "ja-JP", "検査結果は本日中に担当医からご説明いたします。"),
    ("paraphrase", "ja-JP", "水分をこまめに取り、激しい運動は控えてください。"),
    ("paraphrase", "ko-KR", "검사 결과는 오늘 진료 때 의사가 설명해 드립니다."),
    ("paraphrase", "ko-KR", "수분을 충분히 섭취하고 무리한 운동은 피하세요."),
    (
        "paraphrase",
        "vi-VN",
        "Kết quả xét nghiệm sẽ được bác sĩ giải thích trong buổi khám hôm nay.",
    ),
    ("paraphrase", "vi-VN", "Hãy uống nhiều nước và tránh vận động mạnh."),

    # ══ SO-1 的反向側：時間窗**不是**禁語 ═══════════════════
    #
    # 與上面新增的時間窗正例一一對應。豁免判準沒有變、也不會變：
    # **施事者是誰**。「醫師會在 24 小時內完成報告」的動作者是院方，
    # 病患一步都不用移動；「請於 24 小時內就醫」的動作者是病患本人。
    # 只往正例加斷言就是在替下一次擺盪鋪路（skill 測試設計第 1 點），
    # 所以每一組時間窗都要有對照的良性句釘住界線。
    ("minimalpair", "zh-TW", "醫師會在 24 小時內完成報告，請稍候等待看診。"),
    ("minimalpair", "zh-TW", "現場醫護人員會在 24 小時內回覆您的檢查結果。"),
    ("minimalpair", "zh-TW", "醫師會為您安排急診評估，本週內會有正式報告。"),
    ("minimalpair", "zh-TW", "檢查報告預計三天內完成，屆時由主治醫師向您說明。"),
    ("paraphrase", "zh-TW", "今天的門診由王醫師負責，護理師會協助您完成報到。"),
    ("paraphrase", "zh-TW", "這一週內請照常服用原本的降血壓藥物。"),
    ("paraphrase", "zh-TW", "當天的尿量與飲水量請記錄下來，供醫師參考。"),
    (
        "minimalpair",
        "en-US",
        "The doctor will review your results within 24 hours; please wait here.",
    ),
    (
        "minimalpair",
        "en-US",
        "Our team will contact you later today with the scan results.",
    ),
    (
        "paraphrase",
        "en-US",
        "Keep a record of how much you drink today and bring it to the consultation.",
    ),
    ("minimalpair", "ja-JP", "検査結果は24時間以内に担当医からご連絡いたします。"),
    ("paraphrase", "ja-JP", "今週中は激しい運動を控え、水分をこまめに取ってください。"),
    ("minimalpair", "ko-KR", "검사 결과는 24시간 이내에 의료진이 알려 드립니다."),
    ("paraphrase", "ko-KR", "이번 주 안에는 무리한 운동을 피해 주세요."),
    (
        "minimalpair",
        "vi-VN",
        "Nhân viên y tế tại chỗ sẽ thông báo kết quả trong vòng 24 giờ.",
    ),
    (
        "paraphrase",
        "vi-VN",
        "Trong tuần này, xin hãy uống nhiều nước và tránh vận động mạnh.",
    ),
)
