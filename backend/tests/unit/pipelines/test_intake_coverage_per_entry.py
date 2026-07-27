"""§3b intake 涵蓋判定的**逐筆**語意（2026-07-27 覆核 BLOCKER D / E）。

前兩輪的教訓是「只往單一方向加測試」：第一輪只加「必須命中」→ 改出 over-trigger，
第二輪只加「不該命中」→ 改出 under-trigger。本檔刻意**成對**：每一個「不該判成已答」
的語料，旁邊就有一個「仍必須判成已答」的語料，兩邊一起釘住。

語料全部是**新寫的措辭**，不是從 `scripts/e2e_realopenai/driver.py` 的既有台詞
（aspirin／amlodipine／高血壓／第二型糖尿病／父親：膀胱癌）抄來的——除了三條任務
書明文指定要釘的回歸案例（「母親：乳癌、父親：攝護腺肥大」「父親：膀胱癌」
「aspirin（已停用）」），其餘家人稱謂、病名、藥名、語言都刻意換過，避免拿實作去
配適測試。

釘住的三件事：

1. BLOCKER D（HIGH，捏造病歷）：家族史涵蓋判定要**逐筆**做。整串當 haystack 時
   「母親：乳癌、父親：攝護腺肥大」的「癌」與「攝護腺」來自不同家人，卻被判成
   「泌尿道惡性腫瘤家族史＝有」→ 該項被跳過不問，而且 prompt 還叫 LLM 直接寫進
   病史 → SOAP 憑空生出病患沒有的泌尿道癌家族史。
2. 同型問題：用藥的「已停用／過敏」限定語、ED「心血管疾病史」的複合子項
   （命中高血壓就整項當已答 → 心肌梗塞／腦中風永遠不會被口頭問到）。
3. BLOCKER E（MEDIUM）：「次要補問」的禁問清單不得吃 `patients` 表舊資料。
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.pipelines.llm_conversation import (
    ANSWERED_YES,
    MUST_ASK,
    LLMConversationEngine,
    classify_risk_factor,
    render_critical_risk_factor_items_with_intake,
    render_intake_known_block,
    session_intake_fields,
    split_intake_entries,
)
from app.pipelines.patient_context import build_patient_info
from app.pipelines.prompts.shared import CRITICAL_RISK_FACTORS
from app.pipelines.supervisor import SupervisorEngine

_HEMATURIA = "血尿三天"
_ED = "勃起功能障礙"
_UNRELATED = "頻尿"

_ANTICOAG_LABEL = "抗凝血劑或抗血小板藥物使用"
_FAMILY_LABEL = "泌尿道惡性腫瘤"
_SMOKING_LABEL = "吸菸史"
_CV_LABEL = "心血管疾病史"
_DM_LABEL = "糖尿病"


def _factor(needle: str) -> str:
    for group in CRITICAL_RISK_FACTORS:
        for factor in group["factors"]:
            if needle in factor:
                return factor
    raise AssertionError(f"CRITICAL_RISK_FACTORS 找不到含「{needle}」的風險因子")


_F_ANTICOAG = _factor("抗凝血")
_F_FAMILY = _factor("家族史")
_F_CV = _factor("心血管疾病史")
_F_DM = _factor("糖尿病")


def _intake(**fields: str | None) -> dict:
    """帶本次 intake 來源標記的 patient_info（＝patient_context 的真實形狀）。"""
    flat = {
        key: fields.get(key)
        for key in ("medical_history", "medications", "allergies", "family_history")
    }
    return {"age": 68, "gender": "male", **flat, "intake_fields": dict(flat)}


# =============================================================================
# 1. 家族史：逐筆判定（BLOCKER D 核心，雙向）
# =============================================================================

# 「不該判成已答」：惡性詞與泌尿詞分屬**不同家人**，或同一家人只滿足其中一邊。
_FAMILY_NOT_COVERED = [
    "母親：乳癌、父親：攝護腺肥大",  # 任務書指定的回歸案例
    "姊姊：甲狀腺乳突癌、舅舅：腎結石",
    "外婆：大腸直腸癌、二伯：良性攝護腺肥大",
    "祖母：子宮頸癌、堂哥：尿路結石",
    "父親：肝癌、母親：慢性腎臟病",
    "aunt: colon cancer, uncle: enlarged prostate",
    "父親：胃癌併發腎轉移",  # 轉移灶不是泌尿道原發惡性腫瘤 → 判不準就必問
]

# 「仍必須判成已答」：同一筆記錄內同時滿足惡性＋泌尿部位（不得被逐筆化改成 under-trigger）。
_FAMILY_COVERED = [
    "父親：膀胱癌",  # 任務書指定的負向對照
    "二哥：輸尿管上皮癌",
    "外公：腎盂惡性腫瘤",
    "姑姑：乳癌、堂弟：睪丸癌",  # 混合：只要有一筆自己就命中兩邊
    "sister: renal cell carcinoma",
    "叔叔：攝護腺癌（PSA 篩檢發現）",
]


@pytest.mark.parametrize("value", _FAMILY_NOT_COVERED)
def test_family_history_across_relations_is_not_coverage(value: str):
    """惡性詞與泌尿詞來自不同家人 → **仍必問**（否則 SOAP 會捏造家族史）。"""
    verdict = classify_risk_factor(_F_FAMILY, {"family_history": value})
    assert verdict.state == MUST_ASK, f"跨家人湊出來的涵蓋：{value}"


@pytest.mark.parametrize("value", _FAMILY_COVERED)
def test_family_history_same_relation_still_counts_as_covered(value: str):
    """同一筆記錄同時命中惡性＋泌尿 → 仍算已答（不得誤傷成整場重問）。"""
    verdict = classify_risk_factor(_F_FAMILY, {"family_history": value})
    assert verdict.state == ANSWERED_YES, f"該判為已涵蓋卻退回必問：{value}"


def test_split_intake_entries_matches_patient_context_join():
    """patient_context 用「、」串接家族史 → 逐筆判定必須拆得回來。"""
    assert split_intake_entries("母親：乳癌、父親：攝護腺肥大") == [
        "母親：乳癌",
        "父親：攝護腺肥大",
    ]
    assert split_intake_entries("aunt: colon cancer, uncle: enlarged prostate") == [
        "aunt: colon cancer",
        "uncle: enlarged prostate",
    ]
    assert split_intake_entries("  單一筆  ") == ["單一筆"]


# =============================================================================
# 2. 用藥：限定語（已停用 / 過敏）不算「目前在吃」（雙向）
# =============================================================================

_MEDS_NOT_COVERED = [
    "aspirin（已停用）",  # 任務書指定的回歸案例
    "clopidogrel（去年已停藥）",
    "保栓通 已停用",
    "rivaroxaban - discontinued in March",
    "對 aspirin 過敏，改吃普拿疼",
    "以前吃過 warfarin，現在沒在吃",
    "tamsulosin 0.4mg、finasteride 5mg",  # 純泌尿科用藥，本來就不涵蓋
]

_MEDS_COVERED = [
    "拜瑞妥 20mg 每晚一顆",
    "Eliquis 5mg bid、bisoprolol",
    "氯吡格雷 75mg",
    "betaloc、伯基 100mg",
    "已停用 metformin、目前每天吃 aspirin",  # 逐筆：第二筆仍在吃 → 涵蓋
]


@pytest.mark.parametrize("value", _MEDS_NOT_COVERED)
def test_medication_qualifier_blocks_coverage(value: str):
    """「已停用／過敏」的藥名不代表病患現在在吃 → 抗凝血仍必問。"""
    verdict = classify_risk_factor(_F_ANTICOAG, {"medications": value})
    assert verdict.state == MUST_ASK, f"限定語沒被認出來：{value}"


@pytest.mark.parametrize("value", _MEDS_COVERED)
def test_medication_actually_taken_still_counts_as_covered(value: str):
    """真的在吃抗凝血／抗血小板藥 → 仍算已答（限定語邏輯不得誤傷）。"""
    verdict = classify_risk_factor(_F_ANTICOAG, {"medications": value})
    assert verdict.state == ANSWERED_YES, f"該判為已涵蓋卻退回必問：{value}"


# =============================================================================
# 3. ED 心血管：複合子項要逐項涵蓋（雙向）
# =============================================================================

# (病史值, 期望仍要口頭問到的子項)
_CV_PARTIAL = [
    ("血壓偏高（服藥控制）", ("冠狀動脈疾病", "心肌梗塞", "腦中風")),
    ("氣喘、痛風、腦梗塞後遺症", ("高血壓", "冠狀動脈疾病", "心肌梗塞")),
    ("五年前做過心導管", ("高血壓", "心肌梗塞", "腦中風")),
]

# 一個子項都沒提到 → 仍必問，但不做「部分涵蓋」標註
_CV_NO_HIT = ["慢性腎臟病第三期", "心臟不太好", "胃食道逆流"]

_CV_COVERED = [
    "血壓高服藥中、做過心導管放通血管、五年前心肌梗塞、去年輕微中風",
    "hypertension; coronary artery disease; prior myocardial infarction; ischemic stroke",
]


@pytest.mark.parametrize(("value", "expected_uncovered"), _CV_PARTIAL)
def test_cardiovascular_partial_hit_stays_must_ask(value: str, expected_uncovered):
    """只命中一個子項 → 整項仍必問，且標出還缺哪些（心肌梗塞／中風不能被跳過）。"""
    verdict = classify_risk_factor(_F_CV, {"medical_history": value})
    assert verdict.state == MUST_ASK, f"複合子項被單一命中關掉：{value}"
    assert verdict.uncovered == expected_uncovered


@pytest.mark.parametrize("value", _CV_NO_HIT)
def test_cardiovascular_no_hit_is_plain_must_ask(value: str):
    verdict = classify_risk_factor(_F_CV, {"medical_history": value})
    assert verdict.state == MUST_ASK
    assert verdict.uncovered == (), "完全沒命中不該渲染成「部分涵蓋」"


@pytest.mark.parametrize("value", _CV_COVERED)
def test_cardiovascular_all_subitems_still_counts_as_covered(value: str):
    """四個子項都提到 → 仍算已答（收緊後不得變成永遠問不完）。"""
    verdict = classify_risk_factor(_F_CV, {"medical_history": value})
    assert verdict.state == ANSWERED_YES, f"四子項齊備卻仍必問：{value}"


@pytest.mark.parametrize(
    "value", ["第一型糖尿病", "糖尿病(口服藥控制)", "diabetes mellitus, type 2"]
)
def test_diabetes_covered(value: str):
    assert classify_risk_factor(_F_DM, {"medical_history": value}).state == ANSWERED_YES


@pytest.mark.parametrize("value", ["甲狀腺功能低下", "高尿酸血症", "脂肪肝"])
def test_diabetes_not_covered(value: str):
    assert classify_risk_factor(_F_DM, {"medical_history": value}).state == MUST_ASK


# =============================================================================
# 4. 送進 LLM 的真實 system prompt（_CapturingClient 釘住）
# =============================================================================


class _CapturingClient:
    """假 OpenAI client：捕獲 create() 參數並回一份合法 JSON 指導。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "next_focus": "請詢問病患吸菸史",
            "missing_hpi": [],
            "hpi_completion_percentage": 60,
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(payload, ensure_ascii=False)
                    )
                )
            ]
        )


class _FakeRedis:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def setex(self, key, ttl, value):  # noqa: ANN001
        self.stored[key] = value


def _conv_prompt(complaint: str, patient_info: dict) -> str:
    return LLMConversationEngine(Settings()).build_system_prompt(
        complaint, patient_info
    )


def _supervisor_prompt(complaint: str, patient_info: dict) -> str:
    engine = SupervisorEngine(Settings())
    client = _CapturingClient()
    engine._client = client  # noqa: SLF001
    asyncio.run(
        engine.analyze_next_step(
            session_id="per-entry-test",
            conversation_history=[{"role": "patient", "content": "我尿裡有血"}],
            chief_complaint=complaint,
            patient_info=patient_info,
            redis=_FakeRedis(),
            language="zh-TW",
        )
    )
    assert client.calls, "analyze_next_step 未送出 OpenAI 請求（例外被吞掉？）"
    return client.calls[0]["messages"][0]["content"]


_CONV_MUST_ASK_HEADER = "## 本主訴的關鍵風險因子（與 HPI 十欄同級，收尾前必問）"
_CONV_BANNED_HEADER = "## 風險因子中「本次 intake 已涵蓋」的項目（禁止再問）"
_SUP_MUST_ASK_HEADER = "## 本主訴的關鍵風險因子(與 HPI 十欄同級,收尾前必問)"
_SUP_BANNED_HEADER = "## 風險因子中「本次 intake 已涵蓋」的項目(視同已問到,禁止再問)"


def _section(prompt: str, header: str) -> str:
    if header not in prompt:
        return ""
    rest = prompt.split(header, 1)[1]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_prompt_keeps_family_history_mandatory_when_split_across_relations():
    """核心回歸：「母親：乳癌、父親：攝護腺肥大」→ 兩端 prompt 都仍列必問、不進禁問。"""
    patient_info = _intake(family_history="母親：乳癌、父親：攝護腺肥大")

    conv = _conv_prompt(_HEMATURIA, patient_info)
    assert _FAMILY_LABEL in _section(conv, _CONV_MUST_ASK_HEADER)
    assert _CONV_BANNED_HEADER not in conv
    # 最關鍵的一條：不得對 LLM 斷言病患有泌尿道癌家族史
    assert "已涵蓋" not in conv.split(_CONV_MUST_ASK_HEADER)[1]

    sup = _supervisor_prompt(_HEMATURIA, patient_info)
    assert _FAMILY_LABEL in _section(sup, _SUP_MUST_ASK_HEADER)
    assert _SUP_BANNED_HEADER not in sup


def test_prompt_still_bans_family_history_when_one_relation_matches():
    """負向對照：「父親：膀胱癌」→ 兩端都移出必問、進禁問（不得被逐筆化誤傷）。"""
    patient_info = _intake(family_history="父親：膀胱癌")

    conv = _conv_prompt(_HEMATURIA, patient_info)
    assert _FAMILY_LABEL not in _section(conv, _CONV_MUST_ASK_HEADER)
    assert _FAMILY_LABEL in _section(conv, _CONV_BANNED_HEADER)

    sup = _supervisor_prompt(_HEMATURIA, patient_info)
    assert _FAMILY_LABEL not in _section(sup, _SUP_MUST_ASK_HEADER)
    assert _FAMILY_LABEL in _section(sup, _SUP_BANNED_HEADER)


def test_prompt_keeps_anticoagulant_mandatory_when_medication_stopped():
    """核心回歸：用藥「aspirin（已停用）」→ 抗凝血兩端都仍在必問清單。"""
    patient_info = _intake(medications="aspirin（已停用）")

    conv = _conv_prompt(_HEMATURIA, patient_info)
    assert _ANTICOAG_LABEL in _section(conv, _CONV_MUST_ASK_HEADER)
    assert _CONV_BANNED_HEADER not in conv
    # 次要補問段仍列出這筆表單紀錄，但 §3b 例外必須把必問救回來
    assert "- 目前用藥：aspirin（已停用）" in conv
    assert "**例外（優先序最高）**" in conv

    sup = _supervisor_prompt(_HEMATURIA, patient_info)
    assert _ANTICOAG_LABEL in _section(sup, _SUP_MUST_ASK_HEADER)


def test_prompt_still_bans_anticoagulant_when_medication_is_current():
    """負向對照：真的在吃拜瑞妥 → 抗凝血移出必問、進禁問（不得誤傷成一直問）。"""
    patient_info = _intake(medications="拜瑞妥 20mg 每晚一顆")

    conv = _conv_prompt(_HEMATURIA, patient_info)
    assert _ANTICOAG_LABEL not in _section(conv, _CONV_MUST_ASK_HEADER)
    banned = _section(conv, _CONV_BANNED_HEADER)
    assert _ANTICOAG_LABEL in banned
    assert "目前用藥：拜瑞妥 20mg 每晚一顆" in banned

    sup = _supervisor_prompt(_HEMATURIA, patient_info)
    assert _ANTICOAG_LABEL in _section(sup, _SUP_BANNED_HEADER)


def test_ed_prompt_keeps_both_factors_mandatory_with_only_hypertension():
    """核心回歸：ED 病史只有「高血壓」→ 心血管與糖尿病兩端都仍必問。"""
    patient_info = _intake(medical_history="高血壓")

    conv = _conv_prompt(_ED, patient_info)
    conv_must_ask = _section(conv, _CONV_MUST_ASK_HEADER)
    assert _CV_LABEL in conv_must_ask
    assert _DM_LABEL in conv_must_ask
    assert "心肌梗塞" in conv_must_ask and "腦中風" in conv_must_ask
    assert _CONV_BANNED_HEADER not in conv

    sup = _supervisor_prompt(_ED, patient_info)
    sup_must_ask = _section(sup, _SUP_MUST_ASK_HEADER)
    assert _CV_LABEL in sup_must_ask
    assert _DM_LABEL in sup_must_ask
    assert _SUP_BANNED_HEADER not in sup


def test_ed_prompt_bans_factors_when_history_really_covers_them():
    """負向對照：四個心血管子項＋糖尿病都寫齊 → 兩項都移出必問（不誤傷）。"""
    patient_info = _intake(
        medical_history=(
            "血壓高服藥中、做過心導管放通血管、五年前心肌梗塞、去年輕微中風、第一型糖尿病"
        )
    )
    conv = _conv_prompt(_ED, patient_info)
    must_ask = _section(conv, _CONV_MUST_ASK_HEADER)
    banned = _section(conv, _CONV_BANNED_HEADER)
    assert _CV_LABEL not in must_ask
    assert _DM_LABEL not in must_ask
    assert _CV_LABEL in banned and _DM_LABEL in banned
    assert _SMOKING_LABEL in must_ask  # intake 沒有吸菸欄位 → 永遠必問


def test_covered_factor_prompt_marks_form_provenance_not_confirmed_fact():
    """BLOCKER D 附帶：禁問段只能說「表單自填」，不得叫 LLM 當成已確認的病史。"""
    conv = _conv_prompt(_HEMATURIA, _intake(family_history="外公：腎盂惡性腫瘤"))
    banned = _section(conv, _CONV_BANNED_HEADER)
    assert "病患表單自填" in banned
    assert "不得改寫成已由問診確認的事實" in banned
    assert "直接採用此資訊寫進病史" not in conv
    assert "不得替病患補上表單沒寫的細節" in banned


# =============================================================================
# 5. BLOCKER E：次要補問的禁問清單不得吃 patients 表舊資料（雙向）
# =============================================================================


def _returning_patient() -> SimpleNamespace:
    """幾個月前建檔、`patients` 表上有長期資料的回診病患。"""
    return SimpleNamespace(
        name="陳女士",
        date_of_birth=None,
        gender=None,
        medical_history=[{"condition": "甲狀腺功能低下"}],
        current_medications=[{"name": "levothyroxine"}],
        allergies=[{"allergen": "顯影劑"}],
        family_history=[{"relation": "外公", "condition": "腎盂惡性腫瘤"}],
    )


def test_stale_record_does_not_ban_secondary_followups():
    """本次 intake 全空 → 次要補問不得因舊病歷變成硬性禁問（非 §3b 主訴沒有例外救援）。"""
    patient_info = build_patient_info(_returning_patient(), None)
    assert session_intake_fields(patient_info) == {}
    assert render_intake_known_block(patient_info) == ""

    prompt = _conv_prompt(_UNRELATED, patient_info)
    assert "一律不得再問" not in prompt, "舊病歷把用藥補問整段擋掉了"
    assert "若病患於 intake 表單已提供上述資訊" in prompt  # 回到原本的軟性句
    assert "- 目前用藥：levothyroxine" not in prompt
    assert "- 過去病史：甲狀腺功能低下" not in prompt


def test_stale_record_does_not_gate_off_section_3b_either():
    """同一份舊資料也不得關掉 §3b 必問（兩條路徑同一個標準）。"""
    patient_info = build_patient_info(_returning_patient(), None)
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, patient_info
    )
    assert _ANTICOAG_LABEL in must_ask
    assert _FAMILY_LABEL in must_ask
    assert _SMOKING_LABEL in must_ask
    assert banned == ""


def test_this_session_intake_still_bans_secondary_followups():
    """負向對照：本次 intake 真的填了 → 次要補問仍要明列禁問（不得誤傷成完全不擋）。"""
    patient_info = build_patient_info(
        _returning_patient(),
        {
            "current_medications": [{"name": "拜瑞妥 20mg"}],
            "allergies": [{"allergen": "海鮮"}],
            "no_family_history": True,
        },
    )
    prompt = _conv_prompt(_UNRELATED, patient_info)
    assert "一律不得再問" in prompt
    assert "- 目前用藥：拜瑞妥 20mg" in prompt
    assert "- 過敏史：海鮮" in prompt
    assert "- 家族史：無" in prompt
    # 本次 intake 沒填病史 → 該欄的舊病歷值不得被列進禁問清單
    assert "- 過去病史：甲狀腺功能低下" not in prompt


def test_stale_record_keeps_supervisor_gate_on():
    """supervisor 端同樣不得被舊病歷關掉 gate。"""
    prompt = _supervisor_prompt(_ED, build_patient_info(_returning_patient(), None))
    must_ask = _section(prompt, _SUP_MUST_ASK_HEADER)
    assert _CV_LABEL in must_ask
    assert _DM_LABEL in must_ask
    assert _SUP_BANNED_HEADER not in prompt


def test_unrelated_complaint_never_gets_risk_sections():
    """既有不變式：非 §3b 主訴不注入任何風險因子段落（不亂加問題）。"""
    prompt = _conv_prompt(_UNRELATED, _intake(medications="拜瑞妥 20mg"))
    assert _CONV_MUST_ASK_HEADER not in prompt
    assert _CONV_BANNED_HEADER not in prompt
