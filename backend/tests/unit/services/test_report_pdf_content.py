"""
SO-5：PDF 內容覆蓋守護。

稽核指出的斷點：`_build_report_html` 只印 chief_complaint / summary /
clinical_impression / ICD-10，Objective 與 Plan 直接 `json.dumps` 整包 dump。
後果：

- §R 好不容易修好的家族史（intake 明載「父親：膀胱癌」）**在 PDF 上看不到**——
  醫師拿到的紙本缺了 HPI 全欄與四類病史。
- differential_diagnoses（鑑別診斷）整段消失。
- Objective / Plan 變成 raw JSON，醫師要在 `{"urgency": "er_now"}` 裡讀急迫性。

本檔用**實值斷言**（「父親：膀胱癌」這種真的會出現在紙上的字）守住覆蓋，
而不是只斷言標籤存在——標籤在、值不在正是原本的失效模式。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.report_service import _build_report_html

# 一份「完整」的 SOAP，鍵名逐一對照 soap_generator 的 prompt schema
FULL_SUBJECTIVE = {
    "chief_complaint": "無痛性血尿三天",
    "hpi": {
        "onset": "三天前早晨",
        "location": "下腹部",
        "duration": "持續三天",
        "characteristics": "無痛、鮮紅色",
        "severity": "中度",
        "aggravating_factors": "久坐後加劇",
        "relieving_factors": "多喝水稍緩解",
        "associated_symptoms": "頻尿、夜尿兩次",
        "timing": "整日皆有",
        "context": "近期無外傷、無劇烈運動",
    },
    "past_medical_history": "高血壓十年，controlled",
    "medications": "Amlodipine 5mg qd",
    "allergies": "Penicillin 過敏，起疹",
    "family_history": "父親：膀胱癌",
    "social_history": "吸菸每日一包，二十年",
    "review_of_systems": "無發燒、無體重減輕",
}

FULL_OBJECTIVE = {
    "vital_signs": "BP 138/86, HR 78",
    "physical_exam": "腹部柔軟，無壓痛",
    "lab_results": "尿液鏡檢 RBC 50-100/HPF",
    "imaging_results": None,
}

FULL_ASSESSMENT = {
    "clinical_impression": "無痛性肉眼血尿，需排除泌尿上皮癌",
    "differential_diagnoses": [
        {
            "diagnosis": "膀胱泌尿上皮癌",
            "likelihood": "high",
            "reasoning": "無痛性肉眼血尿＋吸菸史＋一等親膀胱癌家族史",
        },
        {
            "diagnosis": "泌尿道感染",
            "likelihood": "low",
            "reasoning": "無發燒、無排尿灼熱",
        },
    ],
}

FULL_PLAN = {
    "recommended_tests": [
        {
            "test_name": "膀胱鏡",
            "rationale": "直接評估膀胱黏膜病灶",
            "urgency": "24h",
            "clinical_reasoning": "高風險族群的無痛性血尿必須排除腫瘤",
        }
    ],
    "treatments": ["暫不給藥，先完成檢查"],
    "medications": ["維持原有 Amlodipine"],
    "follow_up": "檢查結果出爐後回診",
    "patient_education": ["請留意尿色變化並告知現場醫護"],
    "referrals": ["泌尿科門診"],
    "diagnostic_reasoning": "以腫瘤為優先排除對象",
    "urgency": "er_now",
}


def _report(**overrides):
    base = dict(
        id="00000000-0000-0000-0000-000000000001",
        generated_at=None,
        review_status=None,
        review_notes=None,
        subjective=FULL_SUBJECTIVE,
        objective=FULL_OBJECTIVE,
        assessment=FULL_ASSESSMENT,
        plan=FULL_PLAN,
        raw_transcript=None,
        summary="病患主訴無痛性血尿三天。",
        icd10_codes=["R31.9"],
        ai_confidence_score=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def html():
    return _build_report_html(_report(), language="zh-TW")


# ──────────────────────────────────────────────────────
# 1. Subjective：HPI 全欄 + 四類病史（實值斷言）
# ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value", list(FULL_SUBJECTIVE["hpi"].values()))
def test_every_hpi_subfield_value_appears(html, value):
    assert value in html, f"HPI 欄位值未出現在 PDF HTML：{value}"


@pytest.mark.parametrize("label", ["發作時間", "部位", "持續時間", "伴隨症狀", "情境"])
def test_hpi_labels_are_readable_chinese(html, label):
    assert label in html


def test_family_history_real_value_is_printed(html):
    """§R 的核心回歸：家族史修好了，紙本上也必須看得到。"""
    assert "父親：膀胱癌" in html
    assert "家族史" in html


@pytest.mark.parametrize(
    "value",
    [
        "高血壓十年，controlled",   # past_medical_history
        "Amlodipine 5mg qd",        # medications
        "Penicillin 過敏，起疹",     # allergies
        "父親：膀胱癌",              # family_history
        "吸菸每日一包，二十年",       # social_history
        "無發燒、無體重減輕",         # review_of_systems
    ],
)
def test_all_history_categories_are_printed(html, value):
    assert value in html


def test_chief_complaint_and_summary_still_present(html):
    assert "無痛性血尿三天" in html
    assert "病患主訴無痛性血尿三天。" in html


# ──────────────────────────────────────────────────────
# 2. Assessment：differential_diagnoses
# ──────────────────────────────────────────────────────

def test_differential_diagnoses_are_printed(html):
    assert "鑑別診斷" in html
    assert "膀胱泌尿上皮癌" in html
    assert "泌尿道感染" in html
    assert "無痛性肉眼血尿＋吸菸史＋一等親膀胱癌家族史" in html


def test_likelihood_enum_is_humanised(html):
    """likelihood 不該以 raw enum value 出現在醫師紙本上。"""
    assert "可能性" in html
    assert ">高<" in html or "高</td>" in html
    assert "high" not in html


def test_clinical_impression_and_icd10_still_present(html):
    assert "無痛性肉眼血尿，需排除泌尿上皮癌" in html
    assert "R31.9" in html


# ──────────────────────────────────────────────────────
# 3. Objective / Plan：欄位化，不再 json dump
# ──────────────────────────────────────────────────────

def test_objective_is_fieldised_not_json_dumped(html):
    assert "生命徵象" in html
    assert "BP 138/86, HR 78" in html
    assert "理學檢查" in html
    assert "尿液鏡檢 RBC 50-100/HPF" in html
    # 原本的 json.dumps 會留下 raw key 與 JSON 標點
    assert "&quot;vital_signs&quot;" not in html
    assert "vital_signs" not in html


def test_plan_is_fieldised_with_readable_labels(html):
    for value in (
        "膀胱鏡",
        "直接評估膀胱黏膜病灶",
        "高風險族群的無痛性血尿必須排除腫瘤",
        "暫不給藥，先完成檢查",
        "維持原有 Amlodipine",
        "檢查結果出爐後回診",
        "請留意尿色變化並告知現場醫護",
        "泌尿科門診",
        "以腫瘤為優先排除對象",
    ):
        assert value in html, f"Plan 欄位值未出現：{value}"
    for label in ("建議檢查", "處置", "追蹤安排", "衛教說明", "轉診建議", "診斷推論"):
        assert label in html


def test_urgency_enum_is_translated_to_readable_text(html):
    """`er_now` / `24h` 是給程式看的，醫師紙本要看到「立即急診」。"""
    assert "緊急度" in html
    assert "立即急診" in html      # plan.urgency = er_now
    assert "24 小時內" in html     # recommended_tests[0].urgency = 24h
    assert "er_now" not in html


# ──────────────────────────────────────────────────────
# 4. 未知鍵不得靜默丟棄 / 空值有明確標示
# ──────────────────────────────────────────────────────

def test_unknown_keys_are_still_rendered():
    """LLM 多吐 schema 外欄位時，寧可印無翻譯鍵名也不要吞掉臨床內容。"""
    report = _report(
        subjective={**FULL_SUBJECTIVE, "occupational_history": "染料工廠作業員"},
        plan={**FULL_PLAN, "custom_note": "請安排週三膀胱鏡"},
    )
    html = _build_report_html(report, language="zh-TW")
    assert "染料工廠作業員" in html
    assert "occupational history" in html  # 無翻譯 → 鍵名可讀化
    assert "請安排週三膀胱鏡" in html


def test_missing_schema_fields_render_placeholder_not_disappear():
    """欄位缺值要印佔位符，醫師才分得出「沒收集到」與「渲染漏印」。"""
    report = _report(subjective={"chief_complaint": "解尿疼痛"}, objective={})
    html = _build_report_html(report, language="zh-TW")
    assert "家族史" in html
    assert "—" in html


def test_null_objective_field_is_placeholder(html):
    """imaging_results=None 仍要列出（Objective 常態性全 null）。"""
    assert "影像檢查" in html


# ──────────────────────────────────────────────────────
# 5. 安全性不得被排版改動弄壞（與 test_report_pdf_escaping 互補）
# ──────────────────────────────────────────────────────

INJECTION = '<img src="http://attacker.example/x.png"> AT&T'


def test_escaping_survives_new_field_rendering():
    report = _report(
        subjective={**FULL_SUBJECTIVE, "family_history": INJECTION},
        assessment={
            "clinical_impression": "x",
            "differential_diagnoses": [
                {"diagnosis": INJECTION, "likelihood": "low", "reasoning": INJECTION}
            ],
        },
        plan={**FULL_PLAN, "treatments": [INJECTION]},
    )
    html = _build_report_html(report, language="zh-TW")
    assert "<img" not in html
    assert "&lt;img" in html
    assert "AT&amp;T" in html


def test_unknown_key_names_are_escaped():
    """未知鍵名本身也來自 LLM 輸出，不得原樣注入。"""
    report = _report(plan={'<script>x</script>': "v"})
    html = _build_report_html(report, language="zh-TW")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ──────────────────────────────────────────────────────
# 6. 多語系版面標籤仍有效
# ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "language,expected",
    [
        ("en-US", "Family history"),
        ("ja-JP", "家族歴"),
        ("ko-KR", "가족력"),
        ("vi-VN", "家族史"),  # 未支援語系 fallback zh-TW（與既有行為一致）
    ],
)
def test_field_labels_follow_language(language, expected):
    html = _build_report_html(_report(), language=language)
    assert expected in html
    assert "父親：膀胱癌" in html


def test_english_urgency_enum_is_translated():
    html = _build_report_html(_report(), language="en-US")
    assert "Emergency (now)" in html
    assert "er_now" not in html


# ──────────────────────────────────────────────────────
# 7. PDF 真的產得出來（排版改動不得炸 WeasyPrint）
# ──────────────────────────────────────────────────────

def test_full_report_renders_to_pdf():
    from weasyprint import HTML

    from app.services.report_service import _forbid_url_fetch

    pdf = HTML(
        string=_build_report_html(_report(), language="zh-TW"),
        url_fetcher=_forbid_url_fetch,
    ).write_pdf()
    assert pdf.startswith(b"%PDF")
