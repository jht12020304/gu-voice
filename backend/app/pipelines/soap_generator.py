"""
SOAP 報告生成器 — OpenAI GPT-4o 結構化輸出

將問診對話記錄轉換為標準 SOAP (Subjective, Objective, Assessment, Plan)
格式的醫療報告，供醫師審閱與修改。
"""

import json
import logging
import re
from typing import Any

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException
from app.core.openai_client import call_with_retry, get_openai_client
from app.models.enums import URGENCY_VALUES, Urgency
from app.pipelines.icd10_validator import validate_icd10_codes
from app.utils.i18n_messages import get_message
from app.utils.language_detect import matches_expected_language

logger = logging.getLogger(__name__)

# ── 紅旗 → SOAP 緊急度的安全底線（safety floor）─────────────
# RedFlagDetector 在對話即時偵測到的 critical/high 紅旗會持久化到
# red_flag_alerts；但 SOAP 由 LLM 自逐字稿「重新推導」，曾發生
# critical(urosepsis) 卻只給 plan.urgency=24h 的 under-triage。
# 這兩個常數供 _enforce_red_flag_urgency 做 deterministic「只升不降」升級。
_SEVERITY_URGENCY_FLOOR: dict[str, str] = {
    "critical": Urgency.ER_NOW.value,    # er_now
    "high": Urgency.WITHIN_24H.value,    # 24h
    "medium": Urgency.THIS_WEEK.value,   # this_week
}
_URGENCY_RANK: dict[str, int] = {
    Urgency.ROUTINE.value: 0,
    Urgency.THIS_WEEK.value: 1,
    Urgency.WITHIN_24H.value: 2,
    Urgency.ER_NOW.value: 3,
}

# ── SOAP 生成系統提示詞 ──────────────────────────────────
_SOAP_SYSTEM_PROMPT = """你是資深泌尿科門診臨床文件助理，任務是根據問診對話內容產出一份嚴謹、可供醫師快速審閱的 SOAP 初稿。

## 你的角色
- 你不是最終診斷醫師。
- 你只能依據提供的對話內容整理資訊，不可自行虛構、補齊或推論未被明確提及的病史、理學檢查、檢驗結果或診斷。
- 若資訊不足，物件欄位請填 null、list 欄位請填空陣列 []，不要杜撰，也不要填「未提及」、「無」、空字串。

## 核心原則
1. 嚴格依據對話內容，不得杜撰。
2. 不可將病人的猜測當成醫學事實。
3. 不可將「尚未執行的檢查」寫成已完成的結果。
4. 若病人表達不確定，請保留不確定性。
5. 若病患對「同一 HPI 面向」前後陳述不一致（例如嚴重度、頻率、發作時間、持續時間先講一種、
   之後又改口成另一種），**必須**在 clinical_impression 開頭以固定標記「⚠️ 陳述不一致：」
   同時點出**兩個版本**，不得只採其中一段、也不得靜默覆蓋前一段。
6. 優先保留對臨床有價值的資訊，避免冗長重述。
7. 用專業、簡潔、可讀性高的繁體中文撰寫（ICD-10 代碼除外）。
8. 不要輸出多餘前言、解釋、註解，只輸出指定 JSON。

## 泌尿科初診需特別注意的資訊
請優先從對話中辨識並整理下列項目（未提及則填 null 或空陣列）：
- 主訴：頻尿、夜尿、急尿、排尿困難、尿流變細、解尿疼痛、尿失禁、血尿、腰痛、下腹痛、陰囊痛、會陰痛
- 症狀時間軸：何時開始、持續多久、突然或漸進、是否反覆
- 嚴重度與變化：加重、改善、間歇、持續
- 伴隨症狀：發燒、寒顫、噁心、嘔吐、背痛、側腹痛、排尿灼熱、尿液混濁、尿臭、血塊、體重減輕
- 排尿型態：頻率、夜尿次數、尿急、尿痛、解不乾淨、尿滯留感、滴尿、尿流弱
- 血尿細節：肉眼/非肉眼、是否有血塊、是否疼痛
- 疼痛細節：部位、性質、放射、程度、誘發/緩解因子
- 感染相關：過去泌尿道感染、近期抗生素、導尿、發燒
- 結石相關：過往結石、類似發作史
- 攝護腺相關：年長男性下泌尿道症狀、排尿困難、夜尿、尿流弱
- 性與生殖相關：陰莖分泌物、睪丸腫痛、性功能問題（僅限對話有提及）
- 婦女相關：懷孕可能性、月經/陰道出血與泌尿症狀混淆（僅限對話有提及）
- 既往史、用藥史、過敏史、社會史：僅在對話有提及時整理

## 各區塊撰寫規則

### Subjective（主觀）
- chief_complaint：簡潔一句話的主訴。
- hpi 必須為物件（dict），包含 10 個子欄位（onset / location / duration / characteristics / severity / aggravating_factors / relieving_factors / associated_symptoms / timing / context）；每個子欄位為字串或 null。
- past_medical_history / medications / allergies / family_history / social_history / review_of_systems **必須為單一字串或 null**，不要使用 list；可用逗點或短句整理多筆資訊。

### Objective（客觀）
- 問診助手通常無法取得客觀資料。若對話中完全沒有，請把 vital_signs / physical_exam / lab_results / imaging_results **全部填 null**。
- 不得把病人的主觀描述（例如「我自己量體溫 38 度」）誤列為理學檢查；病人自述的數值仍應算在 subjective。
- 每個欄位必須為字串或 null，不可為物件或陣列。

### Assessment（評估）
- differential_diagnoses：以可能性由高至低排列的鑑別診斷陣列，至少 2-3 項；每項需提供 diagnosis、likelihood、reasoning。
- likelihood **只能是 "high"、"moderate"、"low"** 其中之一（注意是 moderate 不是 medium）。
- reasoning 必須引用對話中的具體症狀或病史，不可只寫「臨床常見」這類空話。
- clinical_impression：一段文字總結臨床判斷方向，需保留不確定性；若有紅旗徵象，請在開頭明確標示。
- **矛盾陳述必標（硬性規定，不可省略）**：若病患對同一 HPI 面向前後陳述不一致，必須在
  clinical_impression 開頭以固定標記「⚠️ 陳述不一致：」明確並列**兩個版本**，禁止只保留其一或當作沒發生。
  範例：病患前段稱「血尿幾乎每次都有、痛到 10 分、已持續數週」，後段又改稱「其實是上個月的事、
  偶爾才發生、不太痛」→ 應寫成「⚠️ 陳述不一致：病患前段陳述血尿幾乎每次都有、疼痛 10/10、持續數週，
  後段改稱僅上個月偶發、程度輕微；兩版本並列供醫師釐清。」
- 若同時偵測到紅旗徵象與陳述不一致，請先於開頭標示紅旗，再接續「⚠️ 陳述不一致：」，兩者皆須保留。
- 不可直接下 definitive diagnosis，除非對話中已有明確既有診斷被病人陳述。

### Plan（計畫）
- recommended_tests：建議檢查列表（**物件陣列**），每項包含 test_name、rationale（一句話原因）、urgency、clinical_reasoning（2-4 句，需引用對話資訊與醫學邏輯）。
- urgency **只能是下列 4 個字串之一（完全相符、禁止翻譯、禁止補空白）**：
    1. `er_now`     —— 立即至急診
    2. `24h`        —— 24 小時內就醫
    3. `this_week`  —— 本週內就醫
    4. `routine`    —— 常規追蹤
  拼錯、自創或翻譯（如寫成「緊急」「urgent」）會被後端 fallback 成 `routine` 並記警告，務必嚴格使用 enum value。
- treatments、medications、patient_education、referrals 皆為**字串陣列（list[string]）**，不可為物件陣列。
- follow_up 為單一字串。
- diagnostic_reasoning：3-5 句說明整體檢查策略與臨床決策依據，解釋各項檢查之間的邏輯關聯。
- 書寫語氣需為「建議評估／可考慮」，不可寫成「已安排」「已開立」。
- 若有高風險紅旗，Plan 應明確寫出需優先緊急評估。
- Plan 頂層另加 `urgency` 欄位（同樣 4 選 1 enum value），代表整體 Plan 的緊急度。

### ⚠️ 病患直接看得到的兩個欄位（措辭硬性限制）

本系統部署在**醫療院所候診區的 kiosk**：病患填完問診後**人就在現場**、坐著等叫號看診，
現場就有醫護人員。下列兩個欄位會**原文直接顯示在病患自己的畫面上**，其餘欄位只有醫師看得到：

- `plan.patient_education` —— 病患端「給您的建議」區塊
- `summary` —— 病患端「本次摘要」區塊

這兩個欄位必須遵守：

1. **禁用**「立即就醫」「盡速就醫」「儘速就醫」「趕快去醫院」「立即前往急診」「立即急診評估」
   「掛急診」「叫救護車」，以及任何要病患**自行離開現場、去別的地方求醫**的指示
   （其他語言的等義說法同樣禁止，例如 "seek immediate medical attention"、"go to the ER"、
   "直ちに受診してください"、"응급실로 가세요"、"đi cấp cứu ngay"）。
   病患已經在醫療院所裡了，叫他離開現場既錯誤又危險。
2. **正確措辭**是「請稍候等待看診」「若症狀加重，請立即告知現場醫護人員」。
   越急的情況越要寫成「立即告知現場醫護人員」，而不是叫他自己跑去急診。
3. 仍要保留有價值的衛教內容——**要注意的警訊症狀、生活調整、檢查的目的**都照寫，
   只是把「該去哪裡」換成「告訴現場醫護人員／稍候等看診」。
   範例：「若出血加重，或出現疼痛、頭暈、排尿困難，請立即告知現場醫護人員。」
4. 用病患看得懂的白話，不要塞醫學術語、鑑別診斷推論或 ICD 代碼。
5. 需要急診處置的判斷請寫在 `plan.urgency`、`plan.follow_up`、`plan.diagnostic_reasoning`、
   `assessment.clinical_impression` 這些**醫師面**欄位（那裡可以、也應該直接寫
   「需急診評估」「立即安排泌尿科會診」），**不要**寫進上面兩個病患面欄位。

### 頂層欄位
- summary：3-5 句問診對話摘要（主訴、關鍵病史、重要發現、初步方向），而非僅是診斷摘要。
- icd10_codes：list[string]，保留英文與數字格式，盡可能準確。
- confidence_score：0.0-1.0 的浮點數，反映對話對 **HPI 十欄與鑑別診斷依據** 的完整度。
  family_history / social_history / review_of_systems 若未於對話中收集到屬於正常情況
  （由醫師現場補問），**不應以此壓低分數**。主要扣分項為：HPI 缺漏、主訴模糊、
  鑑別診斷無法從對話內容合理推論。

## 輸出格式
嚴格以下列 JSON schema 回覆，所有 key 必須原封不動（snake_case），禁止新增、刪除或重新命名欄位。所有文字使用繁體中文（ICD-10 代碼除外）。

{
  "subjective": {
    "chief_complaint": "string",
    "hpi": {
      "onset": "string or null",
      "location": "string or null",
      "duration": "string or null",
      "characteristics": "string or null",
      "severity": "string or null",
      "aggravating_factors": "string or null",
      "relieving_factors": "string or null",
      "associated_symptoms": "string or null",
      "timing": "string or null",
      "context": "string or null"
    },
    "past_medical_history": "string or null",
    "medications": "string or null",
    "allergies": "string or null",
    "family_history": "string or null",
    "social_history": "string or null",
    "review_of_systems": "string or null"
  },
  "objective": {
    "vital_signs": "string or null",
    "physical_exam": "string or null",
    "lab_results": "string or null",
    "imaging_results": "string or null"
  },
  "assessment": {
    "differential_diagnoses": [
      {
        "diagnosis": "string",
        "likelihood": "high|moderate|low",
        "reasoning": "string"
      }
    ],
    "clinical_impression": "string"
  },
  "plan": {
    "recommended_tests": [
      {
        "test_name": "string",
        "rationale": "string",
        "urgency": "er_now|24h|this_week|routine",
        "clinical_reasoning": "string"
      }
    ],
    "treatments": ["string"],
    "medications": ["string"],
    "follow_up": "string",
    "patient_education": ["string"],
    "referrals": ["string"],
    "diagnostic_reasoning": "string",
    "urgency": "er_now|24h|this_week|routine"
  },
  "summary": "string",
  "icd10_codes": ["string"],
  "confidence_score": 0.0
}

## 額外限制
- 不可輸出 markdown、程式碼區塊、JSON 以外的任何文字（包含前言、解釋、致謝、致歉）。
- 未提及的物件欄位一律填 null；未提及的 list 欄位請填空陣列 []。不要填「未提及」、「無」、空字串。
- likelihood 只能是 "high"、"moderate"、"low"；urgency 只能是 "er_now"、"24h"、"this_week"、"routine"。拼錯會導致前端顯示異常。
- 所有 list 欄位必須為扁平的字串陣列（除了 differential_diagnoses 與 recommended_tests 是物件陣列）。
"""


# ══ 病患面措辭鐵律：SOAP 出口消毒層 ══════════════════════════
#
# 為什麼需要：部署情境＝**院內候診 kiosk**，病患填完問診人就在現場等看診，
# 現場就有醫護。對他寫「立即就醫／盡速就醫／立即前往急診」等於叫他離開現場、
# 自己跑去別的地方求醫，既錯誤又危險。上面的 prompt 已經寫明禁令，但 prompt 靠
# LLM 遵從、不是結構性保證——真跑實測多場違規（見 tests 內的獨立語料檔）。
# 所以這裡再加一道 deterministic 出口檢查。
#
# ── 適用範圍（讀兩份前端的 code 確認過，不是猜的）─────────────
# 只套用在**真的會渲染在病患畫面上**的兩個欄位：
#   plan.patient_education
#     → frontend/src/screens/patient/PatientSessionDetailPage.tsx:63（`report?.plan?.patientEducation`）
#     → flutter_app/lib/features/patient/patient_session_detail_page.dart:80
#   summary
#     → frontend/src/screens/patient/PatientSessionDetailPage.tsx:111（「本次摘要」）
#     → frontend/src/screens/patient/SessionCompletePage.tsx:164（問診結束頁）
#     → flutter_app/lib/features/patient/patient_session_detail_page.dart:122
# 這兩處是兩份前端**唯一**讀取 SOAP 內容的地方；`review_notes` 曾被當成
# patientEducation 的 fallback，但兩份前端這輪都已移除（那是醫師的審閱備註），
# 故本層不掃 review_notes。
#
# **刻意不套用**於醫師面欄位：assessment.clinical_impression、
# assessment.differential_diagnoses、plan.follow_up、plan.treatments、
# plan.medications、plan.referrals、plan.recommended_tests、plan.diagnostic_reasoning。
# 醫師需要看到「需急診評估」這種處置判斷，改寫它等於刪臨床訊息。
# 急診處置對醫師的可見性由 plan.urgency（_enforce_red_flag_urgency 保證只升不降）、
# plan.follow_up 與 clinical_impression 承擔，不因本層而遺失。
#
# ── 判準：「有沒有叫病患自行離場」，不是「有沒有出現急診兩個字」──
# 違規 ＝ 要病患離開現場、自己跑去別處求醫，或自己叫救護車。
# **不違規** ＝ 描述院方／現場醫護會做什麼——「醫師會為您安排急診評估」對
# 候診中的病患完全合規，裸詞「急診」「急診評估」不該一律替換。
# 因此偵測分三層（順序即優先序）：
#   _LEAVE_SITE_HARD  無條件違規：明確祈使病患移動、自行撥打急救電話。
#   _ON_SITE_EXEMPT   施事者豁免：分句內出現「現場醫護／醫師會／已為您安排」
#                     等標記時，SOFT 命中不算違規（HARD 不受豁免）。
#   _LEAVE_SITE_SOFT  急迫副詞 × 求醫地點/動作 **在同一分句內共現**。
#
# ── 為什麼逐「分句」判定而不是逐字串比對距離 ──────────────
# 前一版用固定距離上限（`{0,8}`）串接副詞與地點，LLM 把話寫長就整條漏掉。
# 真跑 t8 的 summary：「需立即進行超音波檢查和泌尿科急診評估」——「立即」與
# 「急診」相隔 11 個字，距離上限直接接不住。分句邊界（。！？；，、\n / . ; ,）
# 才是語意單位，同一分句內共現就是同一句話在講同一件事。
#
# ── 命中後怎麼改：整個分句換成固定文案，不做字串手術 ────────
# 前兩輪的「片語就地替換」會拼出「請請立即…」重複詞、英文句首小寫、語意破碎的
# 句子，而這些字**原文顯示在病患畫面上**。改成分句層級整段替換：同段其他分句
# （警訊症狀清單、生活衛教）原封保留，被替換的那句一定是完整、通順、在地化的
# 合規句。相鄰的連續違規分句會合併成一句，避免同一句文案連貼兩次。

# 分句邊界：CJK 標點、換行，以及拉丁文的 `;`、`, `、句末 `.!?`。
# 拉丁句號要求後面是空白或字串結尾，才不會切開 `0.5 mg`、`119/79` 這類數值；
# 反過來**不能**要求前面是字母，否則 "dial 911." 的句號會被當成分句內容，
# 替換整句時連句號一起吃掉（真跑改述語料實測到的可讀性瑕疵）。
_CLAUSE_BOUNDARY = re.compile(r"([。．！？；\n]+|[，、]+|;\s*|,\s+|[.!?]+(?=\s|$))")
# 句末標點（決定被替換的分句要不要大寫開頭）。
_SENTENCE_END = re.compile(r"[。．！？!?\n]")

# ── zh-TW ────────────────────────────────────────────────
_ZH_URGENT = (
    r"(?:立即|立刻|馬上|即刻|盡速|儘速|盡快|儘快|趕快|趕緊|趕忙|火速"
    r"|盡早|儘早|越快越好|愈快愈好|第一時間|從速)"
)
# 「求醫的地點／動作」。刻意**不收**「門診」「掛號」「看診」「住院」——
# 「請稍候等待看診」「醫院會安排住院」都是合規句，收了就會誤傷。
_ZH_CARE = r"(?:就醫|就診|求診|求醫|看醫生|找醫生|診療|診治|急診|醫院|醫療院所)"
_ZH_CLAUSE = r"[^。！？；，、\n]*?"

# ── en-US ────────────────────────────────────────────────
_EN_URGENT = (
    r"(?:immediately|right\s+away|straight\s+away|at\s+once|urgently|promptly"
    r"|without\s+delay|as\s+soon\s+as\s+possible|asap)"
)
_EN_CARE = (
    r"(?:seek|see|visit|go\s+to|head\s+to|contact|call|attend|present\s+to)"
    r"\s+(?:a\s+|an\s+|the\s+|your\s+)?"
    r"(?:doctor|physician|hospital|clinic|emergency|urgent\s+care|medical\s+care"
    r"|medical\s+attention|medical\s+help)"
)
# 名詞型：被動語態（"to be seen by a urologist at a hospital"）沒有主動求醫動詞，
# 動詞型規則接不住，但「急迫副詞 × 醫療場所/醫師」共現一樣是叫病患去別處。
# 誤傷由 _ON_SITE_EXEMPT 擋（"our team will…", "the doctor will…"）。
_EN_CARE_NOUN = (
    r"(?:hospital|clinic|urologist|specialist|doctor|physician"
    r"|emergency\s+(?:room|department|care|services)"
    r"|medical\s+(?:care|attention|help|evaluation|treatment|advice))"
)

# ── ja-JP / ko-KR / vi-VN ────────────────────────────────
_JA_URGENT = (
    r"(?:直ちに|ただちに|すぐに|すぐ|至急|大至急|早急に|急いで"
    r"|できるだけ早く|なるべく早く)"
)
_JA_CARE = r"(?:受診|来院|病院|医療機関|救急)"
_KO_URGENT = r"(?:즉시|바로|당장|빨리|신속히|지체\s*없이|서둘러)"
_KO_CARE = r"(?:진료|병원|응급실|내원|의사)"
_VI_URGENT = r"(?:ngay\s+lập\s+tức|ngay|khẩn\s*cấp|tức\s*thì|càng\s+sớm\s+càng\s+tốt)"
# vi 的 `cấp cứu` 同時是「急診」與「急救」，裸詞良性出現的機會比其他語言高，
# 故一律要求搭配急迫語（SOFT）或移動動詞（HARD）才算違規。
_VI_CARE = r"(?:đi\s+khám|khám\s+bệnh|bệnh\s*viện|cấp\s*cứu|bác\s*sĩ|phòng\s*khám)"


def _leave_site_patterns() -> tuple[list[re.Pattern[str]], list[re.Pattern[str]], list[re.Pattern[str]]]:
    """回傳 (HARD, EXEMPT, SOFT) 三組已編譯規則。分函式只為讓上面的常數讀得完。"""
    i = re.IGNORECASE
    hard = [
        # ── zh：明確要病患自己移動／自己叫救護車 ──
        re.compile(r"(?:自行|自己)(?:前往|去|到|就醫|就診|搭車|叫車|掛號)"),
        re.compile(
            r"(?:請|務必|建議|需要|需|應該|應|要|麻煩)您?" + f"(?:{_ZH_URGENT})?"
            r"(?:前往|至|到|去|轉往|轉至|移駕)"
            r"(?:最近|附近|鄰近|其他|別家|大)?(?:的)?(?:急診室?|醫院|醫療院所)"
        ),
        re.compile(r"(?:前往|至|到|去)(?:最近|附近|鄰近|其他|別家)(?:的)?(?:急診室?|醫院|醫療院所)"),
        re.compile(r"掛急診|叫救護車|呼叫救護車|(?:撥打|撥|打)\s*(?:119|911)"),
        # ── en ──
        re.compile(r"(?:call|dial|phone)\s*9-?1-?1", i),
        # 動詞表刻意**不含** come / drive：「the urologist will come to the emergency
        # department shortly」「our team will come to the ER with you」是院方施事、
        # 完全合規，而 HARD 不吃豁免，收了就會誤傷。這兩個動詞的真違規用法
        #（"drive you to the hospital right away"）由 SOFT 的「急迫副詞 × 醫療場所」
        # 接住，而 SOFT 走豁免，所以院方施事句仍然安全。
        re.compile(
            r"(?:go|proceed|head|report|get|travel)\s+(?:back\s+)?(?:to\s+)?"
            r"(?:the\s+|your\s+|a\s+|an\s+|another\s+|nearest\s+)*"
            r"(?:ER\b|E\.R\.|emergency\s+(?:room|department|dept|care)|hospital)",
            i,
        ),
        re.compile(
            r"seek\s+(?:out\s+)?(?:immediate|urgent|emergency|prompt|medical)\s+"
            r"(?:medical\s+)?(?:attention|care|help|evaluation|treatment|assessment|advice)",
            i,
        ),
        # ── ja ──
        re.compile(r"救急車を呼|119番(?:に)?(?:通報|電話)?"),
        re.compile(r"(?:救急外来|病院|医療機関)(?:へ|に|を)?(?:行って|向かって|受診)"),
        # ── ko ──
        re.compile(r"응급실(?:로|에|을)?\s*(?:가|이동|방문|내원|후송)"),
        re.compile(r"119(?:에)?\s*(?:신고|전화|연락)"),
        re.compile(r"구급차(?:를)?\s*(?:부르|불러|호출)"),
        # ── vi ──
        re.compile(r"(?:đi|đến|tới|vào|chạy)\s+(?:khoa\s+)?cấp\s*cứu", i),
        re.compile(r"gọi\s+(?:xe\s+)?cấp\s*cứu", i),
        re.compile(r"(?:đi|đến|tới)\s+bệnh\s*viện", i),
        re.compile(r"đi\s+khám\s+ngay", i),
    ]

    exempt = [
        # ── zh：句子在講「現場／院方會處理」，不是叫病患走 ──
        re.compile(r"現場(?:的)?醫護|醫護人員|護理人員|護理師|醫療人員|醫療團隊|醫護同仁"),
        re.compile(r"(?:醫院|院方|本院|我們|醫師|醫生|醫護|團隊)(?:會|將|已|們)"),
        re.compile(r"為您安排|為你安排|已安排|已為您|已通知|已聯繫|已聯絡|協助安排|安排您"),
        re.compile(r"稍候|稍等|等待看診|等候看診|在此等候|原地等候|留在現場|請在原位"),
        # ── en ──
        re.compile(
            r"on[-\s]?site|staff\s+here|our\s+staff|clinical\s+staff|care\s+team"
            r"|team\s+here|nurse|has\s+been\s+arranged"
            r"|will\s+arrange|wait\s+here|stay\s+here|remain\s+here"
            # 施事者是院方：「the doctor will…」「we'll…」「our team is…」
            r"|\b(?:we|our\s+\w+|the\s+(?:doctor|physician|urologist|team|staff|clinic))"
            r"\s+(?:will|'ll|is|are|has|have|can)\b",
            i,
        ),
        # ── ja ──
        re.compile(r"(?:現場|院内|こちら)の医療スタッフ|スタッフにお知らせ|お待ちください|手配(?:し|いた)"),
        # ── ko ──
        re.compile(r"현장\s*의료진|의료진에게|기다려|기다리|안내(?:해|드리)|준비하고"),
        # ── vi ──
        re.compile(r"tại\s*chỗ|nhân\s*viên\s*y\s*tế|chờ\s+đến\s+lượt|sẽ\s+sắp\s+xếp|đã\s+được", i),
    ]

    soft = [
        # ── zh：急迫副詞 × 求醫地點，同一分句內共現（雙向）──
        re.compile(_ZH_URGENT + _ZH_CLAUSE + _ZH_CARE),
        re.compile(_ZH_CARE + _ZH_CLAUSE + _ZH_URGENT),
        # 沒有急迫副詞的裸祈使「前往急診」「至醫院」也是叫他離場。
        # `(?<![回返在從由])` 排掉「回到醫院複診」「在醫院內稍候」這種非離場語意；
        # 放 SOFT 而非 HARD，是為了讓「已為您轉診至急診」走施事者豁免。
        re.compile(
            r"(?<![回返在從由])(?:前往|至|到|去|赴|轉往|轉至|移駕)"
            r"(?:最近|附近|鄰近|其他|別家|大)?(?:的)?(?:急診室?|醫院|醫療院所)"
        ),
        # ── en ──
        re.compile(_EN_URGENT + r"[^,;.\n]{0,40}?" + _EN_CARE, i),
        re.compile(_EN_CARE + r"[^,;.\n]{0,40}?" + _EN_URGENT, i),
        re.compile(_EN_URGENT + r"[^,;.\n]{0,60}?" + _EN_CARE_NOUN, i),
        re.compile(_EN_CARE_NOUN + r"[^,;.\n]{0,60}?" + _EN_URGENT, i),
        re.compile(r"\bER\b|emergency\s+(?:room|department)", i),
        re.compile(r"(?:medical\s+attention|medical\s+care)\s+(?:is\s+)?" + _EN_URGENT, i),
        # ── ja ──
        re.compile(_JA_URGENT + r"[^。！？、\n]*?" + _JA_CARE),
        re.compile(_JA_CARE + r"[^。！？、\n]*?" + _JA_URGENT),
        re.compile(r"救急外来|救急車"),
        # ── ko ──
        re.compile(_KO_URGENT + r"[^.!?\n]{0,20}?" + _KO_CARE),
        re.compile(_KO_CARE + r"[^.!?\n]{0,20}?" + _KO_URGENT),
        re.compile(r"응급실"),
        # ── vi ──
        re.compile(_VI_URGENT + r"[^,;.\n]{0,30}?" + _VI_CARE, i),
        re.compile(_VI_CARE + r"[^,;.\n]{0,30}?" + _VI_URGENT, i),
    ]
    return hard, exempt, soft


_LEAVE_SITE_HARD, _ON_SITE_EXEMPT, _LEAVE_SITE_SOFT = _leave_site_patterns()

# 「孤兒急迫副詞」：整個分句只有一個急迫副詞（「大至急、近くの病院へ行って…」的
# 前半段）。它自己不違規，但緊接著的分句被替換後會留下
# 「大至急、すぐに現場の医療スタッフに…」這種贅字。緊鄰違規分句時一併吸收掉。
_ORPHAN_URGENT = re.compile(
    r"[\s、,]*(?:請|務必|建議|需要?|應該?|要|麻煩|please|hãy|xin)?\s*"
    rf"(?:{_ZH_URGENT}|{_EN_URGENT}|{_JA_URGENT}|{_KO_URGENT}|{_VI_URGENT})"
    r"[\s、,]*",
    re.IGNORECASE,
)

# 命中分句 → 整個分句換成這句（在地化）。必須自己通得過偵測器
# （test_soap_patient_facing_wording.py 有守護，避免將來改字時自我打臉）。
_PATIENT_FACING_CLAUSE: dict[str, str] = {
    "zh-TW": "請立即告知現場醫護人員",
    "en-US": "please tell the on-site clinical staff right away",
    "ja-JP": "すぐに現場の医療スタッフにお知らせください",
    "ko-KR": "현장 의료진에게 즉시 알려 주세요",
    "vi-VN": "hãy báo ngay cho nhân viên y tế tại chỗ",
}

# 整段兜底：分句替換後**仍**殘留禁語（代表替換文案自己出問題，理論上不會發生）
# 時把整段換掉。寧可少講一句衛教，也不能把候診中的病患趕出去。
_PATIENT_FACING_FALLBACK: dict[str, str] = {
    "zh-TW": "若症狀加重或出現新的不適，請立即告知現場醫護人員，並稍候等待看診。",
    "en-US": (
        "If your symptoms get worse or new problems appear, please tell the on-site "
        "clinical staff right away, and wait here for your consultation."
    ),
    "ja-JP": (
        "症状が悪化したり、新たな異変が現れたりした場合は、"
        "すぐに現場の医療スタッフにお知らせのうえ、診察までお待ちください。"
    ),
    "ko-KR": (
        "증상이 악화되거나 새로운 이상이 나타나면 현장 의료진에게 즉시 알려 주시고, "
        "이곳에서 기다려 주세요."
    ),
    "vi-VN": (
        "Nếu triệu chứng nặng hơn hoặc xuất hiện dấu hiệu mới, hãy báo ngay cho "
        "nhân viên y tế tại chỗ và vui lòng chờ đến lượt."
    ),
}
# 未支援語言 → 退回 zh-TW（與 i18n_messages._resolve_lang 的 DEFAULT_LANGUAGE 一致）。
_PATIENT_FACING_FALLBACK_DEFAULT = "zh-TW"


def _clause_violation(clause: str) -> str | None:
    """單一分句是否「叫病患自行離場求醫」。回傳命中的片語（供 log），否則 None。"""
    for pattern in _LEAVE_SITE_HARD:
        match = pattern.search(clause)
        if match:
            return match.group(0)
    if any(pattern.search(clause) for pattern in _ON_SITE_EXEMPT):
        return None
    for pattern in _LEAVE_SITE_SOFT:
        match = pattern.search(clause)
        if match:
            return match.group(0)
    return None


def _split_clauses(text: str) -> list[tuple[str, str]]:
    """切成 [(分句內容, 其後的分隔符)]；join 回去必須逐字還原原文。"""
    parts = _CLAUSE_BOUNDARY.split(text)
    out: list[tuple[str, str]] = []
    for idx in range(0, len(parts), 2):
        out.append((parts[idx], parts[idx + 1] if idx + 1 < len(parts) else ""))
    return out


class SOAPGenerator:
    """
    SOAP 醫療報告生成器

    使用 OpenAI GPT-4o 模型，從問診對話記錄中
    擷取結構化資訊並生成標準 SOAP 格式報告。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 OpenAI 客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        self._client = get_openai_client()
        self._model = settings.OPENAI_MODEL_SOAP  # gpt-4o
        self._temperature = settings.OPENAI_TEMPERATURE_SOAP  # 0.3
        self._max_tokens = settings.OPENAI_MAX_TOKENS_SOAP  # 4096

        logger.info(
            "SOAPGenerator 初始化 | model=%s, temperature=%.1f, max_tokens=%d",
            self._model,
            self._temperature,
            self._max_tokens,
        )

    def _format_transcript(self, transcript: list[dict[str, Any]]) -> str:
        """
        將對話記錄格式化為可讀文字

        Args:
            transcript: 對話記錄列表，每筆包含 role 和 content

        Returns:
            格式化後的對話文字
        """
        lines: list[str] = []
        for entry in transcript:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            timestamp = entry.get("timestamp", "")

            # 角色名稱使用中性英文 code，避免被 LLM 當成「輸出語言線索」照抄中文
            # （原本的「病患 / AI 助手」會污染日/韓/越場次的 SOAP 輸出語言）。
            role_label = {
                "patient": "Patient",
                "user": "Patient",
                "assistant": "Assistant",
                "ai": "Assistant",
                "system": "System",
            }.get(role, role)

            time_str = f" [{timestamp}]" if timestamp else ""
            lines.append(f"{role_label}{time_str}: {content}")

        return "\n".join(lines)

    async def generate(
        self,
        transcript: list[dict[str, Any]],
        patient_info: dict[str, Any],
        chief_complaint: str,
        language: str | None = None,
        symptom_id: str | None = None,
        red_flags: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        根據對話記錄生成 SOAP 報告

        Args:
            transcript: 對話記錄列表
            patient_info: 病患基本資訊
            chief_complaint: 主訴
            language: session BCP-47 語言碼，決定 SOAP 輸出語言（預設 zh-TW）
            symptom_id: 本次主訴對應的 snake_case slug（例：`hematuria`），
                供 ICD-10 驗證層 (`validate_icd10_codes`) 比對。可為 None。

        Returns:
            結構化 SOAP 報告字典：
            {
                "subjective": {...},
                "objective": {...},
                "assessment": {...},
                "plan": {...},
                "summary": str,
                "icd10_codes": list[str],       # 已通過白名單過濾
                "icd10_verified": bool,         # 是否通過 symptom↔code 對映
                "confidence_score": float,
            }

        Raises:
            AIServiceUnavailableException: OpenAI API 不可用時
        """
        # 組合病患資訊（使用中性英文 label + 原始 enum 值，
        # 避免日/韓/越場次被 LLM 照抄中文欄位名）。
        patient_parts: list[str] = []
        if patient_info.get("name"):
            patient_parts.append(f"Name: {patient_info['name']}")
        # age 必須用 `is not None`：patient_context.calculate_age 對「今年出生且生日
        # 已過」的病患回 int 0，truthy 判斷會讓整行年齡從 SOAP prompt 消失。
        # 其餘欄位的值都是非空字串或 None，truthy 判斷是對的。
        if patient_info.get("age") is not None:
            patient_parts.append(f"Age: {patient_info['age']}")
        if patient_info.get("gender"):
            patient_parts.append(f"Gender: {patient_info['gender']}")
        if patient_info.get("medical_history"):
            patient_parts.append(f"Past medical history: {patient_info['medical_history']}")
        if patient_info.get("medications"):
            patient_parts.append(f"Current medications: {patient_info['medications']}")
        if patient_info.get("allergies"):
            patient_parts.append(f"Allergies: {patient_info['allergies']}")
        if patient_info.get("family_history"):
            patient_parts.append(f"Family history: {patient_info['family_history']}")

        patient_text = "\n".join(patient_parts) if patient_parts else "(not provided)"
        transcript_text = self._format_transcript(transcript)
        red_flag_text = self._format_red_flags(red_flags)

        # user_message 用中性英文標題，輸出語言由 system prompt 的語言規則決定。
        user_message = f"""## Patient Basic Information
{patient_text}

## Chief Complaint
{chief_complaint}
{red_flag_text}
## Consultation Transcript
{transcript_text}

Please produce the full SOAP report based on the information above."""

        try:
            # PHI：log 不輸出主訴原文（「其他」主訴為病患自述自由文字）。
            logger.info(
                "開始生成 SOAP 報告 | transcript_length=%d, language=%s",
                len(transcript),
                language,
            )

            # 依 session language 強制輸出語言：
            # _SOAP_SYSTEM_PROMPT 原文用繁中撰寫（臨床知識、schema 命名不變），
            # 但若不把輸出語言規則放在最前面，LLM 看到大量中文內文後傾向用中文輸出。
            # 作法：prepend + append 雙重保險，頂端建立語言錨點、尾端再重申硬性規定。
            language_rule = get_message("llm.soap_language_instruction", language)
            system_prompt_localized = (
                language_rule.lstrip() + "\n\n" + _SOAP_SYSTEM_PROMPT + language_rule
            )

            response = await call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt_localized},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                    response_format={"type": "json_object"},
                )
            )

            raw_content = response.choices[0].message.content or "{}"
            soap_report = json.loads(raw_content)

            # 驗證並補齊必要欄位（含 urgency enum fallback）
            soap_report = self._validate_and_fill(soap_report, chief_complaint)

            # 安全硬規則：偵測層的 critical/high 紅旗強制反映到緊急度（只升不降），
            # 修補 LLM 自逐字稿重新推導時的 under-triage（如 urosepsis→僅 24h）。
            soap_report = self._enforce_red_flag_urgency(
                soap_report, red_flags, language
            )

            # 病患面措辭鐵律出口檢查：只掃真的渲染給病患的欄位
            # （plan.patient_education / summary），醫師面欄位不動。
            # 放在 _enforce_red_flag_urgency 之後，確保紅旗升級補寫的
            # clinical_impression（醫師面）不會被誤掃，且沒有後續步驟能再塞回禁語。
            soap_report = self._sanitize_patient_facing_fields(soap_report, language)

            # ICD-10 驗證層（M3）：白名單過濾 + symptom 對映
            raw_codes = soap_report.get("icd10_codes") or []
            filtered_codes, is_verified = validate_icd10_codes(
                raw_codes, symptom_id
            )
            if len(filtered_codes) != len(raw_codes):
                logger.info(
                    "ICD-10 validator stripped %d code(s) | raw=%s filtered=%s symptom=%s",
                    len(raw_codes) - len(filtered_codes),
                    raw_codes,
                    filtered_codes,
                    symptom_id,
                )
            if not is_verified:
                logger.info(
                    "ICD-10 not verified | symptom=%s codes=%s",
                    symptom_id,
                    filtered_codes,
                )
            soap_report["icd10_codes"] = filtered_codes
            soap_report["icd10_verified"] = is_verified

            # Heuristic sanity check：LLM 偶爾會不遵守輸出語言硬性規定。
            # 以 summary + clinical_impression 偵測語言；不匹配就 log warn（不 raise）
            self._warn_if_output_language_mismatch(soap_report, language)

            logger.info(
                "SOAP 報告生成完成 | confidence=%.2f, diagnoses_count=%d",
                soap_report.get("confidence_score", 0),
                len(
                    soap_report.get("assessment", {}).get(
                        "differential_diagnoses", []
                    )
                ),
            )

            return soap_report

        except json.JSONDecodeError as exc:
            logger.error("SOAP 報告 JSON 解析失敗 | error=%s", str(exc))
            raise AIServiceUnavailableException(
                message="errors.soap_generation_bad_format",
                details={"error": str(exc)},
            )

        except Exception as exc:
            logger.error(
                "SOAP 報告生成失敗 | error=%s", str(exc), exc_info=True
            )
            raise AIServiceUnavailableException(
                message="errors.soap_generation_unavailable",
                details={"error": str(exc)},
            )

    @staticmethod
    def _format_red_flags(red_flags: list[dict[str, Any]] | None) -> str:
        """把偵測層回報的紅旗格式化為 prompt 區塊（給 LLM 參考，中性英文標題）。"""
        if not red_flags:
            return ""
        lines: list[str] = []
        for rf in red_flags:
            sev = rf.get("severity")
            sev = (sev.value if hasattr(sev, "value") else str(sev or "")).lower()
            cid = rf.get("canonical_id") or rf.get("name") or "red_flag"
            reason = rf.get("trigger_reason") or rf.get("description") or ""
            actions = rf.get("suggested_actions") or []
            if isinstance(actions, list):
                actions = "; ".join(str(a) for a in actions)
            lines.append(f"- [{sev}] {cid}: {reason} (suggested: {actions})")
        body = "\n".join(lines)
        return (
            "\n## ⚠️ Detected Red Flags (real-time triage — MUST reflect in output)\n"
            "These red flags were already detected during the consultation. You MUST:\n"
            "1. State them at the START of clinical_impression.\n"
            "2. Set plan.urgency to match the highest severity "
            "(critical → er_now, high → at least 24h, medium → at least this_week).\n"
            f"{body}\n"
        )

    @staticmethod
    def _enforce_red_flag_urgency(
        report: dict[str, Any],
        red_flags: list[dict[str, Any]] | None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """
        安全硬規則：把偵測層回報的紅旗嚴重度強制反映到 SOAP 緊急度（只升不降）。

        背景：RedFlagDetector 即時偵測到的 critical/high 紅旗已持久化到
        red_flag_alerts，但 SOAP 由 LLM 自逐字稿重新推導，曾發生 critical
        (urosepsis) 卻只給 plan.urgency=24h 的 under-triage。此處以
        deterministic 後處理保證 monotonic escalation：
          critical → 至少 er_now、high → 至少 24h、medium → 至少 this_week。
        並把 recommended_tests 各項 urgency 一併提升至同一 floor（消除
        「整體緊急但某檢查仍緩」的矛盾），且在 clinical_impression 開頭補紅旗
        標註（若 LLM 未標）。無紅旗則完全不動，故不影響非紅旗案。
        """
        if not red_flags:
            return report

        def _sev(rf: dict[str, Any]) -> str:
            s = rf.get("severity")
            return (s.value if hasattr(s, "value") else str(s or "")).lower()

        floors = [
            _SEVERITY_URGENCY_FLOOR[s]
            for s in (_sev(rf) for rf in red_flags)
            if s in _SEVERITY_URGENCY_FLOOR
        ]
        if not floors:
            return report

        floor = max(floors, key=lambda u: _URGENCY_RANK[u])
        floor_rank = _URGENCY_RANK[floor]

        plan = report.setdefault("plan", {})
        current = SOAPGenerator._coerce_urgency(
            plan.get("urgency"), context="plan.urgency"
        )
        if _URGENCY_RANK[current] < floor_rank:
            logger.warning(
                "Red-flag urgency escalation | plan.urgency %s -> %s (%d red flag(s))",
                current, floor, len(floors),
            )
            plan["urgency"] = floor

        # recommended_tests 各項不得低於 floor（消除整體急但檢查緩的矛盾）
        tests = plan.get("recommended_tests")
        if isinstance(tests, list):
            for t in tests:
                if isinstance(t, dict):
                    tu = SOAPGenerator._coerce_urgency(
                        t.get("urgency"), context="recommended_tests.item"
                    )
                    if _URGENCY_RANK[tu] < floor_rank:
                        t["urgency"] = floor

        # clinical_impression 開頭補紅旗標註（deterministic，避免 LLM 漏標）
        assess = report.setdefault("assessment", {})
        impression = str(assess.get("clinical_impression") or "")
        if "⚠" not in impression:
            canon = list(dict.fromkeys(
                (rf.get("canonical_id") or rf.get("name") or "") for rf in red_flags
            ))
            canon = [c for c in canon if c]
            prefix = get_message("soap.red_flag_impression_prefix", language)
            tag = f"⚠️ {prefix}" + (f" [{', '.join(canon)}]" if canon else "")
            assess["clinical_impression"] = (tag + " " + impression).strip()

        return report

    @staticmethod
    def _sanitize_patient_facing_text(
        text: str, language: str | None = None
    ) -> tuple[str, list[str]]:
        """
        對「病患畫面上直接看得到」的一段文字執行措辭鐵律出口檢查。

        Returns:
            (合規後的文字, 命中的禁語片段清單)。沒命中時原字串**原封不動**回傳，
            hits 為空 list —— 合規內容絕不被改動是本函式的硬性契約。

        作法：切成分句 → 逐句判定「有沒有叫病患自行離場求醫」→ 命中的分句
        整句換成在地化固定文案（相鄰違規分句合併成一句），其餘分句原封不動。
        最後再整段掃一次；若仍殘留（理論上不會）就整段換成兜底文案。
        """
        if not isinstance(text, str) or not text.strip():
            return text, []

        lang = (
            language
            if language in _PATIENT_FACING_CLAUSE
            else _PATIENT_FACING_FALLBACK_DEFAULT
        )
        clause_text = _PATIENT_FACING_CLAUSE[lang]

        clauses = _split_clauses(text)
        violations: list[str | None] = [
            _clause_violation(segment) if segment.strip() else None
            for segment, _ in clauses
        ]
        if not any(violations):
            return text, []

        # 由後往前吸收「孤兒急迫副詞」分句（「大至急、近くの病院へ行って…」的前半），
        # 否則替換後會留下「大至急、すぐに現場の医療スタッフに…」這種贅字。
        for idx in range(len(clauses) - 2, -1, -1):
            if violations[idx] is None and violations[idx + 1] is not None:
                stripped = clauses[idx][0].strip()
                if stripped and _ORPHAN_URGENT.fullmatch(stripped):
                    violations[idx] = stripped

        hits: list[str] = []
        # (內容, 其後分隔符, 是否為替換文案)
        rebuilt: list[list[Any]] = []
        for (segment, delimiter), hit in zip(clauses, violations):
            if hit is None:
                rebuilt.append([segment, delimiter, False])
                continue
            hits.append(hit)
            if rebuilt and rebuilt[-1][2]:
                # 與前一個被替換的分句相鄰 → 併成一句，沿用較後面的分隔符，
                # 避免「請立即告知現場醫護人員，請立即告知現場醫護人員。」
                rebuilt[-1][1] = delimiter or rebuilt[-1][1]
                continue
            rebuilt.append([clause_text, delimiter, True])

        pieces: list[str] = []
        starts_sentence = True
        for segment, delimiter, replaced in rebuilt:
            if replaced and starts_sentence:
                segment = segment[:1].upper() + segment[1:]
            pieces.append(segment + delimiter)
            if segment.strip():
                starts_sentence = bool(_SENTENCE_END.search(delimiter))
        out = "".join(pieces)

        residual = next(
            (
                hit
                for hit in (
                    _clause_violation(seg) for seg, _ in _split_clauses(out)
                )
                if hit
            ),
            None,
        )
        if residual:
            hits.append(residual)
            return _PATIENT_FACING_FALLBACK[lang], hits

        return out, hits

    @staticmethod
    def _sanitize_patient_facing_fields(
        report: dict[str, Any], language: str | None = None
    ) -> dict[str, Any]:
        """
        對 SOAP 報告中**真正渲染給病患**的欄位套用措辭鐵律（其餘欄位一律不動）。

        涵蓋欄位與前端渲染位置見本檔案上方「病患面措辭鐵律」註解區塊。
        命中禁語時 log warning 並附上被攔下來的片語，讓人知道 LLM 又寫了什麼
        （只記命中的片語，不記整段臨床文字，避免 log 溢出 PHI）。
        """
        hits_by_field: dict[str, list[str]] = {}

        def _clean(value: Any, field: str) -> Any:
            if not isinstance(value, str):
                return value
            cleaned, hits = SOAPGenerator._sanitize_patient_facing_text(
                value, language
            )
            if hits:
                hits_by_field.setdefault(field, []).extend(hits)
            return cleaned

        # summary（病患端「本次摘要」＋問診結束頁）。
        # 只在原本就是字串時回寫，避免對缺 key 的報告憑空塞出 summary=None。
        if isinstance(report.get("summary"), str):
            report["summary"] = _clean(report["summary"], "summary")

        # plan.patient_education（病患端「給您的建議」）
        plan = report.get("plan")
        if isinstance(plan, dict):
            education = plan.get("patient_education")
            field = "plan.patient_education"
            if isinstance(education, list):
                plan["patient_education"] = [
                    _clean(item, field) for item in education
                ]
            elif isinstance(education, str):
                plan["patient_education"] = _clean(education, field)

        if hits_by_field:
            logger.warning(
                "SOAP 病患面措辭違規已改寫（院內候診 kiosk 禁止叫病患自行離場就醫）"
                " | language=%s fields=%s banned_phrases=%s",
                language,
                sorted(hits_by_field),
                sorted({phrase for hits in hits_by_field.values() for phrase in hits}),
            )

        return report

    @staticmethod
    def _coerce_urgency(value: Any, *, context: str = "urgency") -> str:
        """
        將 LLM 回傳的 urgency 正規化成 4 個合法 enum value 之一。
        落在 enum 外（None、空字串、翻譯後中文、拼錯等）→ fallback 成 `routine`
        並 log warning，讓後續調查可追。
        """
        if isinstance(value, str):
            candidate = value.strip().lower()
            if candidate in URGENCY_VALUES:
                return candidate
        logger.warning(
            "SOAP urgency invalid, fallback to routine | context=%s value=%r",
            context,
            value,
        )
        return Urgency.ROUTINE.value

    @staticmethod
    def _warn_if_output_language_mismatch(
        report: dict[str, Any], expected_language: str | None
    ) -> None:
        """
        以 summary + clinical_impression 做 heuristic 比對；不匹配時 log warn。
        不 raise — 即便偵測不符也要把報告回給使用者，避免阻斷服務。
        """
        if not expected_language:
            return
        summary = str(report.get("summary", ""))
        impression = str(report.get("assessment", {}).get("clinical_impression", ""))
        sample = f"{summary}\n{impression}".strip()
        if not matches_expected_language(sample, expected_language):
            # PHI：log 不輸出 summary / clinical_impression 原文，只留長度供排查。
            logger.warning(
                "SOAP output language mismatch | expected=%s sample_chars=%d",
                expected_language,
                len(sample),
            )

    @staticmethod
    def _validate_and_fill(
        report: dict[str, Any], chief_complaint: str
    ) -> dict[str, Any]:
        """
        驗證 SOAP 報告結構並補齊缺失欄位

        Args:
            report: 原始報告字典
            chief_complaint: 主訴（用於補齊）

        Returns:
            驗證並補齊後的報告字典
        """
        # 確保頂層結構完整
        if "subjective" not in report:
            report["subjective"] = {}
        if "objective" not in report:
            report["objective"] = {}
        if "assessment" not in report:
            report["assessment"] = {}
        if "plan" not in report:
            report["plan"] = {}

        # Subjective 補齊
        subj = report["subjective"]
        if not subj.get("chief_complaint"):
            subj["chief_complaint"] = chief_complaint
        if "hpi" not in subj:
            subj["hpi"] = {}
        hpi_fields = [
            "onset", "location", "duration", "characteristics",
            "severity", "aggravating_factors", "relieving_factors",
            "associated_symptoms", "timing", "context",
        ]
        for field in hpi_fields:
            if field not in subj["hpi"]:
                subj["hpi"][field] = None

        # Objective 補齊
        obj = report["objective"]
        for field in ["vital_signs", "physical_exam", "lab_results", "imaging_results"]:
            if field not in obj:
                obj[field] = None

        # Assessment 補齊
        assess = report["assessment"]
        if "differential_diagnoses" not in assess:
            assess["differential_diagnoses"] = []
        if "clinical_impression" not in assess:
            assess["clinical_impression"] = ""

        # Plan 補齊
        plan = report["plan"]
        for field in [
            "recommended_tests", "treatments", "medications",
            "follow_up", "patient_education", "referrals",
        ]:
            if field not in plan:
                plan[field] = [] if field != "follow_up" else None
        if "diagnostic_reasoning" not in plan:
            plan["diagnostic_reasoning"] = None

        # 確保 recommended_tests 為結構化物件陣列
        if isinstance(plan.get("recommended_tests"), list):
            normalized_tests = []
            for item in plan["recommended_tests"]:
                if isinstance(item, str):
                    # 舊格式：純字串 → 轉為物件
                    normalized_tests.append({
                        "test_name": item,
                        "rationale": "",
                        "urgency": Urgency.ROUTINE.value,
                        "clinical_reasoning": "",
                    })
                elif isinstance(item, dict):
                    item.setdefault("test_name", item.get("name", ""))
                    item.setdefault("rationale", "")
                    item.setdefault("urgency", Urgency.ROUTINE.value)
                    item.setdefault("clinical_reasoning", "")
                    # 每一項 test 的 urgency 也要 enum 化
                    item["urgency"] = SOAPGenerator._coerce_urgency(
                        item.get("urgency"),
                        context="recommended_tests.item",
                    )
                    normalized_tests.append(item)
            plan["recommended_tests"] = normalized_tests

        # Plan 頂層 urgency（M13）：LLM 未吐或吐怪值 → fallback 成 routine
        plan["urgency"] = SOAPGenerator._coerce_urgency(
            plan.get("urgency"),
            context="plan.urgency",
        )

        # 頂層欄位
        if "summary" not in report:
            report["summary"] = ""
        if "icd10_codes" not in report:
            report["icd10_codes"] = []
        if "confidence_score" not in report:
            report["confidence_score"] = 0.0

        # 確保 confidence_score 為合法數值
        try:
            score = float(report["confidence_score"])
            report["confidence_score"] = max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            report["confidence_score"] = 0.0

        return report
