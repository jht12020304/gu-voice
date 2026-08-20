"""IN-2：§3b intake 涵蓋判定詞庫的**五語**雙向語料。

## 這在守什麼

`llm_conversation` 的三態判定（不變式 #23）靠 `_RISK_FACTOR_RULES` 的詞庫決定
「intake 的值是否**真的涵蓋**這個風險因子」。舊詞庫只有 zh + en，但場次語言是五語、
intake 是**病患用場次語言自填**的自由文字，所以：

    ko「방광암」／ vi「ung thư bàng quang」／ ja 假名「膀胱がん」「ワーファリン」

一律判不出涵蓋 → 該項退回「仍必問」→ §3b 必問清單的優先序高於次要補問的禁問清單
（`build_system_prompt` 的「例外（優先序最高）」條款）→ **病患剛在 intake 填過的
家族史／抗凝血用藥被口頭重問一次**（正是 2026-07-27 那份實測逐字稿的第 4 / 12 輪）。

## 測試設計（照 skill「改偵測邏輯時的測試設計」四點）

1. **雙向對稱**：每個詞域、每個語言都同時有 `ANSWERED_YES`（值涵蓋 → 禁問）與
   `MUST_ASK`（值不涵蓋 → 仍必問）語料。只加單向就是在替下一次擺盪鋪路。
2. **措辭避開 e2e persona 台詞**：`intake_wiring_zh` 用「父親：膀胱癌」＋ aspirin，
   本檔一律換人稱、換病名、換藥名（叔父／伯父、腎盂癌／尿路上皮癌、warfarin 系）。
3. **oracle 不是實作自己**：斷言直接寫死三態常數與欄位，不呼叫 `evaluate_coverage`
   當判準。
4. 注入式回歸：把任一語言的詞群刪掉，對應語言的 `ANSWERED_YES` 案例會紅。

## 安全方向

判不準 → 歸「仍必問」是**安全**方向（多問一句）；錯誤的涵蓋判定（誤跳過 + 依 prompt
寫進病史）才是危險方向。所以 `MUST_ASK` 那一半的語料比 `ANSWERED_YES` 更重要——
它釘住「新增的多語字面沒有把不相干的值誤判成涵蓋」。
"""

from __future__ import annotations

import pytest

from app.pipelines.llm_conversation import (
    ANSWERED_YES,
    INTAKE_SOURCE_KEY,
    MUST_ASK,
    classify_risk_factor,
    split_risk_factors_by_intake,
)
from app.pipelines.prompts.shared import get_critical_risk_factors_for_complaint

# ── 從單一來源取真正的 factor 字串（不手抄，避免與 shared.py 漂移）──
_HEMATURIA_FACTORS = get_critical_risk_factors_for_complaint("血尿")[0]["factors"]
_ED_FACTORS = get_critical_risk_factors_for_complaint("勃起功能障礙")[0]["factors"]

ANTICOAGULANT = next(f for f in _HEMATURIA_FACTORS if "抗凝血" in f)
FAMILY_UROMALIGNANCY = next(f for f in _HEMATURIA_FACTORS if "家族史" in f)
CARDIOVASCULAR = next(f for f in _ED_FACTORS if "心血管疾病史" in f)
DIABETES = next(f for f in _ED_FACTORS if "糖尿病" in f)


def _verdict(factor: str, field: str, value: str):
    return classify_risk_factor(factor, {field: value})


# =============================================================================
# 詞域 1：抗凝血／抗血小板藥物（medications 欄，單一詞群 → 命中即涵蓋）
# =============================================================================
# ⚠️ 這個詞群是**唯一**沒有第二道詞群把關的規則（家族史要求泌尿部位共現、心血管要求
# 四子項齊備），所以它的誤判會直接變成「誤跳過抗凝血劑」。新增字面務必最保守。
ANTICOAGULANT_COVERED = [
    pytest.param("warfarin 3mg，每日一次", id="zh-warfarin"),
    pytest.param("Clopidogrel 75mg daily", id="en-clopidogrel"),
    pytest.param("ワーファリン 2mg 朝食後", id="ja-warfarin-kana"),
    pytest.param("バイアスピリン 100mg", id="ja-aspirin-kana"),
    pytest.param("와파린 3mg 하루 한 번", id="ko-warfarin"),
    pytest.param("항응고제 복용 중", id="ko-anticoagulant-generic"),
    pytest.param("thuốc chống đông máu", id="vi-anticoagulant"),
    pytest.param("thuốc loãng máu mỗi ngày", id="vi-blood-thinner"),
]

ANTICOAGULANT_NOT_COVERED = [
    # amlodipine 是 skill「Common Rationalizations」表列的經典反例：用藥欄有東西
    # ≠ 有抗凝血劑。五語都要確認新字面沒有把它誤判成涵蓋。
    pytest.param("amlodipine 5mg", id="zh-amlodipine"),
    pytest.param("Metformin 500mg twice a day", id="en-metformin"),
    pytest.param("アムロジピン 5mg 毎朝", id="ja-amlodipine"),
    pytest.param("암로디핀 5mg 복용", id="ko-amlodipine"),
    pytest.param("amlodipin 5mg mỗi sáng", id="vi-amlodipine"),
    # 停用／過敏限定語：含藥名但整筆不採計 → 退回仍必問（安全方向）
    pytest.param("ワルファリンは中止しました", id="ja-warfarin-discontinued"),
    pytest.param("와파린 복용 중단", id="ko-warfarin-stopped"),
    pytest.param("đã ngưng thuốc chống đông", id="vi-anticoagulant-stopped"),
]


@pytest.mark.parametrize("value", ANTICOAGULANT_COVERED)
def test_anticoagulant_covered_is_answered_yes(value: str) -> None:
    verdict = _verdict(ANTICOAGULANT, "medications", value)
    assert verdict.state == ANSWERED_YES, (
        f"用藥欄「{value}」明載抗凝血/抗血小板藥物，卻沒被判成已涵蓋 → "
        "該項會留在 §3b 必問清單，病患被重問一次"
    )
    assert verdict.field == "medications"


@pytest.mark.parametrize("value", ANTICOAGULANT_NOT_COVERED)
def test_anticoagulant_not_covered_stays_must_ask(value: str) -> None:
    verdict = _verdict(ANTICOAGULANT, "medications", value)
    assert verdict.state == MUST_ASK, (
        f"用藥欄「{value}」不涵蓋抗凝血/抗血小板，卻被判成已涵蓋 → "
        "AI 全程不會口頭確認一次抗凝血劑（危險方向）"
    )


# =============================================================================
# 詞域 2：泌尿道惡性腫瘤家族史（family_history 欄，惡性 × 泌尿部位、**同一筆**）
# =============================================================================
FAMILY_COVERED = [
    pytest.param("叔父：腎盂癌", id="zh-renal-pelvis-cancer"),
    pytest.param("uncle: urothelial carcinoma", id="en-urothelial"),
    pytest.param("伯父：膀胱がん", id="ja-bladder-kana"),
    pytest.param("兄：前立腺の悪性腫瘍", id="ja-prostate-kanji"),
    pytest.param("삼촌: 방광암", id="ko-bladder-cancer"),
    pytest.param("형: 신장 종양(악성)", id="ko-kidney-malignant"),
    pytest.param("chú: ung thư bàng quang", id="vi-bladder-cancer"),
    pytest.param("anh trai: khối u ác tính ở thận", id="vi-kidney-malignant"),
]

FAMILY_NOT_COVERED = [
    # 惡性但非泌尿部位
    pytest.param("姑姑：乳癌", id="zh-breast"),
    pytest.param("aunt: colon cancer", id="en-colon"),
    pytest.param("母：胃がん", id="ja-gastric"),
    pytest.param("어머니: 유방암", id="ko-breast"),
    pytest.param("mẹ: ung thư vú", id="vi-breast"),
    # 泌尿部位但良性
    pytest.param("伯父：前立腺肥大", id="ja-bph"),
    pytest.param("삼촌: 전립선 비대증", id="ko-bph"),
    pytest.param("chú: sỏi thận", id="vi-kidney-stone"),
    # BLOCKER D：條件跨「筆」湊出來（惡性在 A、泌尿部位在 B）→ 不得判成涵蓋，
    # 否則 prompt 會叫 LLM 把不存在的泌尿癌家族史寫進病史（捏造病歷）。
    pytest.param("어머니: 유방암、아버지: 전립선 비대증", id="ko-cross-entry"),
    pytest.param("母：胃がん、父：前立腺肥大", id="ja-cross-entry"),
    pytest.param("mẹ: ung thư vú, bố: phì đại tuyến tiền liệt", id="vi-cross-entry"),
    # 轉移＝非泌尿道原發 → 整筆不採計（五語限定語）
    pytest.param("父：胃がんの腎転移", id="ja-metastasis"),
    pytest.param("아버지: 위암 신장 전이", id="ko-metastasis"),
    pytest.param("bố: ung thư dạ dày di căn thận", id="vi-metastasis"),
]


@pytest.mark.parametrize("value", FAMILY_COVERED)
def test_family_urologic_malignancy_covered(value: str) -> None:
    verdict = _verdict(FAMILY_UROMALIGNANCY, "family_history", value)
    assert verdict.state == ANSWERED_YES, (
        f"家族史「{value}」同一筆內同時有惡性與泌尿部位，卻沒被判成已涵蓋"
    )


@pytest.mark.parametrize("value", FAMILY_NOT_COVERED)
def test_family_urologic_malignancy_not_covered(value: str) -> None:
    verdict = _verdict(FAMILY_UROMALIGNANCY, "family_history", value)
    assert verdict.state == MUST_ASK, (
        f"家族史「{value}」不構成泌尿道惡性腫瘤家族史，卻被判成已涵蓋 → "
        "SOAP 會憑空生出病患沒有的泌尿癌家族史"
    )


# =============================================================================
# 詞域 3：心血管疾病史（medical_history 欄，四子項**都**要被提到）
# =============================================================================
CARDIOVASCULAR_COVERED = [
    pytest.param("高血壓、冠狀動脈疾病、心肌梗塞、中風", id="zh-all-four"),
    pytest.param(
        "hypertension, coronary artery disease, myocardial infarction, stroke",
        id="en-all-four",
    ),
    pytest.param("高血圧、狭心症、心筋梗塞、脳梗塞", id="ja-all-four"),
    pytest.param("고혈압, 협심증, 심근경색, 뇌졸중", id="ko-all-four"),
    pytest.param(
        "tăng huyết áp, đau thắt ngực, nhồi máu cơ tim, đột quỵ", id="vi-all-four"
    ),
]

CARDIOVASCULAR_PARTIAL = [
    pytest.param("高血圧のみ", id="ja-hypertension-only"),
    pytest.param("고혈압", id="ko-hypertension-only"),
    pytest.param("cao huyết áp", id="vi-hypertension-only"),
]


@pytest.mark.parametrize("value", CARDIOVASCULAR_COVERED)
def test_cardiovascular_all_four_subitems_covered(value: str) -> None:
    verdict = _verdict(CARDIOVASCULAR, "medical_history", value)
    assert verdict.state == ANSWERED_YES, f"病史「{value}」四子項齊備卻沒判成涵蓋"
    assert verdict.uncovered == ()


@pytest.mark.parametrize("value", CARDIOVASCULAR_PARTIAL)
def test_cardiovascular_partial_stays_must_ask_with_labels(value: str) -> None:
    """只提到高血壓 ≠ 心血管疾病史已知：心肌梗塞/腦中風仍完全未知。"""
    verdict = _verdict(CARDIOVASCULAR, "medical_history", value)
    assert verdict.state == MUST_ASK
    assert "高血壓" not in verdict.uncovered, "已知的子項不該再被列進『仍須問』"
    assert {"冠狀動脈疾病", "心肌梗塞", "腦中風"} <= set(verdict.uncovered)


# =============================================================================
# 詞域 4：糖尿病（medical_history 欄）
# =============================================================================
DIABETES_COVERED = [
    pytest.param("第二型糖尿病", id="zh-t2dm"),
    pytest.param("Type 2 diabetes mellitus", id="en-t2dm"),
    pytest.param("とうにょうびょう（２型）", id="ja-kana"),
    pytest.param("당뇨병", id="ko"),
    pytest.param("đái tháo đường tuýp 2", id="vi-formal"),
    pytest.param("bệnh tiểu đường", id="vi-colloquial"),
]

DIABETES_NOT_COVERED = [
    pytest.param("高脂血症", id="zh-hyperlipidemia"),
    pytest.param("脂質異常症", id="ja-dyslipidemia"),
    pytest.param("고지혈증", id="ko-hyperlipidemia"),
    pytest.param("mỡ máu cao", id="vi-hyperlipidemia"),
]


@pytest.mark.parametrize("value", DIABETES_COVERED)
def test_diabetes_covered(value: str) -> None:
    assert _verdict(DIABETES, "medical_history", value).state == ANSWERED_YES


@pytest.mark.parametrize("value", DIABETES_NOT_COVERED)
def test_diabetes_not_covered(value: str) -> None:
    assert _verdict(DIABETES, "medical_history", value).state == MUST_ASK


# =============================================================================
# 端到端：五語 intake 真的把該項移出必問清單、改進禁問清單
# =============================================================================
@pytest.mark.parametrize(
    ("medications", "family_history"),
    [
        pytest.param("ワーファリン 2mg", "伯父：膀胱がん", id="ja"),
        pytest.param("와파린 3mg", "삼촌: 방광암", id="ko"),
        pytest.param("thuốc chống đông", "chú: ung thư bàng quang", id="vi"),
    ],
)
def test_five_language_intake_moves_factors_to_forbidden_list(
    medications: str, family_history: str
) -> None:
    """ja/ko/vi 的 intake 值要與 zh 一樣把兩項從必問移到禁問。

    這是 IN-2 的實際後果測試：留在必問清單＝§3b 例外條款壓過禁問清單＝重問。
    """
    patient_info = {
        "medications": medications,
        "family_history": family_history,
        INTAKE_SOURCE_KEY: {
            "medications": medications,
            "family_history": family_history,
            "medical_history": None,
            "allergies": None,
        },
    }
    must_ask, covered = split_risk_factors_by_intake("血尿", patient_info)
    must_ask_text = "\n".join(must_ask)
    covered_text = "\n".join(covered)

    assert "抗凝血" not in must_ask_text, "抗凝血劑仍在必問清單 → 會被重問"
    assert "家族史" not in must_ask_text, "泌尿癌家族史仍在必問清單 → 會被重問"
    assert "抗凝血" in covered_text and "家族史" in covered_text
    # 吸菸史沒有對應 intake 欄位 → 永遠必問（不得被這批詞庫改動波及）
    assert "吸菸史" in must_ask_text
