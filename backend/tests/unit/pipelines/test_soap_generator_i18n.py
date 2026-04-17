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
