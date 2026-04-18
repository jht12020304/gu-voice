"""
Unit tests for TODO-M13（Urgency enum 化）。

覆蓋：
- Urgency enum 4 值完整
- i18n_messages 8 個 key（4 urgency × 2 locale）存在
- _coerce_urgency: 合法 enum value 放行、怪值 fallback 成 routine
- SOAPGenerator 輸出的 plan.urgency 一定落在 4 enum value
- prompt 內含 4 個 enum value 字串
- recommended_tests item 的 urgency 也會被 enum 化
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from app.models.enums import URGENCY_VALUES, Urgency
from app.pipelines import soap_generator as soap_module
from app.pipelines.soap_generator import SOAPGenerator, _SOAP_SYSTEM_PROMPT
from app.utils.i18n_messages import MESSAGES


# ── Enum 結構 ─────────────────────────────────────────────


def test_urgency_enum_has_four_values():
    assert {u.value for u in Urgency} == {"er_now", "24h", "this_week", "routine"}


def test_urgency_values_frozenset_matches():
    assert URGENCY_VALUES == frozenset({"er_now", "24h", "this_week", "routine"})


# ── i18n ──────────────────────────────────────────────────


def test_urgency_i18n_has_eight_keys():
    """4 urgency × 2 locale = 8 個 display string。"""
    required_keys = [f"soap.urgency.{u.value}" for u in Urgency]
    for key in required_keys:
        assert key in MESSAGES, f"missing i18n key: {key}"
        assert "zh-TW" in MESSAGES[key]
        assert "en-US" in MESSAGES[key]
        assert MESSAGES[key]["zh-TW"].strip()
        assert MESSAGES[key]["en-US"].strip()


def test_urgency_i18n_template_contains_boilerplate():
    """固定 boilerplate：『若有以下情況請立即就醫:』開頭。"""
    for u in Urgency:
        zh = MESSAGES[f"soap.urgency.{u.value}"]["zh-TW"]
        en = MESSAGES[f"soap.urgency.{u.value}"]["en-US"]
        assert "若有以下情況請立即就醫" in zh
        assert "Seek emergency care" in en


# ── _coerce_urgency ────────────────────────────────────────


def test_coerce_urgency_accepts_all_enum_values():
    for u in Urgency:
        assert SOAPGenerator._coerce_urgency(u.value) == u.value


def test_coerce_urgency_is_case_insensitive_and_strips():
    assert SOAPGenerator._coerce_urgency("  ER_NOW ") == "er_now"


def test_coerce_urgency_fallbacks_invalid():
    for bad in [None, "", "urgent", "緊急", "immediate", "123", 42]:
        assert SOAPGenerator._coerce_urgency(bad) == "routine"


# ── Prompt 必含 4 個 enum value ─────────────────────────────


def test_soap_prompt_lists_four_urgency_values():
    for value in ("er_now", "24h", "this_week", "routine"):
        assert value in _SOAP_SYSTEM_PROMPT


# ── SOAPGenerator.generate 整合：plan.urgency 永遠合法 ───


def _build_generator(monkeypatch) -> SOAPGenerator:
    settings = MagicMock()
    settings.OPENAI_MODEL_SOAP = "gpt-4o"
    settings.OPENAI_TEMPERATURE_SOAP = 0.3
    settings.OPENAI_MAX_TOKENS_SOAP = 4096
    monkeypatch.setattr(
        soap_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    return SOAPGenerator(settings)


def _patch_with_report(monkeypatch, generator, report_json: str):
    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = report_json
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)


def _run(coro):
    return asyncio.run(coro)


def test_generate_falls_back_urgency_when_llm_outputs_garbage(monkeypatch):
    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "cc"},
        "objective": {},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "x"},
        "plan": {
            "recommended_tests": [
                {
                    "test_name": "UA",
                    "rationale": "",
                    "urgency": "超級緊急",  # 怪值
                    "clinical_reasoning": "",
                }
            ],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
            "urgency": "immediate",  # 非 enum
        },
        "summary": "s",
        "icd10_codes": [],
        "confidence_score": 0.5,
    }
    _patch_with_report(monkeypatch, generator, json.dumps(report))

    result = _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "x"}],
            patient_info={},
            chief_complaint="x",
            language="zh-TW",
        )
    )

    # plan.urgency fallback 成 routine
    assert result["plan"]["urgency"] in URGENCY_VALUES
    assert result["plan"]["urgency"] == "routine"
    # recommended_tests.item.urgency 也 fallback
    assert result["plan"]["recommended_tests"][0]["urgency"] == "routine"


def test_generate_keeps_legitimate_urgency(monkeypatch):
    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "cc"},
        "objective": {},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "x"},
        "plan": {
            "recommended_tests": [
                {
                    "test_name": "UA",
                    "rationale": "r",
                    "urgency": "24h",
                    "clinical_reasoning": "cr",
                }
            ],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
            "urgency": "er_now",
        },
        "summary": "s",
        "icd10_codes": [],
        "confidence_score": 0.5,
    }
    _patch_with_report(monkeypatch, generator, json.dumps(report))

    result = _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "x"}],
            patient_info={},
            chief_complaint="x",
            language="zh-TW",
        )
    )

    assert result["plan"]["urgency"] == "er_now"
    assert result["plan"]["recommended_tests"][0]["urgency"] == "24h"


def test_generate_integrates_icd10_validator(monkeypatch):
    """LLM 吐非白名單碼 → 被 strip；同時 icd10_verified 回 bool。"""
    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "cc"},
        "objective": {},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "x"},
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
            "urgency": "routine",
        },
        "summary": "s",
        "icd10_codes": ["J18.9", "N39.0"],  # J18 非白名單
        "confidence_score": 0.5,
    }
    _patch_with_report(monkeypatch, generator, json.dumps(report))

    result = _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "x"}],
            patient_info={},
            chief_complaint="x",
            language="zh-TW",
            symptom_id="uti",
        )
    )

    assert result["icd10_codes"] == ["N39.0"]
    assert result["icd10_verified"] is True


def test_generate_icd10_unverified_without_symptom(monkeypatch):
    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "cc"},
        "objective": {},
        "assessment": {"differential_diagnoses": [], "clinical_impression": "x"},
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
            "urgency": "routine",
        },
        "summary": "s",
        "icd10_codes": ["N39.0"],
        "confidence_score": 0.5,
    }
    _patch_with_report(monkeypatch, generator, json.dumps(report))

    result = _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "x"}],
            patient_info={},
            chief_complaint="x",
            language="zh-TW",
            symptom_id=None,
        )
    )

    assert result["icd10_codes"] == ["N39.0"]
    assert result["icd10_verified"] is False
