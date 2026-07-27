"""
BLOCKER C：SOAP 病患面欄位不得出現「叫病患自行離場就醫」的措辭。

## 病患面欄位是哪些（讀兩份前端 code 確認，不是猜的）

    plan.patient_education
        frontend/src/screens/patient/PatientSessionDetailPage.tsx:63
            `const raw: unknown = report?.plan?.patientEducation;` → 「給您的建議」清單
        flutter_app/lib/features/patient/patient_session_detail_page.dart:80
    summary
        frontend/src/screens/patient/PatientSessionDetailPage.tsx:111 「本次摘要」
        frontend/src/screens/patient/SessionCompletePage.tsx:164   問診結束頁
        flutter_app/lib/features/patient/patient_session_detail_page.dart:122-125

    這兩處是兩份前端唯一讀取 SOAP 內容的地方。`review_notes` 曾是
    patientEducation 的 fallback，但兩份前端這輪都已移除（醫師審閱備註不給病患看），
    所以本層不掃它——掃了反而會改到醫師的文字。

部署情境是院內候診 kiosk（病患已在現場等看診），叫他「立即就醫／立即急診」
等於叫他離開現場自己跑去別家醫院。

## 前一輪為什麼 2804 個 test 全綠、真跑 t8 照樣 FAIL

1. 規則用固定距離上限（`{0,8}`）串接副詞與地點，LLM 寫長一點就繞過。真跑
   `torsion_critical_zh` 的 summary 是「需立即進行超音波檢查和泌尿科急診評估」，
   「立即」與「急診」相隔 11 字 → 整條漏掉。
2. **測試的 oracle 是實作自己的偵測器**（`_PATIENT_FACING_RESIDUAL`）——用同一個
   偵測器判斷「有沒有消毒乾淨」，偵測器漏掉的句型測試也一定漏掉（循環斷言）。
3. 測試 fixture 取的是第一輪觀察到的**短版**違規句，接不住第二輪真跑的長版。

## 本檔的作法

判準改成 `patient_facing_corpus.py` 裡**手寫、獨立維護**的字面片語清單，
一行 `app.pipelines.soap_generator` 的規則都不 import。語料雙向且對稱：
`LEAVE_SITE_CORPUS`（必須被消毒）與 `COMPLIANT_CORPUS`（一個字都不准動）
兩邊都含 realrun / paraphrase / minimalpair 三種來源，minimalpair 是與正例
只差一個「施事者是院方」標記的良性句，專門釘住
「有沒有叫他離場」這條界線不會因為收緊或放寬規則而漂移。
"""

import copy

import pytest

from app.pipelines.soap_generator import (
    _PATIENT_FACING_CLAUSE,
    _PATIENT_FACING_FALLBACK,
    _SOAP_SYSTEM_PROMPT,
    SOAPGenerator,
    _split_clauses,
)

from .patient_facing_corpus import (
    COMPLIANT_CORPUS,
    LEAVE_SITE_CORPUS,
    LEAVE_SITE_MARKERS,
    ON_SITE_REDIRECT_MARKERS,
    leave_site_markers_in,
)

_sanitize_text = SOAPGenerator._sanitize_patient_facing_text
_sanitize_fields = SOAPGenerator._sanitize_patient_facing_fields


def _id(entry: tuple[str, str, str]) -> str:
    provenance, language, text = entry
    return f"{provenance}-{language}-{text[:24]}"


# ══ 0. 語料庫自身的健全性 ═══════════════════════════════
#
# 語料是本檔的判準，判準壞掉的話下面每一條測試都是空的。


def test_corpus_is_bidirectional_and_non_trivial():
    """雙向且都有份量——避免又變成單向加測試（前兩輪各犯一次）。"""
    assert len(LEAVE_SITE_CORPUS) >= 25, "正例太少"
    assert len(COMPLIANT_CORPUS) >= 25, "反例太少"


def test_corpus_covers_all_five_languages_in_both_directions():
    for corpus, label in ((LEAVE_SITE_CORPUS, "正例"), (COMPLIANT_CORPUS, "反例")):
        languages = {language for _, language, _ in corpus}
        assert languages >= set(ON_SITE_REDIRECT_MARKERS), f"{label} 語言未覆蓋齊：{languages}"


def test_corpus_has_real_run_and_fresh_paraphrases_on_both_sides():
    """
    只有真跑句 → 等於拿實作配適當時那幾句；只有新寫句 → 沒接住真實 LLM 行為。
    兩種來源都要有，而且反例要有 minimalpair（跟正例只差施事者的良性句）。
    """
    for corpus, label in ((LEAVE_SITE_CORPUS, "正例"), (COMPLIANT_CORPUS, "反例")):
        provenances = {p for p, _, _ in corpus}
        assert "realrun" in provenances, f"{label} 缺真跑語料"
        assert "paraphrase" in provenances, f"{label} 缺新寫改述語料"
    assert "minimalpair" in {p for p, _, _ in COMPLIANT_CORPUS}


def test_compliant_corpus_does_not_contain_any_oracle_marker():
    """
    反例本身不可含 oracle 字面片語，否則「反例不該被改」與
    「oracle 命中就是違規」兩個判準會互相矛盾。
    """
    for provenance, language, text in COMPLIANT_CORPUS:
        assert not leave_site_markers_in(text), (provenance, language, text)


def test_oracle_is_not_derived_from_the_implementation():
    """
    oracle 必須是純字面清單。若哪天有人把實作的 regex 塞進來，
    循環斷言就回來了——這條測試就是那道閘。
    """
    assert all(isinstance(marker, str) for marker in LEAVE_SITE_MARKERS)
    regex_metachars = set("()[]{}|\\^$*+?")
    for marker in LEAVE_SITE_MARKERS:
        assert not (set(marker) & regex_metachars), f"oracle 混進 regex：{marker!r}"


@pytest.mark.parametrize(
    "entry", list(LEAVE_SITE_CORPUS) + list(COMPLIANT_CORPUS), ids=_id
)
def test_clause_split_is_lossless(entry):
    """
    分句是整層的地基：切開再接回去必須逐字還原原文，否則「合規內容原封不動」
    這條硬性契約會在標點上默默破功（真的發生過——`dial 911.` 的句號被吃掉）。
    """
    _provenance, _language, text = entry
    assert "".join(seg + delim for seg, delim in _split_clauses(text)) == text


# ══ 1. 正例：必須被消毒（雙向斷言）════════════════════════


@pytest.mark.parametrize("entry", LEAVE_SITE_CORPUS, ids=_id)
def test_leave_site_text_is_sanitized(entry):
    """(a) 出口不得殘留任何 oracle 字面禁語。"""
    _provenance, language, text = entry
    cleaned, hits = _sanitize_text(text, language)
    assert hits, f"漏偵測：{text}"
    residual = leave_site_markers_in(cleaned)
    assert not residual, f"消毒後仍殘留 {residual}：{cleaned}"


@pytest.mark.parametrize("entry", LEAVE_SITE_CORPUS, ids=_id)
def test_leave_site_text_is_redirected_to_on_site_staff(entry):
    """
    (b) 光是「沒有禁語」不夠——本輪修的那一族違規（「需立即進行超音波檢查和
    泌尿科急診評估」）本來就不含字面禁語，只驗 (a) 的話消毒層什麼都不做也會過。
    必須真的把病患導向現場醫護。
    """
    _provenance, language, text = entry
    cleaned, _ = _sanitize_text(text, language)
    assert cleaned != text, f"完全沒被改：{text}"
    assert ON_SITE_REDIRECT_MARKERS[language] in cleaned, cleaned


@pytest.mark.parametrize("entry", LEAVE_SITE_CORPUS, ids=_id)
def test_sanitized_output_is_itself_clean(entry):
    """出口必須是不動點：消毒過的文字再消毒一次不得再被改。"""
    _provenance, language, text = entry
    cleaned, _ = _sanitize_text(text, language)
    twice, hits = _sanitize_text(cleaned, language)
    assert hits == [], hits
    assert twice == cleaned


def test_long_distance_violation_from_the_failing_real_run():
    """
    回歸釘子：真跑 torsion_critical_zh 的 summary，讓 t8 FAIL 的那一句。
    「立即」與「急診」相隔 11 字，固定距離上限的規則接不住。
    """
    text = (
        "30歲男性患者，主訴左邊睪丸突然劇烈疼痛，伴隨陰囊腫脹和噁心，症狀持續約兩小時。"
        "高度懷疑睪丸扭轉，需立即進行超音波檢查和泌尿科急診評估。"
    )
    cleaned, hits = _sanitize_text(text, "zh-TW")
    assert hits
    assert "急診評估" not in cleaned
    # 前半段的臨床事實整段保留，只有違規的那個分句被換掉。
    assert "陰囊腫脹" in cleaned
    assert "症狀持續約兩小時" in cleaned
    assert "現場醫護人員" in cleaned


def test_clinical_content_in_other_clauses_survives():
    """
    誤傷防線：只換掉違規的那個分句，同段其他分句（警訊症狀清單）原封保留。
    """
    cleaned, _ = _sanitize_text(
        "若出血加重或出現疼痛、頭暈、排尿困難，立即就醫。", "zh-TW"
    )
    for token in ("出血加重", "頭暈", "排尿困難"):
        assert token in cleaned, f"{token!r} 被誤刪：{cleaned}"
    assert "現場醫護人員" in cleaned


# ══ 2. 反例：一個字都不准動 ══════════════════════════════


@pytest.mark.parametrize("entry", COMPLIANT_CORPUS, ids=_id)
def test_compliant_text_passes_through_untouched(entry):
    _provenance, language, text = entry
    cleaned, hits = _sanitize_text(text, language)
    assert hits == [], f"合規內容被誤判為禁語：{hits}"
    assert cleaned == text


@pytest.mark.parametrize("entry", COMPLIANT_CORPUS, ids=_id)
def test_compliant_text_untouched_in_every_language(entry):
    """輸出語言參數不應改變「合規內容不動」這件事。"""
    _provenance, _language, text = entry
    for language in ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN", None, "de-DE"):
        cleaned, hits = _sanitize_text(text, language)
        assert hits == [], (language, hits)
        assert cleaned == text


def test_bare_er_disposition_by_the_clinic_is_not_a_violation():
    """
    覆核點名的界線：「醫師會為您安排急診評估」對候診中的病患**不違規**
    （沒有叫他離場），裸詞「急診評估」不該一律替換。
    """
    for text in (
        "醫師會為您安排急診評估，請在原位稍候。",
        "現場醫護人員會立即為您安排超音波檢查與泌尿科急診評估。",
        "急診評估的結果會併入今天的病歷。",
        "這項檢查在本院急診就能完成，不需要另外跑一趟。",
    ):
        cleaned, hits = _sanitize_text(text, "zh-TW")
        assert hits == [], (text, hits)
        assert cleaned == text


def test_urgency_adverb_alone_is_not_a_violation():
    """「盡快」本身不是禁語——只有它指向『去別的地方求醫』才是。"""
    for text in (
        "戒菸是降低膀胱癌風險最有效的方式，建議盡快開始。",
        "請盡快完成尿液採檢，檢體桶就在洗手間旁邊。",
        "醫師會盡快為您診療，請在候診區稍候。",
    ):
        cleaned, hits = _sanitize_text(text, "zh-TW")
        assert hits == [], (text, hits)
        assert cleaned == text


def test_clinic_side_movement_verbs_are_not_violations():
    """
    `scripts/e2e_realopenai/driver.py` 也踩過的坑：「the urologist will come to the
    emergency department」是院方施事，不是叫病患走。come/drive 這類動詞不可
    無條件當違規。
    """
    for text in (
        "The urologist will come to the emergency department shortly.",
        "Our team will come to the ER with you.",
        "A nurse will come and collect you for the scan.",
    ):
        cleaned, hits = _sanitize_text(text, "en-US")
        assert hits == [], (text, hits)
        assert cleaned == text


def test_empty_and_blank_text_untouched():
    for value in ("", "   ", "\n"):
        cleaned, hits = _sanitize_text(value, "zh-TW")
        assert cleaned == value
        assert hits == []


# ══ 3. 可讀性：改寫後的字是原文顯示在病患畫面上的 ═════════


def test_no_duplicated_particles_or_broken_punctuation():
    """
    命中時整個分句換成固定文案（不做字串手術），所以不會出現
    「請請立即…」這種重複詞，句末標點也必須留著。
    """
    samples = [
        ("zh-TW", "如果症狀惡化，請立刻，馬上，前往急診。"),
        ("zh-TW", "病情變化快速，請不要等待，直接掛急診。"),
        ("ja-JP", "痛みが強まる場合は、大至急、近くの病院へ行ってください。"),
    ]
    for language, text in samples:
        cleaned, _ = _sanitize_text(text, language)
        assert "請請" not in cleaned, cleaned
        assert "，，" not in cleaned and "、、" not in cleaned, cleaned
        assert cleaned.endswith("。"), cleaned


def test_sentence_final_period_is_preserved_after_a_digit():
    """
    `dial 911.` 的句號一度被當成分句內容、替換時連句號一起吃掉
    （拉丁句號規則要求前面是字母所致）。病患畫面上會看到沒有句點的殘句。
    """
    cleaned, hits = _sanitize_text(
        "If you lose consciousness at home, have a family member dial 911.", "en-US"
    )
    assert hits
    assert cleaned.endswith("."), cleaned


def test_replacement_is_capitalised_when_it_starts_a_sentence():
    cleaned, _ = _sanitize_text(
        "Symptoms like these warrant immediate evaluation at an emergency room.",
        "en-US",
    )
    assert cleaned[0].isupper(), cleaned


def test_replacement_stays_lowercase_mid_sentence():
    cleaned, _ = _sanitize_text(
        "Should the bleeding become heavier overnight, proceed to the nearest "
        "emergency department for assessment.",
        "en-US",
    )
    assert "overnight, please tell" in cleaned, cleaned


def test_adjacent_violating_clauses_collapse_into_one_sentence():
    """相鄰的連續違規分句不得各貼一次文案。"""
    cleaned, hits = _sanitize_text("請立即就醫，並儘速前往急診室。", "zh-TW")
    assert hits
    assert cleaned.count("現場醫護人員") == 1, cleaned


# ══ 4. 在地化文案自身必須合規 ════════════════════════════


@pytest.mark.parametrize("language", sorted(_PATIENT_FACING_CLAUSE))
def test_localised_clause_and_fallback_are_themselves_compliant(language):
    """
    替換文案／兜底文案自己不得含禁語，否則消毒反而變成新的違規來源
    （也保證 sanitize 是不動點、不會無窮遞迴出髒字）。
    """
    for text in (_PATIENT_FACING_CLAUSE[language], _PATIENT_FACING_FALLBACK[language]):
        assert not leave_site_markers_in(text), text
        cleaned, hits = _sanitize_text(text, language)
        assert hits == [], (language, text, hits)
        assert cleaned == text


def test_every_supported_language_has_both_clause_and_fallback_copy():
    assert set(_PATIENT_FACING_CLAUSE) == set(_PATIENT_FACING_FALLBACK)
    assert set(_PATIENT_FACING_CLAUSE) == set(ON_SITE_REDIRECT_MARKERS)


def test_unsupported_and_none_language_fall_back_to_zh():
    for language in (None, "de-DE", "", "zh"):
        cleaned, hits = _sanitize_text("請立即就醫。", language)
        assert hits
        assert ON_SITE_REDIRECT_MARKERS["zh-TW"] in cleaned, (language, cleaned)


# ══ 5. prompt 層（第一道防線，仍要守著）═══════════════════


def test_prompt_names_both_patient_facing_fields():
    assert "病患直接看得到" in _SOAP_SYSTEM_PROMPT
    assert "`plan.patient_education`" in _SOAP_SYSTEM_PROMPT
    assert "`summary`" in _SOAP_SYSTEM_PROMPT


def test_prompt_lists_banned_phrases():
    for banned in ("立即就醫", "盡速就醫", "趕快去醫院", "立即前往急診"):
        assert banned in _SOAP_SYSTEM_PROMPT, banned


def test_prompt_gives_correct_wording_template():
    assert "請立即告知現場醫護人員" in _SOAP_SYSTEM_PROMPT
    assert "請稍候等待看診" in _SOAP_SYSTEM_PROMPT


def test_prompt_keeps_er_disposition_in_doctor_fields():
    """避免 prompt 把「需急診」整個從報告裡抹掉：急診判斷要寫在醫師面欄位。"""
    assert "醫師面" in _SOAP_SYSTEM_PROMPT
    assert "需急診評估" in _SOAP_SYSTEM_PROMPT
    assert "`plan.urgency`" in _SOAP_SYSTEM_PROMPT


def test_prompt_tells_llm_to_keep_warning_symptoms():
    assert "警訊症狀" in _SOAP_SYSTEM_PROMPT


# ══ 6. 欄位層：只動病患面、醫師面一字不改 ═════════════════


def _report_with_violations() -> dict:
    """病患面與醫師面同時含急診字眼的報告（病患面兩欄用真跑違規句）。"""
    return {
        "summary": (
            "30歲男性患者，主訴左邊睪丸突然劇烈疼痛，伴隨陰囊腫脹和噁心，"
            "症狀持續約兩小時。高度懷疑睪丸扭轉，需立即進行超音波檢查和泌尿科急診評估。"
        ),
        "assessment": {
            "clinical_impression": "⚠️ 偵測到紅旗徵象，需優先緊急評估。疑似睪丸扭轉，需立即急診手術探查。",
            "differential_diagnoses": [
                {
                    "diagnosis": "睪丸扭轉",
                    "likelihood": "high",
                    "reasoning": "突發劇痛合併噁心，須立即就醫排除。",
                }
            ],
        },
        "plan": {
            "recommended_tests": [
                {
                    "test_name": "陰囊超音波",
                    "rationale": "須立即就醫確認血流",
                    "urgency": "er_now",
                    "clinical_reasoning": "建議至急診立即安排。",
                }
            ],
            "treatments": ["立即就醫接受手術探查"],
            "medications": [],
            "follow_up": "立即至急診進行進一步評估和處理。",
            "patient_education": [
                "若出血加重或出現疼痛、頭暈、排尿困難，立即就醫。",
                "建議戒菸以減少泌尿系統疾病風險。",
            ],
            "referrals": ["立即轉診至急診泌尿科"],
            "diagnostic_reasoning": "需立即急診評估以免睪丸壞死。",
            "urgency": "er_now",
        },
    }


def test_patient_facing_fields_are_sanitized():
    report = _sanitize_fields(_report_with_violations(), "zh-TW")
    assert not leave_site_markers_in(report["summary"]), report["summary"]
    assert "急診評估" not in report["summary"]
    for item in report["plan"]["patient_education"]:
        assert not leave_site_markers_in(item), item


def test_compliant_patient_education_item_is_not_touched():
    """同一個 list 裡合規的那一條不得被連坐改掉。"""
    report = _sanitize_fields(_report_with_violations(), "zh-TW")
    assert "建議戒菸以減少泌尿系統疾病風險。" in report["plan"]["patient_education"]


def test_doctor_facing_fields_are_not_touched():
    """
    誤傷防線（最重要的一條）：醫師需要看到「需急診評估」這種處置判斷，
    這些欄位一個字都不能被改。
    """
    before = _report_with_violations()
    after = _sanitize_fields(_report_with_violations(), "zh-TW")

    assert after["assessment"] == before["assessment"]
    for field in (
        "recommended_tests",
        "treatments",
        "medications",
        "follow_up",
        "referrals",
        "diagnostic_reasoning",
        "urgency",
    ):
        assert after["plan"][field] == before["plan"][field], field


def test_er_disposition_still_visible_to_doctor_after_sanitize():
    after = _sanitize_fields(_report_with_violations(), "zh-TW")
    assert after["plan"]["urgency"] == "er_now"
    assert "急診" in after["plan"]["follow_up"]
    assert "急診" in after["assessment"]["clinical_impression"]


def test_compliant_report_is_not_modified_at_all():
    report = {
        "summary": "68 歲男性主訴頻尿，考慮良性前列腺增生可能性較高。",
        "plan": {
            "patient_education": [
                "建議患者記錄每日排尿次數和飲水量。",
                "若症狀加重，請立即告知現場醫護人員。",
            ],
            "follow_up": "建議一個月內回診。",
            "urgency": "routine",
        },
        "assessment": {"clinical_impression": "疑似 BPH。"},
    }
    before = copy.deepcopy(report)
    assert _sanitize_fields(report, "zh-TW") == before


def test_patient_education_as_plain_string_is_handled():
    """LLM 偶爾把 list 欄位吐成字串，也要照樣消毒（不可 crash、不可漏）。"""
    report = {"plan": {"patient_education": "有狀況請立即就醫。"}}
    after = _sanitize_fields(report, "zh-TW")
    assert not leave_site_markers_in(after["plan"]["patient_education"])


def test_non_string_items_survive_sanitize():
    """list 內混入非字串（LLM 亂吐）時不可 crash，也不可被丟掉。"""
    report = {"plan": {"patient_education": ["立即就醫", None, 42, {"a": 1}]}}
    after = _sanitize_fields(report, "zh-TW")
    items = after["plan"]["patient_education"]
    assert len(items) == 4
    assert items[1] is None and items[2] == 42 and items[3] == {"a": 1}
    assert not leave_site_markers_in(items[0])


def test_missing_fields_do_not_crash_or_invent_keys():
    assert _sanitize_fields({}, "zh-TW") == {}


def test_review_notes_is_left_alone():
    """
    review_notes 是醫師的審閱備註，兩份前端都已不再顯示給病患。
    掃它等於改醫師的字——這條測試釘住「不掃」這個決定。
    """
    report = {"review_notes": "已電話聯繫泌尿科，安排立即急診手術探查。"}
    after = _sanitize_fields(copy.deepcopy(report), "zh-TW")
    assert after == report


def test_violation_is_logged_with_the_offending_phrase(caplog):
    """要能事後知道 LLM 到底又寫了什麼（只記命中片語，不倒整段臨床文字）。"""
    with caplog.at_level("WARNING"):
        _sanitize_fields(_report_with_violations(), "zh-TW")
    messages = [r.getMessage() for r in caplog.records if "病患面措辭違規" in r.getMessage()]
    assert messages, caplog.text
    joined = "\n".join(messages)
    assert "plan.patient_education" in joined
    assert "summary" in joined
    assert "立即就醫" in joined


# ══ 7. 接線：generate() 真的有呼叫消毒層 ═══════════════════
#
# 上面的測試都直接打 static method；這裡走完整 generate()，證明
# 「LLM 吐禁語 → 回給 report_queue 的 dict 已經是乾淨的」。
# （app/tasks/report_queue.py 是 SOAPGenerator 在生產的唯一呼叫點，
#   report.summary / report.plan 直接寫這個 dict，沒有繞過消毒層的路徑。）


def _build_generator(monkeypatch):
    from unittest.mock import MagicMock

    from app.pipelines import soap_generator as soap_module

    settings = MagicMock()
    settings.OPENAI_MODEL_SOAP = "gpt-4o"
    settings.OPENAI_TEMPERATURE_SOAP = 0.3
    settings.OPENAI_MAX_TOKENS_SOAP = 4096
    monkeypatch.setattr(
        soap_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    return SOAPGenerator(settings)


def _patch_llm_response(monkeypatch, generator, report: dict) -> None:
    import json
    from unittest.mock import AsyncMock, MagicMock

    from app.pipelines import soap_generator as soap_module

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**_kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps(report, ensure_ascii=False)
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)


def test_generate_returns_sanitized_patient_facing_fields(monkeypatch):
    import asyncio

    generator = _build_generator(monkeypatch)
    _patch_llm_response(monkeypatch, generator, _report_with_violations())

    result = asyncio.run(
        generator.generate(
            transcript=[{"role": "patient", "content": "左睪丸劇痛"}],
            patient_info={"age": 30},
            chief_complaint="睪丸痛",
            language="zh-TW",
        )
    )

    assert not leave_site_markers_in(result["summary"]), result["summary"]
    assert "急診評估" not in result["summary"]
    for item in result["plan"]["patient_education"]:
        assert not leave_site_markers_in(item), item
    # 醫師面欄位仍看得到急診處置
    assert result["plan"]["urgency"] == "er_now"
    assert "急診" in result["plan"]["follow_up"]
    assert "急診" in result["assessment"]["clinical_impression"]


def test_generate_leaves_compliant_report_untouched(monkeypatch):
    import asyncio

    generator = _build_generator(monkeypatch)
    clean_report = {
        "subjective": {"chief_complaint": "頻尿"},
        "objective": {},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "疑似 BPH"},
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "建議一個月內回診。",
            "patient_education": ["建議記錄每日排尿次數與飲水量。"],
            "referrals": [],
            "diagnostic_reasoning": "以尿液分析與 PSA 起始。",
            "urgency": "routine",
        },
        "summary": "68 歲男性主訴頻尿，考慮良性前列腺增生。",
        "icd10_codes": [],
        "confidence_score": 0.6,
    }
    _patch_llm_response(monkeypatch, generator, clean_report)

    result = asyncio.run(
        generator.generate(
            transcript=[{"role": "patient", "content": "頻尿"}],
            patient_info={"age": 68},
            chief_complaint="頻尿",
            language="zh-TW",
        )
    )

    assert result["summary"] == clean_report["summary"]
    assert result["plan"]["patient_education"] == clean_report["plan"]["patient_education"]


# ══ 8. 附帶：age == 0 truthy bug（與 llm_conversation.py 同型）═══


def _capture_user_message(monkeypatch, generator) -> dict:
    import json
    from unittest.mock import AsyncMock, MagicMock

    from app.pipelines import soap_generator as soap_module

    captured: dict = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps({"summary": ""})
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)
    return captured


@pytest.mark.parametrize("age,expected", [(0, "Age: 0"), (68, "Age: 68")])
def test_age_zero_still_reaches_soap_prompt(monkeypatch, age, expected):
    """
    `if patient_info.get("age")` 會讓 age==0 的病患整行年齡從 SOAP prompt 消失
    （與 llm_conversation.py 同型的 truthy bug）。必須是 `is not None`。
    """
    import asyncio

    generator = _build_generator(monkeypatch)
    captured = _capture_user_message(monkeypatch, generator)

    asyncio.run(
        generator.generate(
            transcript=[{"role": "patient", "content": "哭鬧不安"}],
            patient_info={"age": age, "gender": "male"},
            chief_complaint="排尿異常",
            language="zh-TW",
        )
    )

    assert expected in captured["messages"][1]["content"]


def test_age_absent_omits_the_line(monkeypatch):
    """age 缺席時不該憑空寫出 `Age: None`。"""
    import asyncio

    generator = _build_generator(monkeypatch)
    captured = _capture_user_message(monkeypatch, generator)

    asyncio.run(
        generator.generate(
            transcript=[{"role": "patient", "content": "頻尿"}],
            patient_info={"gender": "male"},
            chief_complaint="頻尿",
            language="zh-TW",
        )
    )

    assert "Age:" not in captured["messages"][1]["content"]
