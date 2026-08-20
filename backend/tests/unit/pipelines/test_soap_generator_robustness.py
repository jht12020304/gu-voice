"""
D-4（型別守衛 ＋ 輸出截斷偵測）與 ICD-10 零碼保留的回歸測試。

## D-4：`_validate_and_fill` 沒有型別守衛（稽核實測 4/4 拋例外）

`json_object` 模式只保證「是合法 JSON 物件」，**不保證欄位型別**。
舊版只檢查 key 在不在，於是：

| LLM 吐出來的形狀 | 舊版行為 |
|---|---|
| `subjective` 是 list | `subj.get(...)` → AttributeError |
| `plan` 是 str | `plan["urgency"] = ...` → TypeError |
| 整份是 list | `"subjective" not in report` 對 list 成立 → 之後炸 |
| `hpi` 是 str | `subj["hpi"][field] = None` → TypeError |

四種都是**裸例外冒到 Celery**。更隱蔽的是型別只錯一半的兩種：

- `summary` 吐成 list → 不炸，但消毒層 `isinstance(str)` 不成立、整段跳過，
  禁語直達病患畫面；而且 `soap_reports.summary` 是 Text，寫 list 到
  asyncpg 那層才炸（此時報告已生成、OpenAI 的錢已經花掉）。
- `patient_education` 吐成 dict → 同樣繞過消毒層（只處理 list / str）。

所以本檔的斷言分兩種：**不可拋例外**，以及**消毒層仍然生效**。
後者才是病安相關的那一半——只驗「不炸」會讓修法退化成 try/except。

## D-4：輸出截斷

`finish_reason == "length"` 代表 `OPENAI_MAX_TOKENS_SOAP` 用完、輸出被切斷。
斷在非法位置 → JSONDecodeError，根因被記成「LLM 不遵守 JSON schema」；
斷在合法位置 → **解析成功但少一半欄位**，`_validate_and_fill` 補成空值，
一份殘缺報告安靜入庫。兩種都要在解析**之前**攔下來並拋可重試例外。

## ICD-10 零碼保留（2026-08-20 拍板）

白名單是泌尿科前綴表，但問診合法地會碰到鄰科診斷。e2e 實測 ED 場次
LLM 給 `F52.21`（非器質性勃起功能障礙，正確且臨床有用），validator 全數
剝除 → `icd10_codes` 進 DB 是空陣列，醫師端看到的是「AI 根本沒編碼」。
決策：全剝掉且 raw 非空 → 保留 raw 碼、`icd10_verified=False`、log warning。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AIServiceUnavailableException
from app.pipelines import soap_generator as soap_module
from app.pipelines.soap_generator import SOAPGenerator

from .patient_facing_corpus import leave_site_markers_in

_validate = SOAPGenerator._validate_and_fill


# ══════════════════════════════════════════════════════════
# 測試工具
# ══════════════════════════════════════════════════════════


def _build_generator(monkeypatch) -> SOAPGenerator:
    settings = MagicMock()
    settings.OPENAI_MODEL_SOAP = "gpt-4o"
    settings.OPENAI_TEMPERATURE_SOAP = 0.3
    settings.OPENAI_MAX_TOKENS_SOAP = 4096
    monkeypatch.setattr(
        soap_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    return SOAPGenerator(settings)


def _patch_llm(
    monkeypatch,
    generator: SOAPGenerator,
    payload: Any,
    *,
    finish_reason: str = "stop",
    raw: str | None = None,
) -> None:
    """把 OpenAI 呼叫換成替身。`raw` 可直接餵原始字串（測截斷）。"""

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**_kwargs):
        response = MagicMock()
        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.message.content = (
            raw if raw is not None else json.dumps(payload, ensure_ascii=False)
        )
        response.choices = [choice]
        response.usage = MagicMock(completion_tokens=4096)
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)


def _run_generate(generator: SOAPGenerator, **overrides) -> dict:
    kwargs: dict[str, Any] = {
        "transcript": [{"role": "patient", "content": "小便有血"}],
        "patient_info": {"age": 60},
        "chief_complaint": "血尿",
        "language": "zh-TW",
    }
    kwargs.update(overrides)
    return asyncio.run(generator.generate(**kwargs))


# ══════════════════════════════════════════════════════════
# 1. 型別守衛：畸形輸出不得拋例外
# ══════════════════════════════════════════════════════════
#
# 每一組都是稽核實測會炸的形狀。參數化的 id 就是「LLM 吐了什麼」。

_MALFORMED_REPORTS: tuple[tuple[str, Any], ...] = (
    ("top_level_is_list", [{"summary": "x"}]),
    ("top_level_is_str", "抱歉，我無法產生報告。"),
    ("subjective_is_list", {"subjective": ["主訴：血尿"], "plan": {}}),
    ("subjective_is_str", {"subjective": "血尿兩天", "plan": {}}),
    ("objective_is_list", {"objective": [], "plan": {}}),
    ("assessment_is_str", {"assessment": "疑似膀胱腫瘤", "plan": {}}),
    ("plan_is_str", {"plan": "建議尿液分析"}),
    ("plan_is_list", {"plan": ["尿液分析", "膀胱鏡"]}),
    ("hpi_is_str", {"subjective": {"hpi": "兩天前開始"}, "plan": {}}),
    ("hpi_is_list", {"subjective": {"hpi": ["兩天前開始"]}, "plan": {}}),
    ("summary_is_list", {"plan": {}, "summary": ["第一句", "第二句"]}),
    ("summary_is_dict", {"plan": {}, "summary": {"a": "第一句"}}),
    ("summary_is_number", {"plan": {}, "summary": 42}),
    ("education_is_dict", {"plan": {"patient_education": {"1": "多喝水"}}}),
    ("education_is_str_ok", {"plan": {"patient_education": "多喝水"}}),
    ("education_is_number", {"plan": {"patient_education": 7}}),
    ("icd10_is_str", {"plan": {}, "icd10_codes": "N39.0"}),
    ("icd10_is_dict", {"plan": {}, "icd10_codes": {"primary": "N39.0"}}),
    ("everything_missing", {}),
)


@pytest.mark.parametrize(
    "payload", [p for _, p in _MALFORMED_REPORTS], ids=[n for n, _ in _MALFORMED_REPORTS]
)
def test_malformed_report_does_not_raise(payload):
    """稽核實測 4/4 拋例外的那一族：一律矯正，不得往上炸。"""
    out = _validate(payload, "血尿")
    assert isinstance(out, dict)


@pytest.mark.parametrize(
    "payload", [p for _, p in _MALFORMED_REPORTS], ids=[n for n, _ in _MALFORMED_REPORTS]
)
def test_malformed_report_yields_writable_shapes(payload):
    """矯正後的形狀必須是 DB 與下游能吃的——不只是「沒炸」。

    `summary` → Text 欄位（str）；`icd10_codes` → ARRAY(String)（list）；
    四個區塊 → JSONB（dict）；`plan.urgency` → enum value。
    """
    out = _validate(payload, "血尿")
    for section in ("subjective", "objective", "assessment", "plan"):
        assert isinstance(out[section], dict), section
    assert isinstance(out["subjective"]["hpi"], dict)
    assert isinstance(out["summary"], str)
    assert isinstance(out["icd10_codes"], list)
    assert all(isinstance(code, str) for code in out["icd10_codes"])
    assert isinstance(out["plan"]["patient_education"], (list, str))
    assert out["plan"]["urgency"] in {"er_now", "24h", "this_week", "routine"}
    assert isinstance(out["confidence_score"], float)


def test_type_coercion_preserves_clinical_content():
    """矯正不得把臨床內容丟掉——list summary 要合併，不是清空。"""
    out = _validate({"plan": {}, "summary": ["第一句。", "第二句。"]}, "血尿")
    assert "第一句。" in out["summary"]
    assert "第二句。" in out["summary"]

    out = _validate({"plan": {"patient_education": {"a": "多喝水", "b": "避免憋尿"}}}, "血尿")
    assert set(out["plan"]["patient_education"]) == {"多喝水", "避免憋尿"}


def test_valid_report_is_not_disturbed_by_the_guards():
    """誤傷防線：型別正確的報告，守衛一個欄位都不准改。"""
    report = {
        "subjective": {"chief_complaint": "血尿", "hpi": {"onset": "兩天前"}},
        "objective": {"vital_signs": None},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "疑似 UTI"},
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "一週後回診",
            "patient_education": ["多喝水"],
            "referrals": [],
            "diagnostic_reasoning": "先做尿液分析",
            "urgency": "this_week",
        },
        "summary": "60 歲男性血尿兩天。",
        "icd10_codes": ["N39.0"],
        "confidence_score": 0.7,
    }
    out = _validate(report, "血尿")
    assert out["summary"] == "60 歲男性血尿兩天。"
    assert out["icd10_codes"] == ["N39.0"]
    assert out["plan"]["patient_education"] == ["多喝水"]
    assert out["plan"]["urgency"] == "this_week"
    assert out["assessment"]["clinical_impression"] == "疑似 UTI"
    assert out["subjective"]["hpi"]["onset"] == "兩天前"


def test_malformed_types_are_logged(caplog):
    """事後要查得到 LLM 到底吐了什麼形狀（只記型別名，不倒臨床文字）。"""
    with caplog.at_level("WARNING"):
        _validate({"plan": "建議尿液分析", "summary": ["a"]}, "血尿")
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "plan" in joined
    assert "summary" in joined


# ══════════════════════════════════════════════════════════
# 2. 型別守衛的真正理由：消毒層不得被跳過
# ══════════════════════════════════════════════════════════
#
# 只驗「不炸」的話，把整段包 try/except 也會過。這兩條才是病安斷言。


def test_summary_as_list_still_gets_sanitized(monkeypatch):
    """`summary` 吐成 list 時，消毒層若被跳過，禁語會直達病患畫面。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {
            "plan": {"patient_education": []},
            "summary": ["血尿兩天，無疼痛。", "請於 24 小時內就醫，讓醫師評估。"],
        },
    )
    result = _run_generate(generator)

    assert isinstance(result["summary"], str)
    assert not leave_site_markers_in(result["summary"]), result["summary"]
    assert "現場醫護人員" in result["summary"]
    # 合規的那一句原封保留
    assert "血尿兩天" in result["summary"]


def test_patient_education_as_dict_still_gets_sanitized(monkeypatch):
    """`patient_education` 吐成 dict 時同理。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {
            "plan": {"patient_education": {"1": "多喝水。", "2": "若症狀加重請立即就醫。"}},
            "summary": "血尿兩天。",
        },
    )
    result = _run_generate(generator)

    education = result["plan"]["patient_education"]
    assert isinstance(education, list)
    for item in education:
        assert not leave_site_markers_in(item), item
    assert "多喝水。" in education


def test_whole_report_as_list_does_not_break_generate(monkeypatch):
    """LLM 回 `[...]`（整份不是物件）時 generate() 仍要吐出可寫入的報告。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(monkeypatch, generator, [{"summary": "x"}])
    result = _run_generate(generator)

    assert isinstance(result["summary"], str)
    assert isinstance(result["plan"], dict)
    assert result["subjective"]["chief_complaint"] == "血尿"


# ══════════════════════════════════════════════════════════
# 3. 輸出截斷偵測
# ══════════════════════════════════════════════════════════


def test_truncated_output_raises_retryable_exception(monkeypatch):
    """finish_reason=length → 拋例外，且 `_is_retryable` 判定為可重試。"""
    from app.tasks.report_queue import _is_retryable

    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {"summary": "完整的 JSON，但 API 說它被截斷了"},
        finish_reason="length",
    )
    with pytest.raises(AIServiceUnavailableException) as excinfo:
        _run_generate(generator)

    assert _is_retryable(excinfo.value) is True


def test_truncated_output_reports_the_real_root_cause(monkeypatch):
    """
    根因必須是「max_tokens 不夠」而不是「JSON 格式錯誤」。
    這是本修復的重點：截斷斷在合法位置時，舊版會**解析成功**、
    把半份報告寫進 DB；斷在非法位置時則被記成 bad_format。
    """
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        None,
        finish_reason="length",
        raw='{"summary": "60 歲男性，主訴血尿',  # 半截 JSON
    )
    with pytest.raises(AIServiceUnavailableException) as excinfo:
        _run_generate(generator)

    details = excinfo.value.details or {}
    assert details.get("reason") == "output_truncated"
    assert details.get("finish_reason") == "length"
    # 不可被泛用 handler 重新包成 bad_format（會蓋掉根因）
    assert excinfo.value.message != "errors.soap_generation_bad_format"


def test_truncation_is_logged_with_token_budget(monkeypatch, caplog):
    generator = _build_generator(monkeypatch)
    _patch_llm(monkeypatch, generator, {"summary": "x"}, finish_reason="length")
    with caplog.at_level("ERROR"):
        with pytest.raises(AIServiceUnavailableException):
            _run_generate(generator)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "截斷" in joined
    assert "4096" in joined


def test_normal_finish_reason_is_not_treated_as_truncation(monkeypatch):
    """誤傷防線：finish_reason=stop（與缺欄位的替身）一律照常產出。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(monkeypatch, generator, {"summary": "正常結束"}, finish_reason="stop")
    assert _run_generate(generator)["summary"] == "正常結束"


def test_missing_finish_reason_does_not_raise(monkeypatch):
    """SDK 版本差異／替身沒有這個屬性時，檢查層不可自己變成故障點。"""
    generator = _build_generator(monkeypatch)

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**_kwargs):
        class _Choice:
            message = MagicMock(content='{"summary": "no finish_reason"}')

        class _Resp:
            choices = [_Choice()]

        return _Resp()

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    assert _run_generate(generator)["summary"] == "no finish_reason"


# ══════════════════════════════════════════════════════════
# 4. ICD-10 零碼保留
# ══════════════════════════════════════════════════════════


def test_all_codes_stripped_preserves_raw_unverified(monkeypatch):
    """
    e2e 實證情境：ED 場次 LLM 給 `F52.21`（非器質性勃起功能障礙），
    泌尿科白名單全數剝除 → 舊版寫入空陣列，醫師端看起來像「AI 沒編碼」。
    現在保留 raw 碼、但 `icd10_verified=False`。
    """
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {"plan": {}, "summary": "55 歲男性勃起功能障礙。", "icd10_codes": ["F52.21"]},
    )
    result = _run_generate(generator, chief_complaint="勃起功能障礙", symptom_id="erectile_dysfunction")

    assert result["icd10_codes"] == ["F52.21"]
    assert result["icd10_verified"] is False


def test_zero_code_preservation_is_logged_as_warning(monkeypatch, caplog):
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch, generator, {"plan": {}, "summary": "x", "icd10_codes": ["F52.21"]}
    )
    with caplog.at_level("WARNING"):
        _run_generate(generator)
    joined = "\n".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert "白名單外碼保留未驗證" in joined
    assert "F52.21" in joined


def test_partial_strip_does_not_resurrect_the_stripped_codes(monkeypatch):
    """
    界線：**只有全剝掉**才保留。部分命中代表白名單正常運作，
    這時把被剝掉的雜碼放回去等於讓 hallucination 過關（J18 肺炎）。
    """
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {"plan": {}, "summary": "x", "icd10_codes": ["N39.0", "J18.9"]},
    )
    result = _run_generate(generator, symptom_id="uti")

    assert "J18.9" not in result["icd10_codes"]
    assert "N39.0" in result["icd10_codes"]


def test_empty_raw_codes_stay_empty(monkeypatch):
    """LLM 本來就沒給碼 → 保持空，不得憑空生出東西。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(monkeypatch, generator, {"plan": {}, "summary": "x", "icd10_codes": []})
    result = _run_generate(generator)

    assert result["icd10_codes"] == []
    assert result["icd10_verified"] is False


def test_verified_codes_keep_their_verified_flag(monkeypatch):
    """誤傷防線：正常通過驗證的碼不受本修復影響。"""
    from app.pipelines.icd10_validator import validate_icd10_codes

    codes, verified = validate_icd10_codes(["N39.0"], "uti")
    if not verified:  # pragma: no cover — 對映表若改動就跳過，避免假失敗
        pytest.skip("uti↔N39 對映不在現行 SYMPTOM_TO_ICD10 中")

    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch, generator, {"plan": {}, "summary": "x", "icd10_codes": ["N39.0"]}
    )
    result = _run_generate(generator, symptom_id="uti")

    assert result["icd10_codes"] == codes
    assert result["icd10_verified"] is True


def test_non_string_codes_are_dropped_when_preserving(monkeypatch):
    """保留 raw 時仍要保證是 list[str]（DB 是 ARRAY(String)）。"""
    generator = _build_generator(monkeypatch)
    _patch_llm(
        monkeypatch,
        generator,
        {"plan": {}, "summary": "x", "icd10_codes": ["F52.21", None, "", {"a": 1}]},
    )
    result = _run_generate(generator)

    assert result["icd10_codes"] == ["F52.21"]
    assert all(isinstance(code, str) for code in result["icd10_codes"])


# ══════════════════════════════════════════════════════════
# 5. 病患語言版的病患面兩欄（localize_patient_facing）
# ══════════════════════════════════════════════════════════
#
# 這是 `_PATIENT_FACING_CLAUSE` 五語文案第一次真的活起來的地方：
# 在此之前報告固定 zh-TW（#12），其餘四語的替換文案是死碼。
# 所以本節的重點是**消毒層的語言參數真的接上了**——不是只驗「有回東西」。

_LOCALIZE_LANGUAGES = ("en-US", "ja-JP", "ko-KR", "vi-VN")


def _patch_localizer(monkeypatch, generator, payload: Any, *, finish_reason="stop"):
    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        response = MagicMock()
        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.message.content = (
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        )
        response.choices = [choice]
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)


def _localize(generator, **kwargs) -> dict:
    base = {
        "summary": "60 歲男性血尿兩天。",
        "patient_education": "請稍候等待看診。",
        "target_language": "en-US",
    }
    base.update(kwargs)
    return asyncio.run(generator.localize_patient_facing(**base))


@pytest.mark.parametrize("language", _LOCALIZE_LANGUAGES)
def test_localized_output_is_sanitized_in_the_target_language(monkeypatch, language):
    """
    翻譯層會「還原」它以為被和諧掉的醫囑——中文原文合規不代表譯文合規。
    譯文必須過**目標語言**的消毒規則，而不是 zh-TW 的。
    """
    from app.pipelines.soap_generator import _PATIENT_FACING_CLAUSE

    violations = {
        "en-US": "Please see a doctor within 24 hours if it gets worse.",
        "ja-JP": "悪化した場合は24時間以内に受診してください。",
        "ko-KR": "악화되면 24시간 이내에 진료를 받으세요.",
        "vi-VN": "Nếu nặng hơn, xin hãy đi khám trong vòng 24 giờ.",
    }
    generator = _build_generator(monkeypatch)
    _patch_localizer(
        monkeypatch,
        generator,
        {"summary": "Recap.", "patient_education": violations[language]},
    )
    out = _localize(generator, target_language=language)

    assert out["language"] == language
    assert not leave_site_markers_in(out["patient_education"]), out
    # 用的是**該語言**的替換文案，不是中文那句
    assert _PATIENT_FACING_CLAUSE[language].rstrip("。") .lower() in (
        out["patient_education"].lower()
    ), out


def test_localized_compliant_output_is_untouched(monkeypatch):
    """誤傷防線：合規譯文一個字都不准動。"""
    text = "Please wait here; the on-site clinical staff will call you."
    generator = _build_generator(monkeypatch)
    _patch_localizer(
        monkeypatch, generator, {"summary": "Recap.", "patient_education": text}
    )
    out = _localize(generator)

    assert out["patient_education"] == text
    assert out["summary"] == "Recap."


def test_localizer_uses_the_cheap_model(monkeypatch):
    """純翻譯任務不該燒 SOAP 主模型的錢。"""
    generator = _build_generator(monkeypatch)
    generator._settings.OPENAI_MODEL_SUMMARIZER = "gpt-4o-mini"
    captured: dict = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured.update(kwargs)
        response = MagicMock()
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message.content = json.dumps({"summary": "s", "patient_education": "e"})
        response.choices = [choice]
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)
    _localize(generator)

    assert captured["model"] == "gpt-4o-mini"
    assert captured["response_format"] == {"type": "json_object"}


def test_localizer_prompt_forbids_adding_advice(monkeypatch):
    """
    翻譯層最常見的越界就是「順手補一句衛教」。prompt 必須明令只轉述，
    且必須帶上 kiosk 情境（否則譯文會自作主張寫 "go to the ER"）。
    """
    generator = _build_generator(monkeypatch)
    captured: dict = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured.update(kwargs)
        response = MagicMock()
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message.content = json.dumps({"summary": "s", "patient_education": "e"})
        response.choices = [choice]
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)
    _localize(generator, target_language="ja-JP")

    system = captured["messages"][0]["content"]
    assert "TRANSLATE ONLY" in system
    assert "Do NOT invent medical advice" in system
    assert "waiting area" in system
    assert "emergency room" in system  # 明令禁止叫病患離場
    assert "Japanese" in system  # 目標語言真的帶進去了


@pytest.mark.parametrize(
    "bad",
    [
        {"summary": "s"},  # 缺 patient_education
        {"summary": 1, "patient_education": "e"},  # 型別錯
        {"summary": "", "patient_education": "  "},  # 全空
        ["s", "e"],  # 不是 dict
    ],
)
def test_malformed_localization_raises(monkeypatch, bad):
    """壞掉的轉述一律拋例外 → 呼叫端留 NULL（前端 fallback 回中文原文）。

    半套譯文比沒有譯文更糟：病患畫面會出現半英半中的殘句。
    """
    generator = _build_generator(monkeypatch)
    _patch_localizer(monkeypatch, generator, bad)
    with pytest.raises(Exception):
        _localize(generator)


def test_truncated_localization_raises(monkeypatch):
    generator = _build_generator(monkeypatch)
    _patch_localizer(
        monkeypatch,
        generator,
        {"summary": "s", "patient_education": "e"},
        finish_reason="length",
    )
    with pytest.raises(ValueError):
        _localize(generator)


def test_unsupported_target_language_raises(monkeypatch):
    generator = _build_generator(monkeypatch)
    _patch_localizer(monkeypatch, generator, {"summary": "s", "patient_education": "e"})
    with pytest.raises(ValueError):
        _localize(generator, target_language="de-DE")


def test_empty_source_raises_without_calling_openai(monkeypatch):
    """兩欄都空 → 不必浪費一次呼叫。"""
    generator = _build_generator(monkeypatch)
    generator._client.chat.completions.create = AsyncMock(
        side_effect=AssertionError("不該呼叫 OpenAI")
    )
    with pytest.raises(ValueError):
        _localize(generator, summary="", patient_education="   ")
