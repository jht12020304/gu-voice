"""
Phase 3-1：守護 SOAPGenerator 依 session.language 在 system prompt 尾段
附加輸出語言硬性規定。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.pipelines import soap_generator as soap_module
from app.pipelines.soap_generator import SOAPGenerator


def _run(coro):
    return asyncio.run(coro)


def _build_generator(monkeypatch) -> SOAPGenerator:
    settings = MagicMock()
    settings.OPENAI_MODEL_SOAP = "gpt-4o"
    settings.OPENAI_TEMPERATURE_SOAP = 0.3
    settings.OPENAI_MAX_TOKENS_SOAP = 4096
    # 關掉 openai client 建立（不需要真 API key）
    monkeypatch.setattr(
        soap_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    return SOAPGenerator(settings)


def _fake_soap_json() -> str:
    """最小合法 SOAP JSON，讓 _validate_and_fill 不爆。"""
    import json

    return json.dumps(
        {
            "subjective": {"chief_complaint": "cc"},
            "objective": {},
            "assessment": {"differential_diagnoses": [], "clinical_impression": ""},
            "plan": {
                "recommended_tests": [],
                "treatments": [],
                "medications": [],
                "follow_up": "",
                "patient_education": [],
                "referrals": [],
                "diagnostic_reasoning": "",
            },
            "summary": "",
            "icd10_codes": [],
            "confidence_score": 0.5,
        }
    )


def _patch_call(monkeypatch, generator: SOAPGenerator) -> dict[str, Any]:
    """在 soap_module 上裝 fake call_with_retry + fake chat.completions.create。"""
    captured: dict[str, Any] = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = _fake_soap_json()
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)
    return captured


def test_soap_prompt_contains_en_language_instruction(monkeypatch):
    generator = _build_generator(monkeypatch)
    captured = _patch_call(monkeypatch, generator)

    _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "I have flank pain"}],
            patient_info={"name": "Alice", "age": 30, "gender": "female"},
            chief_complaint="flank pain",
            language="en-US",
        )
    )

    system_content = captured["messages"][0]["content"]
    assert "Output Language" in system_content
    assert "US English" in system_content


def test_soap_prompt_contains_zh_language_instruction_by_default(monkeypatch):
    generator = _build_generator(monkeypatch)
    captured = _patch_call(monkeypatch, generator)

    # language=None 應該回退到 DEFAULT_LANGUAGE（預設 zh-TW）
    _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "血尿"}],
            patient_info={},
            chief_complaint="血尿",
            language=None,
        )
    )

    system_content = captured["messages"][0]["content"]
    assert "輸出語言" in system_content
    assert "繁體中文" in system_content


def test_soap_prompt_keeps_original_clinical_rules(monkeypatch):
    """
    語言指示是疊加在原 prompt 尾段；原有臨床規則不得被覆蓋。
    """
    from app.pipelines.soap_generator import _SOAP_SYSTEM_PROMPT

    generator = _build_generator(monkeypatch)
    captured = _patch_call(monkeypatch, generator)

    _run(
        generator.generate(
            transcript=[{"role": "patient", "content": "x"}],
            patient_info={},
            chief_complaint="x",
            language="en-US",
        )
    )

    system_content = captured["messages"][0]["content"]
    # 原 prompt 的硬性條款應該都還在
    assert _SOAP_SYSTEM_PROMPT in system_content
    assert "confidence_score" in system_content


# ─────────────────────────────────────────────────────────────
# LLM 輸出語言一致性 sanity check（TODO-Item8）
# ─────────────────────────────────────────────────────────────


def _patch_call_with_report(
    monkeypatch, generator: SOAPGenerator, report_json: str
) -> None:
    """替 generator 注入一個會回傳 `report_json` 的假 OpenAI client。"""

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = report_json
        return response

    monkeypatch.setattr(soap_module, "call_with_retry", fake_call_with_retry)
    generator._client.chat.completions.create = AsyncMock(side_effect=fake_create)


def test_soap_output_zh_warns_when_en_was_requested(monkeypatch, caplog):
    """LLM 被要求英文卻回繁中 → generator 應 log warning（但仍回傳報告）。"""
    import json
    import logging

    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "flank pain"},
        "objective": {},
        "assessment": {
            "differential_diagnoses": [],
            "clinical_impression": "病患表示左側腰痛，可能為腎結石",
        },
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
        },
        "summary": "病患表示左側腰痛持續三天，伴隨血尿",
        "icd10_codes": [],
        "confidence_score": 0.5,
    }
    _patch_call_with_report(monkeypatch, generator, json.dumps(report))

    with caplog.at_level(logging.WARNING, logger="app.pipelines.soap_generator"):
        _run(
            generator.generate(
                transcript=[{"role": "patient", "content": "flank pain"}],
                patient_info={},
                chief_complaint="flank pain",
                language="en-US",
            )
        )

    mismatch_logs = [
        r for r in caplog.records if "SOAP output language mismatch" in r.getMessage()
    ]
    assert len(mismatch_logs) == 1


def test_soap_output_en_matches_en_no_warning(monkeypatch, caplog):
    """LLM 被要求英文且確實回英文 → 不應 log mismatch warning。"""
    import json
    import logging

    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "flank pain"},
        "objective": {},
        "assessment": {
            "differential_diagnoses": [],
            "clinical_impression": "Patient reports left flank pain; suspect renal calculi.",
        },
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
        },
        "summary": "Patient with three days of left flank pain and hematuria.",
        "icd10_codes": [],
        "confidence_score": 0.5,
    }
    _patch_call_with_report(monkeypatch, generator, json.dumps(report))

    with caplog.at_level(logging.WARNING, logger="app.pipelines.soap_generator"):
        _run(
            generator.generate(
                transcript=[{"role": "patient", "content": "flank pain"}],
                patient_info={},
                chief_complaint="flank pain",
                language="en-US",
            )
        )

    mismatch_logs = [
        r for r in caplog.records if "SOAP output language mismatch" in r.getMessage()
    ]
    assert mismatch_logs == []


def test_soap_output_zh_matches_zh_no_warning(monkeypatch, caplog):
    import json
    import logging

    generator = _build_generator(monkeypatch)
    report = {
        "subjective": {"chief_complaint": "血尿"},
        "objective": {},
        "assessment": {
            "differential_diagnoses": [],
            "clinical_impression": "病患主訴血尿三天，建議進一步評估泌尿系統",
        },
        "plan": {
            "recommended_tests": [],
            "treatments": [],
            "medications": [],
            "follow_up": "",
            "patient_education": [],
            "referrals": [],
            "diagnostic_reasoning": "",
        },
        "summary": "病患表示血尿持續三天，伴隨下腹痛",
        "icd10_codes": [],
        "confidence_score": 0.5,
    }
    _patch_call_with_report(monkeypatch, generator, json.dumps(report))

    with caplog.at_level(logging.WARNING, logger="app.pipelines.soap_generator"):
        _run(
            generator.generate(
                transcript=[{"role": "patient", "content": "血尿"}],
                patient_info={},
                chief_complaint="血尿",
                language="zh-TW",
            )
        )

    mismatch_logs = [
        r for r in caplog.records if "SOAP output language mismatch" in r.getMessage()
    ]
    assert mismatch_logs == []
