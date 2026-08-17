"""§3b 風險因子 × intake 的**三態**判定（2026-07-27 覆核 BLOCKER #5）+ age==0 渲染。

背景（真跑實測，血尿場、76 歲、intake 有 aspirin 與「父親：膀胱癌」）：
system prompt 明明含 `Current medications: aspirin` / `Family history: 父親：膀胱癌`，
AI 仍在第 4 輪問「有沒有在吃阿司匹靈、華法林這類會影響凝血的藥」、第 12 輪問
「有沒有泌尿道癌症的家族史」。根因是 intake 只是「病患資訊」段的被動陳述，而 §3b
風險因子清單是主動的「必問」指令 —— 衝突時 LLM 服從後者。第一輪把 intake 已提供項
移進「禁問清單」修掉了重問，但判定條件是**「該欄有任何非空值」**，把 §3b 從安全
不變式降級成「信任 intake 表單的完整度」：

- 用藥欄只填 `amlodipine`（沒填 OTC aspirin）→「抗凝血/抗血小板」整項被移出必問。
- ED 場 `medical_history` 只填「高血壓」→ 同時關掉「心血管疾病史」與「糖尿病」。

本檔釘住收緊後的三態與其邊界：

| intake 狀態                                   | 期望            |
|---|---|
| `no_*` 旗標為 True（patient_context 寫入「無」） | 已答＝否，不再問 |
| 有值**且語意涵蓋**該風險因子（用藥含 aspirin）    | 已答＝是，不再問 |
| 有值**但不涵蓋**（用藥只有 amlodipine）／空白     | **仍必問**      |

外加一條旁路：§3b gating **只能吃本次場次 intake**。
`patient_context.build_patient_info` 在本次 intake 空白時會把 medical_history /
medications / allergies fallback 到 `patients` 表的長期資料（可能是幾個月前建檔），
那份不得關掉 §3b。

後續（2026-07-27 覆核 BLOCKER D / E）：涵蓋判定改為**逐筆**（家族史的惡性詞與泌尿詞
必須來自同一位家人）、用藥限定語（已停用／過敏）不算在吃、心血管複合子項要逐項涵蓋、
「次要補問」禁問清單同樣只吃本次 intake。那些雙向語料在
`test_intake_coverage_per_entry.py`。
"""

import asyncio
import json
from types import SimpleNamespace

from app.core.config import Settings
from app.pipelines import llm_conversation as lc
from app.pipelines.llm_conversation import (
    ANSWERED_NO,
    ANSWERED_YES,
    INTAKE_FIELD_LABELS,
    INTAKE_SOURCE_KEY,
    MUST_ASK,
    LLMConversationEngine,
    classify_risk_factor,
    known_history_fields,
    render_critical_risk_factor_items_with_intake,
    risk_factor_intake_field,
    session_intake_fields,
)
from app.pipelines.patient_context import build_patient_info
from app.pipelines.prompts.shared import CRITICAL_RISK_FACTORS
from app.pipelines.supervisor import SupervisorEngine, build_patient_info_str

_HEMATURIA = "血尿持續三天"
_ED = "勃起功能障礙"

_ANTICOAG = "抗凝血劑或抗血小板藥物使用"
_FAMILY = "泌尿道惡性腫瘤(膀胱癌、腎癌、攝護腺癌)家族史"
_SMOKING = "吸菸史(目前或過去"
_CV = "心血管疾病史"
_DM = "糖尿病"


def _factor(needle: str) -> str:
    """從 shared.CRITICAL_RISK_FACTORS 取出含 needle 的完整 factor 原文。"""
    for group in CRITICAL_RISK_FACTORS:
        for factor in group["factors"]:
            if needle in factor:
                return factor
    raise AssertionError(f"CRITICAL_RISK_FACTORS 找不到含「{needle}」的風險因子")


def _marked(**intake_fields: str | None) -> dict:
    """組一份帶「本次 intake 來源標記」的 patient_info。

    模擬 patient_context.build_patient_info 補上 INTAKE_SOURCE_KEY 之後的形狀
    （見 needsFromOthers）。扁平欄位同時填上，因為 prompt 的「病患資訊」段讀扁平值。
    """
    flat = {key: intake_fields.get(key) for key in INTAKE_FIELD_LABELS}
    return {
        "age": 76,
        "gender": "male",
        **flat,
        INTAKE_SOURCE_KEY: dict(flat),
    }


# 真跑那一場的 intake（aspirin + 父親膀胱癌）
_INTAKE_FULL = _marked(
    medical_history="高血壓、第二型糖尿病",
    medications="aspirin",
    allergies="無",
    family_history="父親：膀胱癌",
)
# 覆核揪出的漏問場景：用藥欄填了別的藥、家族史填了非泌尿癌
_INTAKE_NONCOVERING = _marked(
    medical_history="高血壓",
    medications="amlodipine",
    allergies="無",
    family_history="母親：乳癌",
)
_INTAKE_EMPTY: dict = {
    "age": 76,
    "gender": "male",
    "medical_history": None,
    "medications": None,
    "allergies": None,
    "family_history": None,
}

_CONV_MUST_ASK_HEADER = "## 本主訴的關鍵風險因子（與 HPI 十欄同級，收尾前必問）"
_CONV_BANNED_HEADER = "## 風險因子中「本次 intake 已涵蓋」的項目（禁止再問）"
_SUP_MUST_ASK_HEADER = "## 本主訴的關鍵風險因子(與 HPI 十欄同級,收尾前必問)"
_SUP_BANNED_HEADER = "## 風險因子中「本次 intake 已涵蓋」的項目(視同已問到,禁止再問)"


def _section(prompt: str, header: str) -> str:
    """取出 prompt 中某個 `## 標題` 到下一個 `## ` 之間的內容；標題不存在回 ""。"""
    if header not in prompt:
        return ""
    rest = prompt.split(header, 1)[1]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _conv_prompt(complaint: str, patient: dict) -> str:
    return LLMConversationEngine(Settings()).build_system_prompt(complaint, patient)


# ── 1. age==0 / gender 渲染 ──────────────────────────────────


def test_age_zero_is_not_dropped_from_prompt():
    """age==0（未滿一歲）以前被 truthy 判斷整行吃掉，與 supervisor 行為不一致。"""
    prompt = _conv_prompt(_HEMATURIA, {"age": 0, "gender": "male"})
    assert "Age: 0" in prompt


def test_age_none_still_omitted():
    """age 為 None 時仍不渲染該行（只修 0，不改「沒有年齡」的行為）。"""
    prompt = _conv_prompt(_HEMATURIA, {"age": None, "gender": "male"})
    assert "Age:" not in prompt


def test_gender_rendered_as_internal_code():
    """gender 由 patient_context 上游改回 `.value`，prompt 應是 `Gender: male`。"""
    prompt = _conv_prompt(_HEMATURIA, {"age": 76, "gender": "male"})
    assert "Gender: male" in prompt
    assert "Gender.MALE" not in prompt


def test_supervisor_patient_info_str_handles_zero_and_none():
    """supervisor 側：age==0 顯示 0；age/gender 為 None 顯示「未知」而非「None」。"""
    assert "年齡：0" in build_patient_info_str({"age": 0, "gender": "male"})
    s = build_patient_info_str({"age": None, "gender": None})
    assert "年齡：未知" in s
    assert "性別：未知" in s
    assert "None" not in s


# ── 2. 風險因子 ↔ intake 欄位對照 ────────────────────────────


def test_risk_factor_intake_field_mapping_covers_catalogue():
    """對照表要覆蓋 CRITICAL_RISK_FACTORS 現有每一項（吸菸 / 血脂刻意無對應欄位）。"""
    resolved = {
        factor: risk_factor_intake_field(factor)
        for group in CRITICAL_RISK_FACTORS
        for factor in group["factors"]
    }
    for factor, field in resolved.items():
        if "吸菸" in factor:
            assert field is None, f"intake 沒有吸菸欄位，不得視為已提供：{factor}"
        elif "抗凝血" in factor:
            assert field == "medications"
        elif "家族史" in factor:
            assert field == "family_history"
        elif "心血管疾病史" in factor or "糖尿病" in factor:
            assert field == "medical_history"
        else:  # 新增 factor 沒對到 → 必須 fail-safe 成「永遠必問」
            assert field is None, f"未預期的對照：{factor} → {field}"


def test_unmapped_factor_is_always_must_ask():
    """對照不到欄位的風險因子（上游改寫文字時）一律 fail-safe 成必問。"""
    verdict = classify_risk_factor("尚未定義的新風險因子", {"medications": "aspirin"})
    assert verdict == (MUST_ASK, None, None, ())


# ── 3. 三態判定（本次修復的核心） ─────────────────────────────


def test_explicit_no_flag_counts_as_answered_no():
    """狀態一：no_* 旗標 → patient_context 寫「無」→ 已答＝否，不再問。"""
    verdict = classify_risk_factor(_factor("抗凝血"), {"medications": "無"})
    assert verdict.state == ANSWERED_NO
    assert (verdict.field, verdict.value) == ("medications", "無")


def test_medication_list_containing_anticoagulant_counts_as_answered_yes():
    """狀態二：用藥列表含 aspirin → 已答＝是，不再問（收緊後不得變回一直問）。"""
    for listed in ("aspirin", "阿斯匹靈 100mg", "warfarin 5mg、metformin", "Plavix"):
        verdict = classify_risk_factor(_factor("抗凝血"), {"medications": listed})
        assert verdict.state == ANSWERED_YES, f"{listed} 應被判為涵蓋抗凝血/抗血小板"
        assert verdict.field == "medications"


def test_medication_list_without_anticoagulant_stays_must_ask():
    """狀態三（**本次核心回歸**）：用藥只填 amlodipine → 抗凝血仍必問。

    「用藥欄填了別的藥」不等於「沒有在吃抗凝血劑」——OTC aspirin 最常漏填。
    """
    for listed in ("amlodipine", "amlodipine 5mg、metformin", "降血壓藥"):
        verdict = classify_risk_factor(_factor("抗凝血"), {"medications": listed})
        assert verdict.state == MUST_ASK, f"{listed} 不涵蓋抗凝血劑，必須維持必問"
        assert (verdict.field, verdict.value) == ("medications", listed)


def test_blank_field_stays_must_ask():
    """狀態三：欄位空白 → 仍必問（第一輪已有的行為，不得弄壞）。"""
    assert classify_risk_factor(_factor("抗凝血"), {})[0] == MUST_ASK


def test_family_history_requires_both_malignancy_and_urologic_terms():
    """家族史那項問的是**泌尿道惡性腫瘤**，只有兩個條件都命中才算涵蓋。"""
    covered = ("父親：膀胱癌", "祖父攝護腺癌", "brother: kidney cancer", "腎細胞癌")
    for value in covered:
        assert (
            classify_risk_factor(_factor("家族史"), {"family_history": value})[0]
            == ANSWERED_YES
        ), value

    # 有癌但非泌尿道 / 有泌尿器官但非惡性 / 完全無關 → 都要留在必問
    not_covered = ("母親：乳癌", "父親：肺癌", "父親：攝護腺肥大", "母親：高血壓")
    for value in not_covered:
        assert (
            classify_risk_factor(_factor("家族史"), {"family_history": value})[0]
            == MUST_ASK
        ), value


def test_ed_medical_history_covers_only_what_it_mentions():
    """覆核實測的 ED 場：病史只填「高血壓」不得同時關掉糖尿病。"""
    only_htn = {"medical_history": "高血壓"}
    assert classify_risk_factor(_factor("糖尿病"), only_htn).state == MUST_ASK

    both = {"medical_history": "高血壓、第二型糖尿病"}
    assert classify_risk_factor(_factor("糖尿病"), both).state == ANSWERED_YES

    # 病史有值但兩者都不涵蓋 → 兩項都仍必問
    neither = {"medical_history": "氣喘"}
    assert classify_risk_factor(_factor("心血管疾病史"), neither).state == MUST_ASK
    assert classify_risk_factor(_factor("糖尿病"), neither).state == MUST_ASK


def test_explicit_no_on_medical_history_answers_both_ed_factors():
    """no_past_medical_history → 該欄「無」＝心血管與糖尿病都已答＝否。"""
    none_flag = {"medical_history": "無"}
    assert classify_risk_factor(_factor("心血管疾病史"), none_flag).state == ANSWERED_NO
    assert classify_risk_factor(_factor("糖尿病"), none_flag).state == ANSWERED_NO


# ── 4. gating 來源：只吃本次場次 intake ───────────────────────


def test_patient_context_family_history_has_no_patient_table_fallback():
    """釘住 `session_intake_fields` 無標記時信任 family_history 的前提。

    build_patient_info 對 medical_history / medications / allergies 有
    `or format_jsonb_list(patient.…)` 的舊資料 fallback，family_history 沒有。
    上游一旦補上 family_history fallback，本測試會紅 → 必須同步改
    `_INTAKE_ONLY_FIELDS_WITHOUT_MARKER`，否則舊家族史會偷偷關掉 §3b。
    """
    stale = SimpleNamespace(
        name="王先生",
        date_of_birth=None,
        gender=None,
        medical_history=[{"condition": "高血壓"}],
        current_medications=[{"name": "aspirin"}],
        allergies=[{"allergen": "penicillin"}],
        family_history=[{"relation": "父", "condition": "膀胱癌"}],
    )
    built = build_patient_info(stale, None)
    assert built["medical_history"] == "高血壓"
    assert built["medications"] == "aspirin"
    assert built["allergies"] == "penicillin"
    assert built["family_history"] is None, (
        "family_history 出現 patients 表 fallback → 舊資料會關掉 §3b 泌尿癌家族史必問"
    )


def test_stale_patient_record_does_not_gate_off_must_ask():
    """intake 全空、patients 表有舊病史/舊用藥 → §3b 三項仍全部必問。

    舊資料可能是幾個月前建檔的，不能拿來當「本次已問到」。
    """
    stale = SimpleNamespace(
        name="王先生",
        date_of_birth=None,
        gender=None,
        medical_history=[{"condition": "高血壓"}],
        current_medications=[{"name": "aspirin"}],
        allergies=[{"allergen": "penicillin"}],
        family_history=[{"relation": "父", "condition": "膀胱癌"}],
    )
    patient_info = build_patient_info(stale, None)

    assert session_intake_fields(patient_info) == {}, "舊病歷值不得被當成本次 intake"

    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, patient_info
    )
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert _SMOKING in must_ask
    assert banned == ""

    ed_must_ask, ed_banned = render_critical_risk_factor_items_with_intake(
        _ED, patient_info
    )
    assert _CV in ed_must_ask
    assert _DM in ed_must_ask
    assert ed_banned == ""


def test_session_intake_no_flags_are_trusted_without_marker():
    """本次 intake 的 no_* 旗標（→「無」）即使沒有來源標記也算數。

    build_patient_info 只有在本次 intake 的 no_* 為 True 時才寫入「無」。
    """
    patient = SimpleNamespace(
        name="王先生",
        date_of_birth=None,
        gender=None,
        medical_history=[{"condition": "高血壓"}],
        current_medications=[{"name": "aspirin"}],
        allergies=None,
        family_history=None,
    )
    patient_info = build_patient_info(
        patient,
        {"no_current_medications": True, "no_family_history": True},
    )
    assert patient_info["medications"] == "無"
    assert patient_info["family_history"] == "無"

    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, patient_info
    )
    assert _ANTICOAG not in must_ask and _ANTICOAG in banned
    assert _FAMILY not in must_ask and _FAMILY in banned
    assert "答案為「否」" in banned
    # 病史欄沒有 no_* 旗標 → 值來自 patients 表 → 不得被信任
    assert session_intake_fields(patient_info).keys() == {"medications", "family_history"}


def test_intake_source_marker_is_authoritative():
    """帶 INTAKE_SOURCE_KEY 時完全以它為準（扁平欄位的舊值不參與 gating）。"""
    patient_info = {
        "medications": "aspirin",  # 扁平值可能來自 patients 表
        "family_history": "父親：膀胱癌",
        INTAKE_SOURCE_KEY: {"medications": None, "family_history": "父親：膀胱癌"},
    }
    assert session_intake_fields(patient_info) == {"family_history": "父親：膀胱癌"}

    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, patient_info
    )
    assert _ANTICOAG in must_ask, "本次 intake 沒填用藥 → 抗凝血必須維持必問"
    assert _FAMILY in banned


def test_known_history_fields_still_sees_all_sources():
    """「次要補問」段用的清單刻意不分來源（那段不是安全 gate）。"""
    assert known_history_fields({"medications": "aspirin", "allergies": "  "}) == {
        "medications": "aspirin"
    }


# ── 5. 必問 / 禁問清單切分 ───────────────────────────────────


def test_intake_covered_factors_leave_must_ask_list():
    """真跑那一場：aspirin + 父親膀胱癌 → 抗凝血、家族史移出必問、進禁問。"""
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, _INTAKE_FULL
    )
    assert _ANTICOAG not in must_ask
    assert _FAMILY not in must_ask
    assert _ANTICOAG in banned and "目前用藥：aspirin" in banned
    assert _FAMILY in banned and "家族史：父親：膀胱癌" in banned
    assert "不需重複詢問" in banned
    # BLOCKER D 附帶修法：不得叫 LLM 把表單自填值當已確認的臨床事實寫進病史
    assert "病患表單自填" in banned
    assert "不得改寫成已由問診確認的事實" in banned
    assert "直接採用" not in banned


def test_noncovering_intake_keeps_everything_mandatory():
    """**本次核心回歸**：填了 amlodipine / 乳癌家族史 → 三項風險因子仍全部必問。"""
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, _INTAKE_NONCOVERING
    )
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert _SMOKING in must_ask
    assert banned == ""


def test_blank_intake_fields_stay_mandatory():
    """intake 該欄空白 → 仍必問（不因為『有這個欄位』就當已問到）。"""
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, _INTAKE_EMPTY
    )
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert banned == ""


def test_smoking_history_never_covered_by_intake():
    """intake 表單沒有吸菸欄位 → 不論 intake 多完整，吸菸史永遠留在必問清單。"""
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _HEMATURIA, _INTAKE_FULL
    )
    assert _SMOKING in must_ask
    assert _SMOKING not in banned


def test_ed_partial_history_keeps_both_factors_mandatory():
    """ED：病史只填「高血壓」→ 心血管與糖尿病**都仍必問**（BLOCKER D 複合子項）。

    「心血管疾病史(高血壓、冠狀動脈疾病、心肌梗塞、腦中風)」是四個子項，命中高血壓
    不代表心肌梗塞／腦中風被問到過。必問行要標出「還缺哪幾項」，避免 AI 重問高血壓。
    """
    must_ask, banned = render_critical_risk_factor_items_with_intake(
        _ED, _marked(medical_history="高血壓")
    )
    assert _CV in must_ask
    assert _DM in must_ask
    assert "吸菸史與血脂異常" in must_ask
    assert "心肌梗塞" in must_ask and "腦中風" in must_ask
    assert "只涵蓋其中一部分" in must_ask
    assert banned == ""


def test_unrelated_complaint_gets_no_sections_even_with_intake():
    """無關主訴不注入任何 §3b 段落（既有不變式不得被 intake 邏輯破壞）。"""
    assert render_critical_risk_factor_items_with_intake("頻尿", _INTAKE_FULL) == ("", "")


# ── 6. conversation system prompt 整合 ───────────────────────


def test_conversation_prompt_moves_covered_factors_to_ban_list():
    """必問段不得再出現抗凝血 / 家族史；禁問段要帶 intake 的值。"""
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_FULL)
    must_ask = _section(prompt, _CONV_MUST_ASK_HEADER)
    banned = _section(prompt, _CONV_BANNED_HEADER)

    assert must_ask, "必問段應仍存在（吸菸史沒被 intake 涵蓋）"
    assert _ANTICOAG not in must_ask
    assert _FAMILY not in must_ask
    assert _SMOKING in must_ask

    assert "一律不得**再問" in banned
    assert "目前用藥：aspirin" in banned
    assert "家族史：父親：膀胱癌" in banned


def test_conversation_prompt_keeps_noncovering_factors_mandatory():
    """**本次核心回歸**：amlodipine 場的 prompt 必問段仍含抗凝血、且無禁問段。"""
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_NONCOVERING)
    must_ask = _section(prompt, _CONV_MUST_ASK_HEADER)
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert _CONV_BANNED_HEADER not in prompt
    # 且不得對 LLM 斷言「病患已提供抗凝血用藥資訊」
    assert "抗凝血劑或抗血小板藥物使用 → " not in prompt


def test_conversation_prompt_secondary_ban_yields_to_mandatory_risk_factors():
    """次要補問的「目前用藥已有紀錄，禁問」不得擋掉 §3b 的抗凝血必問。"""
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_NONCOVERING)
    assert "- 目前用藥：amlodipine" in prompt  # 次要補問段仍列為已知
    assert "**例外（優先序最高）**" in prompt
    assert "仍必須" in prompt


def test_conversation_prompt_without_intake_keeps_all_three_mandatory():
    """intake 全空 → 三項風險因子全部必問、無禁問段（§3b 原行為不變）。"""
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_EMPTY)
    must_ask = _section(prompt, _CONV_MUST_ASK_HEADER)
    assert _SMOKING in must_ask
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert _CONV_BANNED_HEADER not in prompt


def test_conversation_prompt_keeps_dont_know_and_single_question_invariants():
    """intake 過濾不得洗掉 don't-know 不重問 / 每輪一問的措辭。"""
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_FULL)
    assert "不知道" in prompt
    assert "每輪仍只問一題" in prompt
    assert "不得換句話" in prompt


def test_conversation_prompt_drops_mandatory_header_when_all_covered(monkeypatch):
    """所有風險因子都被 intake 涵蓋時，必問段整段不渲染（只留禁問段）。

    目前 ontology 每組都含 intake 沒有的吸菸史，故以 monkeypatch 造出「全覆蓋」情境，
    確保這條分支真的走得到（未來新增純 intake 可覆蓋的風險因子群時就會用到）。
    """
    monkeypatch.setattr(
        lc,
        "get_critical_risk_factors_for_complaint",
        lambda cc: [{"id": "fake", "factors": ["目前是否使用抗凝血劑"]}],
    )
    prompt = _conv_prompt(_HEMATURIA, _INTAKE_FULL)
    assert _CONV_MUST_ASK_HEADER not in prompt
    assert _CONV_BANNED_HEADER in prompt
    assert "目前用藥：aspirin" in _section(prompt, _CONV_BANNED_HEADER)


def test_conversation_prompt_no_risk_sections_for_unrelated_complaint():
    prompt = _conv_prompt("頻尿", _INTAKE_FULL)
    assert _CONV_MUST_ASK_HEADER not in prompt
    assert _CONV_BANNED_HEADER not in prompt
    assert "次要補問" in prompt  # 其他段落照舊


def test_secondary_section_lists_known_answers_as_banned():
    """『次要補問』段列的正是四類病史，已有紀錄者要被明列成禁問（含值）。"""
    prompt = _conv_prompt("頻尿", _INTAKE_FULL)
    assert "一律不得再問" in prompt
    assert "- 目前用藥：aspirin" in prompt
    assert "- 家族史：父親：膀胱癌" in prompt
    assert "- 過敏史：無" in prompt


def test_secondary_section_falls_back_when_no_intake():
    """intake 全空時維持原本那句（不憑空冒出空的禁問清單）。"""
    prompt = _conv_prompt("頻尿", _INTAKE_EMPTY)
    assert "若病患於 intake 表單已提供上述資訊" in prompt
    assert "一律不得再問" not in prompt


# ── 7. supervisor gate 整合（實際捕獲送出的 system prompt） ───


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
                    message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
                )
            ]
        )


class _FakeRedis:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def setex(self, key, ttl, value):  # noqa: ANN001
        self.stored[key] = value


def _supervisor_prompt(complaint: str, patient_info: dict) -> str:
    engine = SupervisorEngine(Settings())
    client = _CapturingClient()
    engine._client = client  # noqa: SLF001
    asyncio.run(
        engine.analyze_next_step(
            session_id="test-session",
            conversation_history=[{"role": "patient", "content": "我尿血三天了"}],
            chief_complaint=complaint,
            patient_info=patient_info,
            redis=_FakeRedis(),
            language="zh-TW",
        )
    )
    assert client.calls, "analyze_next_step 未送出 OpenAI 請求（例外被吞掉？）"
    return client.calls[0]["messages"][0]["content"]


def test_supervisor_gate_excludes_intake_covered_factors():
    """next_focus gate 的必問清單不得再含本次 intake 已涵蓋項，改列進禁問段。"""
    prompt = _supervisor_prompt(_HEMATURIA, _INTAKE_FULL)
    must_ask = _section(prompt, _SUP_MUST_ASK_HEADER)
    banned = _section(prompt, _SUP_BANNED_HEADER)

    assert _ANTICOAG not in must_ask
    assert _FAMILY not in must_ask
    assert _SMOKING in must_ask  # 吸菸史仍 gate 住完整度

    assert "一律不得**指向它們" in banned
    assert "目前用藥：aspirin" in banned
    assert "家族史：父親：膀胱癌" in banned
    # 完整度不得因 intake 已答的項目被壓低
    assert "壓低 hpi_completion_percentage" in banned


def test_supervisor_gate_keeps_noncovering_factors_mandatory():
    """**本次核心回歸**：amlodipine 場的 supervisor gate 仍 gate 住抗凝血。"""
    prompt = _supervisor_prompt(_HEMATURIA, _INTAKE_NONCOVERING)
    must_ask = _section(prompt, _SUP_MUST_ASK_HEADER)
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert "絕對不可評為 80 以上" in must_ask
    # 背景資訊有「目前用藥（intake 已提供）：amlodipine」，必須明示必問優先
    assert "**優先序最高**" in must_ask
    assert _SUP_BANNED_HEADER not in prompt


def test_supervisor_gate_ignores_stale_patient_record():
    """patients 表舊資料不得關掉 supervisor 端的 §3b gate。"""
    stale = SimpleNamespace(
        name="王先生",
        date_of_birth=None,
        gender=None,
        medical_history=[{"condition": "高血壓"}],
        current_medications=[{"name": "aspirin"}],
        allergies=None,
        family_history=None,
    )
    prompt = _supervisor_prompt(_ED, build_patient_info(stale, None))
    must_ask = _section(prompt, _SUP_MUST_ASK_HEADER)
    assert _CV in must_ask
    assert _DM in must_ask
    assert _SUP_BANNED_HEADER not in prompt


def test_supervisor_gate_intact_without_intake():
    """intake 全空 → 三項全在必問 gate 裡、無禁問段（§3b gate 原行為不變）。"""
    prompt = _supervisor_prompt(_HEMATURIA, _INTAKE_EMPTY)
    must_ask = _section(prompt, _SUP_MUST_ASK_HEADER)
    assert _SMOKING in must_ask
    assert _ANTICOAG in must_ask
    assert _FAMILY in must_ask
    assert "絕對不可評為 80 以上" in must_ask
    assert _SUP_BANNED_HEADER not in prompt


def test_supervisor_background_marks_intake_and_gender():
    """背景字串仍帶 intake 標記，且性別是 male（不是 Gender.MALE）。"""
    prompt = _supervisor_prompt(_HEMATURIA, _INTAKE_FULL)
    assert "性別：male" in prompt
    assert "目前用藥（intake 已提供）：aspirin" in prompt
    assert "家族史（intake 已提供）：父親：膀胱癌" in prompt


def test_supervisor_no_risk_sections_for_unrelated_complaint():
    prompt = _supervisor_prompt("頻尿", _INTAKE_FULL)
    assert _SUP_MUST_ASK_HEADER not in prompt
    assert _SUP_BANNED_HEADER not in prompt
