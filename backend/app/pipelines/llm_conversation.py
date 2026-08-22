"""
LLM 對話引擎 — OpenAI GPT-4o 結構化問診

負責驅動泌尿科 AI 問診助手的對話邏輯，
遵循 HPI (History of Present Illness) 框架進行結構化問診。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any, NamedTuple

from app.core.config import Settings
from app.core.exceptions import AIServiceUnavailableException
from app.core.openai_client import (
    budget_messages,
    cache_kwargs,
    call_with_retry,
    get_openai_client,
    sampling_kwargs,
)
from app.pipelines.next_focus_guard import (
    build_dont_know_ban,
    declined_fields_from_history,
    effective_next_focus,
)
from app.pipelines.prompts.shared import (
    SINGLE_QUESTION_RULE,
    count_critical_risk_factors_for_complaint,
    get_critical_risk_factors_for_complaint,
    render_hpi_checklist,
    render_red_flags_for_conversation,
    sanitize_for_prompt,
)
from app.utils.i18n_messages import get_message as _i18n_get

logger = logging.getLogger(__name__)


# =============================================================================
# intake 已涵蓋 → 禁問清單（§3b 必問清單的 intake 感知過濾）
# =============================================================================
# 實測（2026-07-27 真跑）:system prompt 明載 `Current medications: aspirin`、
# `Family history: 父親：膀胱癌`，AI 仍在第 4 輪問「有沒有在吃阿司匹靈、華法林這類
# 會影響凝血的藥」、第 12 輪問「有沒有泌尿道癌症的家族史」。根因不是資訊沒進 prompt，
# 而是 intake 只是「病患資訊」段的**被動陳述**，§3b 風險因子清單卻是主動的**必問指令**
# ——兩段衝突時 LLM 服從後者。既有的「若 intake 已提供則不需重複詢問」是要 LLM 自己
# 跨段比對，實測不可靠。
#
# 對策:組 prompt 時就把 intake 已**涵蓋**的風險因子從必問清單移除、改列進附帶 intake
# 值的**禁問清單**，不再指望 LLM 自行比對。supervisor 的 next_focus gate 同源（避免
# 兩邊漂移）。
#
# ── 判定是三態，不是「欄位空/非空」兩態（2026-07-27 覆核 BLOCKER #5） ──
# 舊版把「該欄有任何非空值」當成已答，等於信任 intake 表單的完整度，實測後果：
#   - 用藥欄只填 `amlodipine`（沒填 OTC aspirin）→「抗凝血/抗血小板」整項被移出必問、
#     還被寫進「一律不得再問」的禁問清單 → AI 全程不會口頭確認一次。
#   - ED 場 `medical_history` 只填「高血壓」→ 同時關掉「心血管疾病史」與「糖尿病」。
# 而且 prompt 會對 LLM 斷言一個不成立的事實（「病患已提供抗凝血用藥資訊」）。
# 現行三態:
#   1. 該欄是病患明確表示的「無」(patient_context 對 no_* 旗標寫入「無」)
#      → 已答＝「否」，不再問。
#   2. 該欄有值**且值語意涵蓋這個風險因子**（用藥列表出現 aspirin / warfarin…）
#      → 已答＝「是」，不再問；但 prompt 只說「表單自填為 X、不需重複詢問」，
#        **不得**叫 LLM 把它當成已確認的臨床事實（見下方「捏造病歷」段）。
#   3. 該欄有值**但不涵蓋**（用藥只有 amlodipine）／該欄空白 → **仍必問**。
# 涵蓋判定靠 `_RISK_FACTOR_RULES` 的關鍵字／藥物類別對照，**保守優先**:比不到 →
# 第三態（仍必問）。多問一句的代價遠低於漏掉抗凝血劑。
#
# ── 涵蓋判定是「逐筆」的，不是把整串當 haystack（2026-07-27 覆核 BLOCKER D） ──
# 第二輪的判定把整個欄位值當成一個字串比對，於是條件可以來自**不同筆記錄**:
#   家族史「母親：乳癌、父親：攝護腺肥大」→「癌」來自母親、「攝護腺」來自父親
#   → 判成「泌尿道惡性腫瘤家族史＝有」→ 該項被跳過不問，**而且**prompt 還要 LLM
#   把它寫進病史 → SOAP 憑空生出病患沒有的泌尿道癌家族史。漏問只是漏問，
#   **捏造家族史寫進醫師看的報告是另一個量級的問題**。
# 現行作法:
#   - 值一律先用 `split_intake_entries` 拆成「筆」（intake 的 list 欄位由
#     patient_context 用「、」串接，故分隔符以「、」為主、其餘標點為容錯）。
#   - `same_entry=True` 的規則（家族史）要求**同一筆**同時滿足惡性詞與泌尿部位詞。
#   - 「筆」帶有取消資格的限定語（用藥「已停用」、「過敏」；家族史「轉移」）時整筆
#     不採計 → 退回仍必問。判不準一律歸「仍必問」。
#   - 複合子項（ED 的「心血管疾病史(高血壓、冠狀動脈疾病、心肌梗塞、腦中風)」）
#     要**每個子項都被提到**才算涵蓋；只提到高血壓＝部分涵蓋 → 仍必問，並在必問
#     行標註「已知高血壓、仍須問心肌梗塞／腦中風…」，避免 LLM 重問已知的那一項。
#
# ── gating 只吃「本次場次 intake」，不吃 patients 表舊資料 ──
# `patient_context.build_patient_info` 在本次 intake 空白時，會把
# medical_history / medications / allergies 三欄 fallback 到 `patients` 表的長期
# 資料（可能是幾個月前建檔的）。§3b 是安全不變式，不能被舊資料關掉，故 gating 走
# `session_intake_fields()`——只採信可證明來自本次 intake 的值。
# =============================================================================

# `_cap_conversation_history`（conversation_handler）壓縮舊輪次後寫入 history 的那一則
# 摘要，其 content 一律以此為前綴。`format_messages` 靠它把「該進 LLM 的壓縮摘要」與
# 「其餘不該進 LLM 的 system 歷史」區分開來——單一來源，避免兩邊字面漂移。
HISTORY_SUMMARY_PREFIX = "[前段對話摘要]"

# intake 四欄的中文標籤（顯示在禁問清單裡，與 supervisor.build_patient_info_str 一致）
INTAKE_FIELD_LABELS: dict[str, str] = {
    "medical_history": "過去病史",
    "medications": "目前用藥",
    "allergies": "過敏史",
    "family_history": "家族史",
}

# patient_context.build_patient_info 未來要多回的「本次 intake 原值」子 dict。
# key 為上面四欄之一、值為本次 intake 的字串（no_* 旗標為 True 時是「無」，沒填是 None）。
# 有這個 key 時 §3b gating 完全以它為準；沒有時走下方保守 fallback。
INTAKE_SOURCE_KEY = "intake_fields"

# 沒有 INTAKE_SOURCE_KEY 時，扁平 patient_info 裡**可證明**來自本次 intake 的欄位。
# build_patient_info 對 family_history 沒有 `or format_jsonb_list(patient.…)` 的
# fallback 分支（其餘三欄有），故 family_history 的值必定來自本次 intake。
# 這個假設由 test_intake_risk_coverage.py 直接對 build_patient_info 釘住，
# 上游一旦加了 family_history fallback，測試會紅。
_INTAKE_ONLY_FIELDS_WITHOUT_MARKER: tuple[str, ...] = ("family_history",)

# 病患明確表示「沒有」的值。patient_context 對 no_* 旗標寫死中文「無」，
# 其餘拼法是容錯（不影響安全方向:認不出來只會退回「仍必問」）。
_EXPLICIT_NONE_VALUES: frozenset[str] = frozenset(
    {"無", "沒有", "否認", "無特殊", "none", "no", "nil", "n/a", "na"}
)

# ── 風險因子「被涵蓋」的判定詞庫 ──────────────────────────────
# 原則:寧可漏判（→ 仍必問）也不可誤判（→ 誤跳過）。故一律不收會誤命中其他名詞的
# 短縮寫（asa / dm / cad）與泌尿科同名詞（「支架」可能是輸尿管雙 J 管）。
#
# ── 五語詞庫（IN-2，2026-08-20） ─────────────────────────────
# 舊版只有 zh + en。場次語言是五語（zh-TW / en-US / ja-JP / ko-KR / vi-VN），intake
# 是**病患用場次語言自填**的自由文字，所以 ko「방광암」、vi「ung thư bàng quang」、
# ja 假名「膀胱がん」「ワーファリン」在舊詞庫下一律判不出涵蓋 → 該項退回「仍必問」
# → §3b 必問條款的優先序高於次要補問的禁問清單（build_system_prompt 的「例外（優先序
# 最高）」）→ **病患剛在 intake 填過的家族史／抗凝血用藥被口頭重問一次**。
#
# 收詞判準（照不變式 #23 的安全方向）:
#   - 判不準 → 歸「仍必問」是**安全**方向（多問一句）；錯誤的涵蓋判定（誤跳過 +
#     寫進病史）才是危險方向。故只收**高確信**的醫療常用語彙,寧缺勿濫。
#   - 每個字面都先檢查「在其他四語的常見句子裡是不是高頻子字串」（不變式 #25 的
#     全語言聯集教訓）——這裡的比對對象是 intake 欄位值,不是逐字稿,但同樣是聯集。
#   - ja 的漢字**不等於**zh 的漢字:悪性/腫瘍/前立腺/睾丸/心筋梗塞/高血圧/脳梗塞
#     都與繁中寫法不同,必須並列;純假名寫法（がん／ワーファリン）也要收。
#   - 短字面只在「另有詞群把關」時才收:`_MALIGNANCY_TERMS` 只用在家族史規則
#     （same_entry=True,必須同一筆同時命中泌尿部位詞）,故 ko「암」可收；
#     vi 的「u」（腫瘤）則**不收**——單字母會誤命中一切。
_ANTICOAGULANT_TERMS: tuple[str, ...] = (
    "抗凝",
    "抗血小板",
    "血液稀釋",
    "薄血",
    "anticoagul",
    "antiplatelet",
    "blood thinner",
    "noac",
    "doac",
    "aspirin",
    "阿司匹靈",
    "阿斯匹靈",
    "阿司匹林",
    "阿斯匹林",
    "伯基",
    "bokey",
    "warfarin",
    "華法林",
    "可邁丁",
    "coumadin",
    "clopidogrel",
    "plavix",
    "保栓通",
    "氯吡格雷",
    "ticagrelor",
    "brilinta",
    "prasugrel",
    "effient",
    "dipyridamole",
    "persantin",
    "cilostazol",
    "pletaal",
    "rivaroxaban",
    "xarelto",
    "拜瑞妥",
    "apixaban",
    "eliquis",
    "edoxaban",
    "lixiana",
    "dabigatran",
    "pradaxa",
    "heparin",
    "肝素",
    "enoxaparin",
    "clexane",
    # ── ja-JP ──（漢字「抗凝固」已被 zh 的「抗凝」涵蓋；假名藥名必須另收）
    "ワーファリン",
    "ワルファリン",
    "アスピリン",  # 同時涵蓋「バイアスピリン」
    "クロピドグレル",
    "プラビックス",
    "エリキュース",
    "イグザレルト",
    "リクシアナ",
    "プラザキサ",
    "ヘパリン",
    # 刻意不收 ja 的口語「血液サラサラ」——那是納豆／EPA 等保健食品的行銷用語,
    # 收了會讓「吃保健食品」被判成「已在用抗凝血劑」＝誤跳過（危險方向）。
    # ── ko-KR ──
    "항응고",
    "항혈소판",
    "와파린",
    "아스피린",
    "클로피도그렐",
    "플라빅스",
    "자렐토",
    "엘리퀴스",
    "헤파린",
    "혈액 응고 억제",
    # ── vi-VN ──
    "chống đông",
    "kháng đông",
    "chống kết tập tiểu cầu",
    "loãng máu",
)

# 刻意不收單字「瘤」——「腎血管肌脂肪瘤」「膀胱乳突瘤」是良性病灶，收了會讓良性
# 家族史被誤判成泌尿道惡性腫瘤家族史（誤判＝跳過＋寫進病史，方向錯得最貴）。
_MALIGNANCY_TERMS: tuple[str, ...] = (
    "癌",
    "惡性",
    "腫瘤",
    "cancer",
    "carcinoma",
    "tumor",
    "tumour",
    "malignan",
    "neoplasm",
    # ── ja-JP ──（「癌」漢字已收；ja 日常多寫假名「がん」,惡性/腫瘤的 ja 漢字不同）
    "がん",
    "ガン",
    "悪性",
    "腫瘍",
    # ── ko-KR ──（「암」是單音節,但本詞群**只**用於家族史規則且 same_entry=True,
    #   必須與同一筆裡的泌尿部位詞共現才成立,故短字面在此安全）
    "암",
    "악성",
    "종양",
    # ── vi-VN ──（刻意不收單字「u」——單字母會誤命中一切）
    "ung thư",
    "ung bướu",
    "ác tính",
    "khối u",
)

_UROLOGIC_TERMS: tuple[str, ...] = (
    "泌尿",
    "膀胱",
    "腎",
    "輸尿管",
    "尿路",
    "尿道",
    "攝護腺",
    "前列腺",
    "睪丸",
    "bladder",
    "kidney",
    "renal",
    "urothelial",
    "urolog",
    "urinary",
    "prostate",
    "ureter",
    "urethra",
    "testic",
    "testis",
    # ── ja-JP ──（膀胱／腎／尿路／尿道／泌尿 與繁中同漢字,已被上面涵蓋；
    #   以下是 ja 特有寫法:前立腺≠前列腺、睾丸≠睪丸、尿管≠輸尿管）
    "前立腺",
    "睾丸",
    "精巣",
    "尿管",
    "ぼうこう",
    "じんぞう",
    # ── ko-KR ──
    "방광",
    "신장",
    "신우",
    "콩팥",
    "요로",
    "요관",
    "요도",
    "전립선",
    "전립샘",
    "고환",
    "비뇨",
    # ── vi-VN ──
    "bàng quang",
    "thận",
    "niệu quản",
    "niệu đạo",
    "tiết niệu",
    "tiền liệt tuyến",
    "tuyến tiền liệt",
    "tinh hoàn",
)

# ED 的「心血管疾病史」是**複合子項**（高血壓 / 冠狀動脈疾病 / 心肌梗塞 / 腦中風），
# 四項各自獨立 gate:病史只填「高血壓」時，心肌梗塞與腦中風仍完全未知，不得因為命中
# 任一子項就把整項判成已答（第二輪的錯）。故拆成四個詞群，四群都被提到才算涵蓋。
# 泛稱詞（心臟病 / 心血管 / 心衰 / 心律不整 / 動脈硬化…）刻意不列入任何子項——寫得
# 越模糊越該口頭問清楚。
_HYPERTENSION_TERMS: tuple[str, ...] = (
    "高血壓",
    "血壓高",
    "血壓偏高",
    "hypertension",
    "htn",
    # ja 用簡化漢字「圧」,與繁中「壓」不同字
    "高血圧",
    "血圧が高",
    # ko / vi
    "고혈압",
    "tăng huyết áp",
    "cao huyết áp",
)

_CORONARY_TERMS: tuple[str, ...] = (
    "冠狀動脈",
    "冠心",
    "coronary",
    "心絞痛",
    "angina",
    "心導管",
    # 刻意不收「支架」——泌尿科的輸尿管雙 J 管在病患自填欄位也常寫成「支架」。
    "angioplasty",
    "繞道",
    "cabg",
    # ja（冠動脈≠冠狀動脈、狭心症≠心絞痛）
    "冠動脈",
    "狭心症",
    "心臓カテーテル",
    "バイパス手術",
    # ko
    "관상동맥",
    "협심증",
    "관상 동맥",
    # vi
    "động mạch vành",
    "đau thắt ngực",
    "bắc cầu mạch vành",
)

_MYOCARDIAL_INFARCTION_TERMS: tuple[str, ...] = (
    "心肌梗塞",
    "心梗",
    "myocardial",
    "infarct",
    # ja 寫「心筋梗塞」（筋≠肌）
    "心筋梗塞",
    # ko / vi
    "심근경색",
    "nhồi máu cơ tim",
)

_STROKE_TERMS: tuple[str, ...] = (
    "中風",
    "腦梗",
    "腦血管",
    "stroke",
    "cerebrovascular",
    # ja 用簡化漢字「脳」
    "脳梗塞",
    "脳卒中",
    "脳出血",
    "脳血管",
    # ko
    "뇌졸중",
    "뇌경색",
    "뇌출혈",
    "중풍",
    # vi
    "đột quỵ",
    "tai biến mạch máu não",
    "nhồi máu não",
)

_DIABETES_TERMS: tuple[str, ...] = (
    "糖尿",
    "diabet",
    "t1dm",
    "t2dm",
    "iddm",
    "niddm",
    # ja「糖尿病」與繁中同漢字（已被「糖尿」涵蓋）；假名寫法另收
    "とうにょうびょう",
    # ko / vi
    "당뇨",
    "tiểu đường",
    "đái tháo đường",
)

# ── 取消資格的限定語:整「筆」不採計（→ 退回仍必問） ───────────
# 用藥欄:「已停用」「過敏」等於**沒有在吃**，卻含有藥名 → 不得判成已答＝是。
# 家族史:「轉移」（胃癌腎轉移）不是泌尿道原發惡性腫瘤 → 不得判成泌尿癌家族史。
# 一律只會讓判定更保守（多問一句），不會讓必問項被跳過。
_MEDICATION_DISQUALIFIERS: tuple[str, ...] = (
    "已停",
    "停用",
    "停藥",
    "沒在吃",
    "沒有在吃",
    "未服用",
    "曾服",
    "曾經吃",
    "以前吃",
    "過去服用",
    "過敏",
    "不能吃",
    "禁用",
    "discontinu",
    "stopped",
    "no longer",
    "allerg",
    # ja / ko / vi:與詞庫同輪補齊。限定語只會讓判定**更保守**（整筆不採計 → 退回
    # 仍必問）,所以這裡收詞的風險方向與涵蓋詞庫相反,不需要同等嚴格,但仍只收高確信詞。
    "中止",
    "服用していない",
    "飲んでいない",
    "やめました",
    "アレルギー",
    "중단",
    "끊었",
    "복용 안",
    "알레르기",
    "đã ngưng",
    "đã ngừng",
    "ngưng dùng",
    "không còn dùng",
    "dị ứng",
)

_FAMILY_HISTORY_DISQUALIFIERS: tuple[str, ...] = (
    "轉移",
    "metasta",
    "転移",  # ja 簡化漢字
    "전이",  # ko
    "di căn",  # vi
)


class TermGroup(NamedTuple):
    """涵蓋判定的一個「必要條件」詞群。

    label 只用在**複合子項**規則（same_entry=False 且多群）的部分涵蓋標註，
    讓必問行能寫出「已知高血壓、仍須問心肌梗塞…」。
    """

    label: str
    terms: tuple[str, ...]


class RiskFactorRule(NamedTuple):
    """某個 §3b 風險因子的 intake 涵蓋判定規則。

    keyword     對到 shared.CRITICAL_RISK_FACTORS 那串自由文字 factor 的關鍵字。
    field       可涵蓋它的 intake 欄位。
    groups      每一群都要命中一項才算涵蓋。
    same_entry  True＝所有詞群必須命中在**同一筆**記錄內（家族史:同一位家人身上
                同時有惡性腫瘤與泌尿部位）。False＝複合子項，各子項可分散在不同筆
                （心血管四子項），但**每一項都要被提到**。
    disqualifiers 該筆記錄含這些限定語時整筆不採計。
    """

    keyword: str
    field: str
    groups: tuple[TermGroup, ...]
    same_entry: bool = False
    disqualifiers: tuple[str, ...] = ()


class RiskFactorVerdict(NamedTuple):
    """三態判定結果。

    uncovered 只在「部分涵蓋」（複合子項命中一部分）時非空，內容是**尚未被涵蓋**的
    子項標籤，供必問行標註；完全沒命中或完全涵蓋時皆為空。
    """

    state: str
    field: str | None
    value: str | None
    uncovered: tuple[str, ...] = ()


# shared.CRITICAL_RISK_FACTORS 的 factors 是沒有穩定 id 的自由文字，故以關鍵字比對；
# 比不到 → None → 該項**永遠必問**。這個 fail 方向是安全的:上游改寫 factor 文字最多
# 讓已知項被多問一次，不會讓必問項被誤跳過。
# 吸菸史 / 血脂異常刻意沒有對應欄位——intake 表單根本沒有這兩欄，永遠必須問。
_ANTICOAGULANT_GROUP = TermGroup("抗凝血／抗血小板藥物", _ANTICOAGULANT_TERMS)
_CARDIOVASCULAR_GROUPS: tuple[TermGroup, ...] = (
    TermGroup("高血壓", _HYPERTENSION_TERMS),
    TermGroup("冠狀動脈疾病", _CORONARY_TERMS),
    TermGroup("心肌梗塞", _MYOCARDIAL_INFARCTION_TERMS),
    TermGroup("腦中風", _STROKE_TERMS),
)

_RISK_FACTOR_RULES: tuple[RiskFactorRule, ...] = (
    RiskFactorRule(
        "抗凝血",
        "medications",
        (_ANTICOAGULANT_GROUP,),
        disqualifiers=_MEDICATION_DISQUALIFIERS,
    ),
    RiskFactorRule(
        "抗血小板",
        "medications",
        (_ANTICOAGULANT_GROUP,),
        disqualifiers=_MEDICATION_DISQUALIFIERS,
    ),
    RiskFactorRule(
        "家族史",
        "family_history",
        (TermGroup("惡性腫瘤", _MALIGNANCY_TERMS), TermGroup("泌尿部位", _UROLOGIC_TERMS)),
        same_entry=True,
        disqualifiers=_FAMILY_HISTORY_DISQUALIFIERS,
    ),
    RiskFactorRule("心血管疾病史", "medical_history", _CARDIOVASCULAR_GROUPS),
    RiskFactorRule("糖尿病", "medical_history", (TermGroup("糖尿病", _DIABETES_TERMS),)),
)

# 拆「筆」的分隔符。intake 的 list 欄位由 patient_context 用「、」串接（家族史為
# 「關係：病名」），其餘標點是病患自由輸入的容錯。
_ENTRY_SEPARATORS: tuple[str, ...] = ("、", "，", ",", "；", ";", "\n", "/", "|", "+")

# classify_risk_factor 的三態
MUST_ASK = "must_ask"
ANSWERED_NO = "answered_no"
ANSWERED_YES = "answered_yes"


def _rule_for_factor(factor: str) -> RiskFactorRule | None:
    """回該 factor 的涵蓋判定規則；無對應規則回 None（＝永遠必問）。"""
    for rule in _RISK_FACTOR_RULES:
        if rule.keyword in factor:
            return rule
    return None


def risk_factor_intake_field(factor: str) -> str | None:
    """某個 §3b 風險因子可由哪個 intake 欄位涵蓋；無對應欄位回 None（＝永遠必問）。"""
    rule = _rule_for_factor(factor)
    return rule.field if rule else None


def is_explicit_none(value: str) -> bool:
    """該 intake 值是否為病患明確表示的「無」。"""
    return value.strip().lower() in _EXPLICIT_NONE_VALUES


def split_intake_entries(value: str) -> list[str]:
    """把一個 intake 欄位值拆成「筆」（家族史一位家人一筆、用藥一種藥一筆）。

    涵蓋判定必須逐筆做，否則條件會跨筆湊出來——「母親：乳癌、父親：攝護腺肥大」
    被當成一個 haystack 時「癌」與「攝護腺」分別來自不同家人，卻會判成
    「泌尿道惡性腫瘤家族史＝有」（BLOCKER D，會讓 SOAP 捏造家族史）。
    """
    normalized = value
    for separator in _ENTRY_SEPARATORS[1:]:
        normalized = normalized.replace(separator, _ENTRY_SEPARATORS[0])
    return [part.strip() for part in normalized.split(_ENTRY_SEPARATORS[0]) if part.strip()]


def _hit_group_indices(entry: str, groups: tuple[TermGroup, ...]) -> set[int]:
    haystack = entry.lower()
    return {
        index
        for index, group in enumerate(groups)
        if any(term in haystack for term in group.terms)
    }


def evaluate_coverage(value: str, rule: RiskFactorRule) -> tuple[bool, tuple[str, ...]]:
    """逐筆判定 intake 值是否涵蓋此風險因子。

    回 (是否完全涵蓋, 尚未涵蓋的子項標籤)。第二個值只在**部分涵蓋**時非空——
    完全沒命中時回空 tuple（必問行不標註），完全涵蓋時也是空。
    帶取消資格限定語（已停用 / 過敏 / 轉移）的「筆」整筆不採計。
    """
    usable = [
        entry
        for entry in split_intake_entries(value)
        if not any(bad in entry.lower() for bad in rule.disqualifiers)
    ]
    if rule.same_entry:
        # 家族史:必須有**同一筆**同時滿足所有詞群；部分命中不做標註（那些詞群是
        # 同一件事的兩個屬性，拆開講沒有臨床意義）。
        covered = any(
            len(_hit_group_indices(entry, rule.groups)) == len(rule.groups)
            for entry in usable
        )
        return covered, ()

    hit: set[int] = set()
    for entry in usable:
        hit |= _hit_group_indices(entry, rule.groups)
    if len(hit) == len(rule.groups):
        return True, ()
    if not hit:
        return False, ()
    return False, tuple(
        group.label for index, group in enumerate(rule.groups) if index not in hit
    )


def known_history_fields(patient_info: dict[str, Any]) -> dict[str, str]:
    """回 {欄位: 值}，含 patient_info 四欄所有非空值（**不分來源**）。

    含 `patients` 表的舊資料，因此**不可**直接拿來當任何禁問／跳過的依據
    （BLOCKER E 就是這樣把回診病患的舊病歷變成硬性禁問）。目前只有兩個用途:
    `session_intake_fields` 的無標記 fallback 起點，以及「來源不可證而被保守降級」
    的日誌。所有面向 prompt 的清單一律走 `session_intake_fields`。
    """
    provided: dict[str, str] = {}
    for key in INTAKE_FIELD_LABELS:
        raw = patient_info.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            provided[key] = value
    return provided


def session_intake_fields(patient_info: dict[str, Any]) -> dict[str, str]:
    """回 {欄位: 值}，只含**可證明來自本次場次 intake** 的非空值。

    §3b 是安全不變式，不能被 `patients` 表的舊資料（可能是幾個月前）關掉。
    - patient_info 帶 `INTAKE_SOURCE_KEY` 子 dict 時 → 完全以它為準（精確來源）。
    - 沒帶時 → 保守 fallback，只採信兩種可證明來自本次 intake 的值:
      (a) `_INTAKE_ONLY_FIELDS_WITHOUT_MARKER`（build_patient_info 對這些欄位沒有
          patients 表 fallback 分支）；
      (b) 值為明確的「無」——build_patient_info 只有在本次 intake 的 `no_*` 旗標為
          True 時才會寫入「無」。
      其餘（例如 medications="aspirin"）來源不可證，一律當未知 → 仍必問。
    """
    info = patient_info or {}
    marker = info.get(INTAKE_SOURCE_KEY)
    if isinstance(marker, dict):
        return {
            key: str(raw).strip()
            for key in INTAKE_FIELD_LABELS
            if (raw := marker.get(key)) is not None and str(raw).strip()
        }

    fallback: dict[str, str] = {}
    for key, value in known_history_fields(info).items():
        if key in _INTAKE_ONLY_FIELDS_WITHOUT_MARKER or is_explicit_none(value):
            fallback[key] = value
    return fallback


def classify_risk_factor(factor: str, intake: dict[str, str]) -> RiskFactorVerdict:
    """三態判定某個 §3b 風險因子。回 RiskFactorVerdict(state, 欄位, 值, 未涵蓋子項)。

    state ∈ {MUST_ASK, ANSWERED_NO, ANSWERED_YES}。`intake` 必須是
    `session_intake_fields()` 的輸出（只含本次場次 intake）。
    """
    rule = _rule_for_factor(factor)
    if rule is None:
        return RiskFactorVerdict(MUST_ASK, None, None)
    value = intake.get(rule.field)
    if not value:
        return RiskFactorVerdict(MUST_ASK, rule.field, None)
    if is_explicit_none(value):
        return RiskFactorVerdict(ANSWERED_NO, rule.field, value)
    covered, uncovered = evaluate_coverage(value, rule)
    if covered:
        return RiskFactorVerdict(ANSWERED_YES, rule.field, value)
    # 該欄有值但不涵蓋這個風險因子（用藥只列 amlodipine、家族史的癌與泌尿部位分屬
    # 不同家人、心血管四子項只提到高血壓）→ 仍屬未知，維持必問。
    return RiskFactorVerdict(MUST_ASK, rule.field, value, uncovered)


def split_risk_factors_by_intake(
    chief_complaint: Any, patient_info: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """把本主訴的 §3b 風險因子拆成（仍須問, 本次 intake 已涵蓋）。

    回傳兩份**已渲染的條列行**；主訴無匹配風險因子時回 ([], [])。
    """
    groups = get_critical_risk_factors_for_complaint(chief_complaint)
    if not groups:
        return [], []
    info = patient_info or {}
    intake = session_intake_fields(info)
    # 沒有來源標記時，「值涵蓋但來源不可證」的欄位會被保守降級成必問（多問一句）。
    # 這是暫時狀態，patient_context 補上 INTAKE_SOURCE_KEY 後就會精確判定；先讓它
    # 在日誌可見，否則這種降級是靜默的、只會在真跑逐字稿裡才看得出來。
    unprovable = (
        {}
        if isinstance(info.get(INTAKE_SOURCE_KEY), dict)
        else {k: v for k, v in known_history_fields(info).items() if k not in intake}
    )
    must_ask: list[str] = []
    covered: list[str] = []
    downgraded: list[str] = []
    for group in groups:
        for factor in group["factors"]:
            state, field, value, uncovered = classify_risk_factor(factor, intake)
            if state == MUST_ASK and field in unprovable:
                rule = _rule_for_factor(factor)
                if rule and evaluate_coverage(unprovable[field], rule)[0]:
                    downgraded.append(factor)
            # D-1：`value` 是病患 intake 自填文字，會被插進 prompt 的條列行 →
            # 一律消毒（判定本身用未消毒原值，消毒只影響渲染，不影響三態結論）。
            safe_value = sanitize_for_prompt(value)
            if state == ANSWERED_NO and field:
                covered.append(
                    f"- {factor} → 病患已在本次 intake 表單自填「無」"
                    f"（{INTAKE_FIELD_LABELS[field]}：{safe_value}）＝已問到，答案為「否」"
                )
            elif state == ANSWERED_YES and field:
                # 只陳述「表單上填了什麼」，**不得**要 LLM 把它當成已確認的臨床事實
                # 寫進病史——intake 是病患自填、可能誤填或填錯欄位（BLOCKER D）。
                covered.append(
                    f"- {factor} → 病患於本次 intake 表單自填為"
                    f"「{INTAKE_FIELD_LABELS[field]}：{safe_value}」，不需重複詢問；"
                    "記錄時須標明此為**病患表單自填**內容（例如「病患表單自填：…」），"
                    "不得改寫成已由問診確認的事實，也不得替病患補上表單沒寫的細節"
                )
            elif uncovered:
                # 複合子項只被涵蓋一部分（例如病史只寫高血壓）→ 仍必問，但標明
                # 已知的部分不必重問，避免 AI 拿表單上已有的項目再問一次。
                must_ask.append(
                    f"- {factor}（表單自填「{safe_value}」只涵蓋其中一部分，"
                    f"仍須逐一口頭問到：{'、'.join(uncovered)}）"
                )
            else:
                must_ask.append(f"- {factor}")
    if downgraded:
        logger.warning(
            "§3b 風險因子因無法證明來源而保守維持必問（patient_context 尚未提供 "
            "%s 標記，無法分辨本次 intake 與 patients 表舊資料）| complaint=%s, factors=%s",
            INTAKE_SOURCE_KEY,
            chief_complaint,
            downgraded,
        )
    return must_ask, covered


def count_must_ask_risk_factors(
    chief_complaint: Any, patient_info: dict[str, Any]
) -> int:
    """§3b 配額用的 K：**本次 intake 過濾後**仍必須口頭問到的風險因子題數。

    D-2 的根因：`conclusion_policy` 的動態硬上限與軟門檻下限原本吃
    `shared.count_critical_risk_factors_for_complaint`（只看主訴的未過濾 K），但
    prompt 端的必問清單早已被 intake 三態判定過濾過。血尿場 K=3、intake 已涵蓋
    2 項時，配額仍照 K=3 抬高 → 軟門檻下限 base+3-1=12、硬上限 base+3+2=15，
    病患實際只剩 1 個風險因子要答，卻被多綁 6–7 輪才收得了尾。

    **方向護欄**：must_ask ⊆ 全部 factors，故過濾後 K 天生 ≤ 原 K；這裡再用
    `min()` 明寫一次，確保任何上游改動都不可能讓 K 變大（K 變大＝配額被抬高＝
    病患被多綁更多輪，是這個修復絕不能引入的反方向）。
    """
    total = count_critical_risk_factors_for_complaint(chief_complaint)
    if total <= 0:
        return 0
    must_ask, _covered = split_risk_factors_by_intake(chief_complaint, patient_info or {})
    return max(0, min(len(must_ask), total))


def render_critical_risk_factor_items_with_intake(
    chief_complaint: Any, patient_info: dict[str, Any]
) -> tuple[str, str]:
    """§3b 關鍵風險因子清單的 intake 感知渲染（生產路徑唯一入口）。

    conversation 與 supervisor 都只呼叫這一支；`shared.render_critical_risk_factor_items`
    是它的前身，已無生產呼叫端（見 needsFromOthers：待刪）。

    回 (必問條列字串, intake 已涵蓋條列字串)；無匹配主訴時兩者皆為 ""，
    §3b 段落完全不注入（不變式:其他主訴行為不變、不亂加問題）。
    conversation 的「必問 / 禁問」段與 supervisor 的「收尾 gate」共用此單一來源。
    """
    must_ask, covered = split_risk_factors_by_intake(chief_complaint, patient_info)
    return "\n".join(must_ask), "\n".join(covered)


def render_intake_known_block(patient_info: dict[str, Any]) -> str:
    """四欄中**本次 intake** 已填答者的條列（給「次要補問」段的禁問清單）；全空回 ""。

    2026-07-27 覆核 BLOCKER E:這段渲染出的是**硬性禁問**指令，先前用
    `known_history_fields`（不分來源）→ 幾個月前建檔的 `patients` 表舊病史／舊用藥
    也會變成禁問，而非 §3b 主訴（例如頻尿）沒有「必問清單優先」那條例外可以救援
    → 本次 intake 全空的回診病患，AI 會被舊病歷擋住、整場不問用藥。
    改與 §3b gating 同一個標準:只採信可證明來自**本次場次 intake** 的值。
    """
    provided = session_intake_fields(patient_info or {})
    # D-1：病患自填值 → 一律消毒後才插進 prompt（見 shared.sanitize_for_prompt）。
    return "\n".join(
        f"- {INTAKE_FIELD_LABELS[key]}：{sanitize_for_prompt(value)}"
        for key, value in provided.items()
    )


class LLMConversationEngine:
    """
    OpenAI GPT-4o 對話引擎

    根據病患主訴驅動結構化問診流程，
    一次一個問題地引導病患描述症狀細節。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 OpenAI 非同步客戶端

        Args:
            settings: 應用程式設定實例
        """
        self._settings = settings
        self._client = get_openai_client()
        self._model = settings.OPENAI_MODEL_CONVERSATION  # default gpt-4o
        self._temperature = settings.OPENAI_TEMPERATURE_CONVERSATION  # 0.7
        self._max_tokens = settings.OPENAI_MAX_TOKENS_CONVERSATION  # 2048
        # reasoning 模型(o1 / o3 / gpt-5 等)專用參數。"none" 代表傳統 chat
        # 模型路徑(gpt-4o),程式會完全不送 reasoning_effort 並改送 temperature。
        self._reasoning_effort = settings.OPENAI_REASONING_EFFORT_CONVERSATION

        logger.info(
            "LLMConversationEngine 初始化 | model=%s, temperature=%.1f, max_tokens=%d, reasoning_effort=%s",
            self._model,
            self._temperature,
            self._max_tokens,
            self._reasoning_effort,
        )

    def build_system_prompt(
        self,
        chief_complaint: str,
        patient_info: dict[str, Any],
        language: str | None = None,
    ) -> str:
        """
        根據主訴與病患資訊建構系統提示詞

        Args:
            chief_complaint: 病患主訴（例如「血尿」、「頻尿」）
            patient_info: 病患基本資訊（姓名、年齡、性別、病史等）
            language:       場次語言（BCP-47，如 "en-US"）；用於決定 LLM 輸出語言,
                            None 會退回 i18n_messages 的 DEFAULT_LANGUAGE（zh-TW）。

        Returns:
            完整系統提示詞字串
        """
        # D-1：主訴可能是病患自填的 200 字自由文字（`chief_complaint_text`），而且它被
        # 插在 `## 主訴` 標題的**下一行行首**——多行值的第二行若以 `##` 起頭，渲染後
        # 與真正的區段標題無法區分。消毒只摺疊空白與剝掉開頭的 `#`，不改臨床字面，
        # 故下游的紅旗 / §3b 主訴關鍵字比對結果不變。
        chief_complaint = sanitize_for_prompt(chief_complaint)

        # 角色定位第二行與尾段的「輸出語言（硬性規定）」都依 session 語言查表。
        # 之前硬寫「使用繁體中文與病患溝通」會導致前端傳 en-US 也被 LLM 以中文回覆。
        role_language_line = _i18n_get("llm.conversation_language_rule", language)
        output_language_rule = _i18n_get(
            "llm.conversation_output_language_rule", language
        )
        red_flag_alert_rule = _i18n_get(
            "llm.conversation_red_flag_alert_rule", language
        )
        # #5：語音只支援場次語言；病患問能否改台語/客語/方言時，AI 不可宣稱聽得懂，
        # 要請對方改用場次語言或改打字，避免「AI 說可以但其實聽不懂」的過度承諾。
        unsupported_speech_rule = _i18n_get(
            "llm.conversation_unsupported_speech_rule", language
        )
        # 組合病患資訊摘要
        # 標籤與性別採英文內部碼（Name / Age / Gender / male / female），
        # 避免 zh-TW 標籤在 en-US session 被 LLM 照抄（「性別：male」）。
        # D-1：所有**病患自由輸入**的值（姓名、四欄病史、主訴自填文字）一律先過
        # sanitize_for_prompt——它們原本零消毒直入 system prompt，多行 + `##` 開頭
        # 就能在渲染後偽裝成一個新的指令區段（見 shared.sanitize_for_prompt 註解）。
        # age/gender 是內部碼（int / enum value），不是自由文字，不需消毒。
        patient_summary_parts: list[str] = []
        if (name := sanitize_for_prompt(patient_info.get("name"))):
            patient_summary_parts.append(f"Name: {name}")
        # age 用 `is not None`——truthy 判斷會讓 age==0（未滿一歲）整行從 prompt 消失，
        # 且與 supervisor.build_patient_info_str 的行為不一致。
        if patient_info.get("age") is not None:
            patient_summary_parts.append(f"Age: {patient_info['age']}")
        if patient_info.get("gender"):
            patient_summary_parts.append(f"Gender: {patient_info['gender']}")
        if (value := sanitize_for_prompt(patient_info.get("medical_history"))):
            patient_summary_parts.append(f"Past medical history: {value}")
        if (value := sanitize_for_prompt(patient_info.get("medications"))):
            patient_summary_parts.append(f"Current medications: {value}")
        if (value := sanitize_for_prompt(patient_info.get("allergies"))):
            patient_summary_parts.append(f"Allergies: {value}")
        if (value := sanitize_for_prompt(patient_info.get("family_history"))):
            patient_summary_parts.append(f"Family history: {value}")

        patient_section = (
            "\n".join(patient_summary_parts)
            if patient_summary_parts
            else "(not provided)"
        )
        # HPI 10 欄框架與主訴相關紅旗都從 shared.py 單一來源渲染,
        # 與 SOAP hpi schema、red_flag detector 知識庫對齊(P1-D、P2-E)。
        hpi_section = render_hpi_checklist()
        red_flags_section = render_red_flags_for_conversation(chief_complaint)

        # §3b：特定高風險主訴(血尿 / PSA / ED)的關鍵風險因子提升為「與 HPI 同級必問」,
        # 不再淪為只在十欄達 7 成才問的「次要補問」→ 避免核心十欄填滿就收尾、觸不到
        # 吸菸史 / 抗凝血 / 泌尿癌家族史(血尿惡性分層)、心血管風險(ED)。無匹配主訴回空字串,
        # critical_risk_section 保持 ""（其他主訴完全不受影響）。
        # intake 已涵蓋的風險因子**不進必問清單**，改進禁問清單（見模組頂端註記）。
        must_ask_items, intake_covered_items = (
            render_critical_risk_factor_items_with_intake(chief_complaint, patient_info)
        )
        critical_risk_section = ""
        if must_ask_items:
            critical_risk_section = (
                "## 本主訴的關鍵風險因子（與 HPI 十欄同級，收尾前必問）\n"
                f"根據病患主訴「{chief_complaint}」，下列風險因子屬**必問**，重要性與 HPI 十欄相同，\n"
                "**不得**歸入下方「次要補問」而延到 HPI 達 7 成後才問，也不得因核心十欄已填滿就略過：\n"
                f"{must_ask_items}\n"
                "規則：每輪仍只問一題，**應在 HPI 中後段就開始穿插詢問這些風險因子、不要全部延到"
                "最後**（避免問診回合用盡時仍沒問到）；問診收尾前必須都問到。"
                "病患已明確表示不知道／沒有／記不得，即視為已問到，"
                "不得換句話對同一項再重問（遵守 don't-know 不重問規則）。\n\n"
            )
        if intake_covered_items:
            critical_risk_section += (
                "## 風險因子中「本次 intake 已涵蓋」的項目（禁止再問）\n"
                "下列項目病患已在本次 intake 表單答過（明確填「無」，或填的內容已涵蓋"
                "該風險因子），視同**你已經問過並得到答案**，\n"
                "**一律不得**再問——換句話問、確認式問法"
                "（例如「請問您有沒有在吃⋯⋯」）同樣禁止：\n"
                f"{intake_covered_items}\n"
                "只有本清單列出的項目算已問到；上面「必問」清單裡的項目**即使 intake "
                "其他欄位有填內容，也仍然必須逐一口頭問到**。\n"
                "若臨床上需要細節，只能針對「與本主訴直接相關的單一具體點」追問，"
                "不得請病患重述整份清單。\n\n"
            )

        # 「次要補問」段落列的正是 intake 四欄（用藥 / 過敏 / 家族史 / 病史）。舊版只留一句
        # 「若病患於 intake 表單已提供上述資訊，則不需重複詢問」，要 LLM 自己跨段比對 →
        # 實測仍會重問。改成把已填答項連同值明列成禁問清單（未填答者才留在可補問範圍）。
        intake_known_block = render_intake_known_block(patient_info)
        if intake_known_block:
            secondary_intake_rule = (
                "**下列項目病患已於本次 intake 表單填答，視同你已經問過並"
                "得到答案，一律不得再問**（換句話問、確認式問法同樣禁止）：\n"
                f"{intake_known_block}\n"
                "只有上面沒列到的項目，才可依本段規則補問；若臨床上需要細節，"
                "只能針對與主訴直接相關的單一具體點追問，不得請病患重述整份清單。\n"
                "上列內容為**病患表單自填**，記錄時請標明來源，不得改寫成"
                "已由問診確認的事實。"
            )
            # 優先序:上方 §3b「必問」清單勝過本段禁問清單。否則會出現
            # 「用藥欄有 amlodipine（本段禁問「目前用藥」）」把「抗凝血劑必問」擋掉
            # ——那正是 BLOCKER #5 要修的漏問路徑。
            if must_ask_items:
                secondary_intake_rule += (
                    "\n**例外（優先序最高）**：上方「本主訴的關鍵風險因子」必問清單裡的"
                    "項目**不受本段禁問限制**——即使該項目所屬欄位（例如目前用藥、"
                    "過去病史、家族史）在上面已列出紀錄，你**仍必須**逐一針對那些"
                    "風險因子口頭問到答案（現有紀錄未涵蓋該風險因子時才會出現在必問清單）。"
                )
        else:
            secondary_intake_rule = (
                "若病患於 intake 表單已提供上述資訊，則不需重複詢問，直接進入 HPI。"
            )

        # 把「輸出語言」規則放在最前面 — LLM 對 prompt 開頭權重最高,
        # 尾段的規則容易被中間大量中文內容稀釋,造成 en-US 場次偶發以中文回覆。
        system_prompt = f"""{output_language_rule.lstrip()}

你是一位專業的泌尿科 AI 問診助手，負責協助進行初步問診。

## 角色定位
- 你是泌尿科門診的 AI 問診助手
- {role_language_line}
- 語氣親切、專業且具同理心

## 病患資訊
{patient_section}

## 主訴
{chief_complaint}

## 主要問診任務（HPI 十欄框架）
根據病患的主訴「{chief_complaint}」，依序收集下列十個 HPI 面向：
{hpi_section}

{critical_risk_section}## 次要補問（HPI 完整度較高後才進入）
當上述 HPI 十欄已大致問完（約 7 成以上），請視對話狀況補問下列臨床文件需要的資訊，
每次仍只問一題，且只在與主訴相關時才問：
- 過往泌尿科相關疾病或手術史
- 目前服用中的藥物（特別是抗凝血劑、利尿劑、攝護腺藥物）
- 已知藥物過敏
- 家族是否有泌尿道癌症、腎結石或攝護腺疾病史
- 相關生活習慣（例如飲水量、咖啡因、吸菸，限與主訴有關聯時）
- 其他系統的不適（review of systems，僅在臨床相關時補問）

{secondary_intake_rule}

## 問診準則
- 使用病患能理解的日常用語，避免過度使用醫學專業術語
- 若病患的回答不夠明確，可進行追問以釐清
- 適時表達關心與同理心（例如「我了解這對您來說很不舒服」）
- 不做診斷或治療建議，僅進行症狀收集
- 每次回覆最多 2 句話，請保持簡潔明瞭
- {red_flag_alert_rule}
- {unsupported_speech_rule}
- 不要重複詢問病患在本次對話中已明確回答過、或已表示不知道／記不得／無法回答的問題；已回答或已確認無法提供時，請接續尚未釐清的下一個面向，不要換句話重問。
- 【硬性規定，從對話第一題就適用】病患對某個 HPI 面向表示不知道／記不得／無法回答後，
  不得以任何換句話形式對「同一面向」再追問變化提問——例如已問過 Onset（發生時間）
  卻改問「是突然還是漸進發生的」、已問過 Duration（持續時間）卻改問「間歇性還是持續性」
  或「多久了」、已問過 Severity（嚴重度）卻改問「幾分」或「有多痛」，這些都算同一欄位
  的換句話重問，一律禁止；即使是對話的第一個問題也適用此規則。請直接跳到下一個尚未
  釐清的 HPI 面向，不要在同一面向反覆繞。

{SINGLE_QUESTION_RULE}

## 紅旗症狀注意
請特別留意以下可能需要緊急處理的紅旗症狀：
{red_flags_section}

（偵測到紅旗時，依上方問診準則裡的紅旗提醒規則執行，不要在此另寫提醒語。）

## 回覆格式
- 使用自然、口語化的語言（語言依本文件最開頭的「輸出語言」規定）
- 每次回覆簡潔明瞭，通常 1-3 句話
- 不使用 markdown 格式（不加粗、不用清單）或特殊符號
- 不說「好的」「了解」等空洞開場白，直接進入問題

## 最後重申（硬性規定）
- 本 prompt 中的中文段落都是**內部指引**,你**不得**把其中任何中文詞彙、標題、
  標籤或例句照抄到給病患的回覆中。
- 你的回覆必須 100% 採用本文件最開頭「輸出語言」指定的語言。"""

        return system_prompt

    def build_wrap_up_prompt(self, language: str | None = None) -> str:
        """收尾專用「極簡」系統提示：只含輸出語言規則 + 角色定位，**刻意不含** HPI 十欄 /
        次要補問 / 風險因子等任何 questioning 框架。

        根因（實測 ED 場）：即使把收尾指示前後夾擊、文案強化到「不得問任何臨床問題」，
        中段龐大的 questioning 框架仍會讓 LLM 在收尾輪硬問一題（反覆問次要用藥問題、
        留下懸空問句才結束）。移除競爭指令、只留收尾語境，是唯一可靠解。實際收尾規則由
        format_messages(conclude=True) 前後夾擊注入，故此處不重複附加。
        """
        output_language_rule = _i18n_get(
            "llm.conversation_output_language_rule", language
        )
        role_language_line = _i18n_get("llm.conversation_language_rule", language)
        return f"{output_language_rule.lstrip()}\n\n{role_language_line}"

    def format_messages(
        self,
        history: list[dict[str, Any]],
        system_prompt: str,
        supervisor_guidance: dict[str, Any] | None = None,
        language: str | None = None,
        conclude: bool = False,
    ) -> list[dict[str, str]]:
        """
        將對話歷史格式化為 OpenAI Chat Completions API 的訊息格式

        Args:
            history: 對話歷史列表，每筆包含 role 和 content
            system_prompt: 系統提示詞
            supervisor_guidance: 來自 Supervisor 的動態指導
            language: 場次語言（BCP-47），用來選擇 Supervisor 指導段的區段標題。
            conclude: 本輪是否要收尾（HPI 達標或回合硬上限）。True 時附加收尾指示，
                      讓 LLM 講結束語、不再發問；之後 handler 會自動完成場次。

        Returns:
            格式化後的訊息列表
        """
        final_system_prompt = system_prompt

        # #2：Supervisor 指導是「上一輪」結果（fire-and-forget，分析時還沒看到病患對該題的回答），
        # next_focus 常仍指向 AI 剛問過的題目 → 偶發重複提問。對策：(a) 逾時 fallback 佔位不注入；
        # (b) 注入指導時附「已答過或已表示不知道就別重問」硬性護欄（優先級高於指導本身）。
        # 不改指導管線本身，純消費端 prompt。
        # 收尾輪（conclude）**完全跳過** next_focus 注入——next_focus 本質是「下一題要問什麼」，
        # 在收尾輪注入等於再塞一個發問指令與收尾規則打架（實測會讓 LLM 收尾輪硬問一題）。
        # (c) 2026-08-17：guidance 的一輪延遲撞上「不知道」時，pending next_focus 常正是
        # 病患**剛剛拒答**的那一欄（它就是上一輪叫 AI 問的題目）。既有的 no_repeat 護欄
        # 只是叫 LLM 自己判斷，實測 LLM 改成「換句話問得軟一點」→ e2e
        # a2_no_duration_reask_after_dontknow FAIL。改由 next_focus_guard 確定性判斷：
        # 只有「剛被拒答的欄位 ∩ next_focus 指向的欄位」非空時才換成推進指令，
        # 指向別欄一律原樣注入（拒答 A 後改問 B 是正確行為）。
        if not conclude and supervisor_guidance and not supervisor_guidance.get("fallback"):
            next_focus = effective_next_focus(
                history, supervisor_guidance, language
            )
            if next_focus:
                section_title = _i18n_get(
                    "llm.supervisor_guidance_section", language
                )
                no_repeat = _i18n_get("llm.supervisor_guidance_no_repeat", language)
                final_system_prompt += f"\n\n{section_title}\n{next_focus}\n{no_repeat}"

        # (d) 2026-08-17 第三輪 e2e：把過期指導換掉之後，Supervisor 與注入文字都已不再
        # 提 Duration，對話 LLM **仍自己**問出「頻尿的感覺是一直都有，還是有時候才會出現」。
        # 靜態問診準則裡那條「不得換句話重問」在長 prompt 中段競爭不過當下語境 →
        # 改用與收尾指示相同的「三明治」：把**本輪限定**、且只列**剛被拒答那一欄**
        # 換句話例句的硬性禁令放到最前與最後。收尾輪不加（那輪本來就不發問）。
        if not conclude:
            dont_know_ban = build_dont_know_ban(
                declined_fields_from_history(history), language
            )
            if dont_know_ban:
                final_system_prompt = (
                    f"{dont_know_ban}\n{final_system_prompt}\n{dont_know_ban}"
                )

        # 收尾指示「三明治」：同時置於系統提示最前（最高優先）與最後（最高 recency），
        # 覆蓋前面 Supervisor 的 next_focus。單靠尾段附加時，中段龐大的 HPI/次要補問/
        # 風險因子 questioning 框架仍會讓 LLM 在收尾輪硬問一題（實測 ED 場問了次要用藥
        # 問題、留下懸空問句才結束）→ 前後夾擊強化「本輪零發問、只講收尾語」的遵從。
        if conclude:
            wrap_rule = _i18n_get("llm.conversation_wrap_up_rule", language)
            final_system_prompt = wrap_rule + "\n" + final_system_prompt + wrap_rule

        messages: list[dict[str, str]] = [
            {"role": "system", "content": final_system_prompt}
        ]

        for entry in history:
            role = entry.get("role", "user")
            content = entry.get("content", "")

            # 將內部角色對應到 OpenAI API 角色
            if role in ("patient", "user"):
                messages.append({"role": "user", "content": content})
            elif role in ("assistant", "ai"):
                messages.append({"role": "assistant", "content": content})
            elif role == "system" and str(content).startswith(HISTORY_SUMMARY_PREFIX):
                # D-8：`_cap_conversation_history` 把超過 CONVERSATION_HISTORY_MAX_TURNS
                # 的舊輪次壓成**一則** role="system" 的摘要，就是為了「不靜默丟棄舊輪次、
                # 以免遺失紅旗臨床脈絡」。但這裡原本無條件跳過所有 system 歷史 →
                # 摘要**從來沒有進過 LLM**，壓縮＝丟棄，長場次的前段病史對 AI 完全消失。
                # 放行這一則（且**只放行**帶 `[前段對話摘要]` 前綴的那一則，其餘 system
                # 歷史仍跳過），比改 `_cap_conversation_history` 的 role 侵入更小：
                # 改成 assistant 會讓這則摘要一併漏進紅旗語意層的
                # `_build_conversation_summary`（那裡刻意排除摘要角色）。
                messages.append({"role": "system", "content": content})
            # 其餘 system 角色的歷史訊息跳過（系統提示已在最前面）

        return messages

    async def generate_response(
        self,
        messages: list[dict[str, str]],
        session_context: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """
        呼叫 OpenAI Chat Completions API 串流生成回應

        Args:
            messages: 格式化後的訊息列表（含 system prompt）
            session_context: 場次上下文資訊（用於日誌記錄等）

        Yields:
            回應文字片段（逐 chunk 產出）

        Raises:
            AIServiceUnavailableException: OpenAI API 不可用時
        """
        session_id = session_context.get("session_id", "unknown")

        try:
            logger.info(
                "呼叫 LLM 生成回應 | session=%s, model=%s, reasoning_effort=%s, messages_count=%d",
                session_id,
                self._model,
                self._reasoning_effort,
                len(messages),
            )

            # 取樣參數依「模型家族」決定，集中在 sampling_kwargs（openai_client.py）：
            # reasoning 家族（gpt-5.x／o 系列）送 reasoning_effort（"none" 是合法 API 值
            # ＝關 CoT，對話走這個最快）、傳統家族（gpt-4o）送 temperature。
            # 2026-08-22 之前這裡用 config=="none" 的字串約定判斷，gpt-5.6 拒收
            # temperature 之後那個約定就是錯的來源，故改綁模型名。
            # P1-#7：送 LLM 前先套 token budget（context_limit - max_tokens - reserve），
            # 超量時保留 system prompt、從頭部丟舊對話。
            budgeted = budget_messages(messages, self._model, self._max_tokens)

            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": budgeted,
                "max_completion_tokens": self._max_tokens,
                "stream": True,
                **sampling_kwargs(
                    self._model,
                    effort=self._reasoning_effort,
                    temperature=self._temperature,
                ),
                # 每輪重送同一 session 前綴 → 按場次路由快取（openai_client.cache_kwargs）
                **cache_kwargs(session_context.get("session_id")),
            }

            # 只有 stream 初建失敗（429 / timeout）才重試；一旦開始收 chunk 就不能重試。
            stream = await call_with_retry(
                lambda: self._client.chat.completions.create(**create_kwargs)
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text_piece = chunk.choices[0].delta.content
                    yield text_piece

        except Exception as exc:
            logger.error(
                "LLM 回應生成失敗 | session=%s, error=%s",
                session_id,
                str(exc),
                exc_info=True,
            )
            raise AIServiceUnavailableException(
                message="errors.ai_chat_unavailable",
                details={"session_id": session_id, "error": str(exc)},
            )
