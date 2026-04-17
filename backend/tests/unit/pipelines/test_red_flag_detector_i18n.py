"""
Phase 3-1：守護 RedFlagDetector 的 trigger_reason 依 session.language 本地化。

- rule-based 命中時：zh-TW session 拿到中文 reason，en-US session 拿到英文
- semantic layer 的 LLM system prompt 會夾帶對應語言的輸出指示
- 合併兩層時，combined trigger_reason 也走本地化模板
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector


def _run(coro):
    return asyncio.run(coro)


def _make_detector_with_rules(
    rules: list[dict[str, Any]], monkeypatch=None
) -> RedFlagDetector:
    """建一個 detector，跳過 DB 載入，用指定 rules。"""
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2

    db = MagicMock()
    # 關掉 openai client 真實建立
    fake_client = MagicMock()
    if monkeypatch is not None:
        monkeypatch.setattr(
            rfd_module, "get_openai_client", MagicMock(return_value=fake_client)
        )
    else:
        # 沒有 monkeypatch（同步測試）直接替換；測試結束不還原也無妨
        rfd_module.get_openai_client = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]

    detector = RedFlagDetector(settings, db)
    detector._rules = rules
    detector._rules_loaded = True
    return detector


def test_rule_based_trigger_reason_zh_tw():
    rules = [
        {
            "id": "r1",
            "name": "血尿",
            "severity": "high",
            "keywords": ["血尿"],
            "regex_pattern": None,
            "description": "desc",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector_with_rules(rules)
    alerts = detector._rule_based_detect("我昨天開始有血尿", language="zh-TW")
    assert len(alerts) == 1
    assert alerts[0]["trigger_reason"] == "關鍵字比對:「血尿」".replace(":", "：")


def test_rule_based_trigger_reason_en_us():
    rules = [
        {
            "id": "r1",
            "name": "Hematuria",
            "severity": "high",
            "keywords": ["hematuria"],
            "regex_pattern": None,
            "description": "desc",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector_with_rules(rules)
    alerts = detector._rule_based_detect(
        "I have had hematuria since yesterday", language="en-US"
    )
    assert len(alerts) == 1
    assert alerts[0]["trigger_reason"] == 'Keyword match: "hematuria"'


def test_rule_based_regex_reason_en_us():
    rules = [
        {
            "id": "r1",
            "name": "Fever",
            "severity": "medium",
            "keywords": [],
            "regex_pattern": r"\d{2}\.\d\s*c",
            "description": "desc",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector_with_rules(rules)
    alerts = detector._rule_based_detect(
        "my temperature is 38.5 C now", language="en-US"
    )
    assert len(alerts) == 1
    assert alerts[0]["trigger_reason"].startswith("Pattern match:")


def test_rule_based_unsupported_language_falls_back_to_default():
    rules = [
        {
            "id": "r1",
            "name": "x",
            "severity": "medium",
            "keywords": ["pain"],
            "regex_pattern": None,
            "description": "",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector_with_rules(rules)
    # fr-FR 非支援 → fallback default（預設 zh-TW）
    alerts = detector._rule_based_detect("pain", language="fr-FR")
    assert len(alerts) == 1
    # 無論 default 是 zh 或 en，至少應該是已知模板之一
    assert alerts[0]["trigger_reason"] in {
        "關鍵字比對：「pain」",
        'Keyword match: "pain"',
    }


def test_merge_combined_trigger_reason_en_us():
    rule_alerts = [
        {
            "severity": "high",
            "title": "Hematuria",
            "description": "",
            "trigger_reason": 'Keyword match: "hematuria"',
            "alert_type": "rule_based",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    semantic_alerts = [
        {
            "severity": "high",
            "title": "Hematuria",
            "description": "",
            "trigger_reason": "patient reports blood in urine",
            "alert_type": "semantic",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    merged = RedFlagDetector._merge_and_deduplicate(
        rule_alerts, semantic_alerts, language="en-US"
    )
    assert len(merged) == 1
    assert merged[0]["alert_type"] == "combined"
    assert merged[0]["trigger_reason"].startswith("[Rule]")
    assert "[Semantic]" in merged[0]["trigger_reason"]


def test_merge_combined_trigger_reason_zh_tw():
    rule_alerts = [
        {
            "severity": "high",
            "title": "血尿",
            "description": "",
            "trigger_reason": "關鍵字比對：「血尿」",
            "alert_type": "rule_based",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    semantic_alerts = [
        {
            "severity": "high",
            "title": "血尿",
            "description": "",
            "trigger_reason": "病患陳述有血塊",
            "alert_type": "semantic",
            "suggested_actions": [],
            "matched_rule_id": None,
        }
    ]
    merged = RedFlagDetector._merge_and_deduplicate(
        rule_alerts, semantic_alerts, language="zh-TW"
    )
    assert len(merged) == 1
    assert merged[0]["trigger_reason"].startswith("[規則]")
    assert "[語意]" in merged[0]["trigger_reason"]


def test_semantic_prompt_contains_language_instruction_en_us(monkeypatch):
    """
    `_semantic_detect` 應在 system prompt 尾段附上當次 session language 的輸出指示。
    mock 住 OpenAI call_with_retry，抓 system content 驗證。
    """
    detector = _make_detector_with_rules([], monkeypatch=monkeypatch)

    captured: dict[str, Any] = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"alerts": []}'
        return response

    monkeypatch.setattr(rfd_module, "call_with_retry", fake_call_with_retry)
    detector._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    _run(
        detector._semantic_detect(
            text="I have blood in urine",
            session_context={"session_id": "s1", "chief_complaint": "hematuria"},
            language="en-US",
        )
    )

    messages = captured["messages"]
    system_content = messages[0]["content"]
    assert messages[0]["role"] == "system"
    # 英文 prompt 應該包含英文輸出語言指示
    assert "Output Language" in system_content
    assert "US English" in system_content


def test_semantic_prompt_contains_language_instruction_zh_tw(monkeypatch):
    detector = _make_detector_with_rules([], monkeypatch=monkeypatch)

    captured: dict[str, Any] = {}

    async def fake_call_with_retry(fn):
        return await fn()

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"alerts": []}'
        return response

    monkeypatch.setattr(rfd_module, "call_with_retry", fake_call_with_retry)
    detector._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    _run(
        detector._semantic_detect(
            text="我有血尿",
            session_context={"session_id": "s1", "chief_complaint": "血尿"},
            language="zh-TW",
        )
    )

    system_content = captured["messages"][0]["content"]
    assert "輸出語言" in system_content
    assert "繁體中文" in system_content
