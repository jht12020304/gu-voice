"""Gate 關卡：釘住三個「跨 agent 邊界」的接線缺陷。

這三條都是「A 產出了資料，B 沒接」的同型缺陷——每一半單獨看都是對的，
只有跨檔案讀才看得出資料掉在中間。平行修復時最容易漏，故獨立成檔：

1. `sessions.intake_data` 的 `no_family_history` 旗標
   → schema 沒這一欄時，`patient_context.build_patient_info` 的對應分支是死碼，
     家族史只分得出「有填 / 沒填」，分不出「病患明確表示沒有」。
2. `soap_generator` 的 `age` truthy 判斷
   → `calculate_age` 對今年出生的病患回 int 0，truthy 會讓整行年齡從 SOAP
     prompt 消失（嬰兒場次的 SOAP 沒有年齡）。
3. `conversation_handler` → `AlertService.create` 的 `llm_analysis`
   → 語意層產出 LLM 原判、model 與 service 都支援該欄，只有 handler 的 payload
     沒帶 → `red_flag_alerts.llm_analysis` 永遠 NULL，事後無從覆核
     「LLM 本來判什麼、被 severity floor 改成什麼」。
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.pipelines import soap_generator as soap_module
from app.pipelines.patient_context import build_patient_info
from app.pipelines.soap_generator import SOAPGenerator
from app.schemas.session import SessionIntake


# ── 1. no_family_history：schema → intake_data → build_patient_info ──────


def test_session_intake_accepts_no_family_history_flag():
    """裸 JSON（e2e driver 的送法）必須收得下這個 key，且 dump 成 snake_case。

    Pydantic 預設 ignore extra：schema 缺欄位時送這個 key **不會 422**，
    而是靜默丟掉——所以「送得出去」必須真的斷言 dump 結果，不能只看沒報錯。
    """
    dumped = SessionIntake(**{"no_family_history": True, "family_history": []}).model_dump()
    assert dumped["no_family_history"] is True


def test_session_intake_no_family_history_defaults_false():
    """兩個前端目前都沒有這個勾選框；沒送時必須等同現行行為。"""
    assert SessionIntake().model_dump()["no_family_history"] is False


def _patient() -> SimpleNamespace:
    return SimpleNamespace(
        name="X",
        gender=SimpleNamespace(value="male"),
        date_of_birth=date(1950, 4, 12),
        medical_history=None,
        current_medications=None,
        allergies=None,
    )


def test_no_family_history_flag_renders_as_explicit_none():
    """勾了「沒有家族史」→ 家族史必須是明確的「無」，不是 None。

    None 會讓 soap_generator / llm_conversation 整行不渲染，LLM 分不出
    「已表明沒有」與「還沒問」→ §3b 必問的泌尿癌家族史被重問一次。
    """
    intake = SessionIntake(**{"no_family_history": True}).model_dump()
    assert build_patient_info(_patient(), intake)["family_history"] == "無"


def test_absent_family_history_stays_none():
    """沒填也沒勾 → 維持 None（還沒問），對照組證明上一條不是恆真。"""
    intake = SessionIntake().model_dump()
    assert build_patient_info(_patient(), intake)["family_history"] is None


# ── 2. soap_generator：age == 0 不得從 prompt 消失 ────────────────────


def _build_generator(monkeypatch) -> SOAPGenerator:
    settings = MagicMock()
    settings.OPENAI_MODEL_SOAP = "gpt-4o"
    settings.OPENAI_TEMPERATURE_SOAP = 0.3
    settings.OPENAI_MAX_TOKENS_SOAP = 4096
    monkeypatch.setattr(
        soap_module, "get_openai_client", MagicMock(return_value=MagicMock())
    )
    return SOAPGenerator(settings)


def _fake_soap_json() -> str:
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


def _capture_user_prompt(monkeypatch, generator: SOAPGenerator, patient_info: dict) -> str:
    captured: dict = {}

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

    asyncio.run(
        generator.generate(
            transcript=[{"role": "patient", "content": "哭鬧"}],
            patient_info=patient_info,
            chief_complaint="血尿",
            language="zh-TW",
        )
    )
    # messages[1] = user prompt（messages[0] 是 system prompt）
    return captured["messages"][1]["content"]


def test_age_zero_reaches_soap_prompt(monkeypatch):
    """今年出生的病患（age == 0）年齡必須進 SOAP prompt。"""
    prompt = _capture_user_prompt(
        monkeypatch, _build_generator(monkeypatch), {"name": "嬰兒", "age": 0}
    )
    assert "Age: 0" in prompt


def test_age_none_still_omitted(monkeypatch):
    """沒有生日 → age is None → 整行不渲染（既有行為不得改變）。"""
    prompt = _capture_user_prompt(
        monkeypatch, _build_generator(monkeypatch), {"name": "無生日", "age": None}
    )
    assert "Age:" not in prompt


def test_calculate_age_can_actually_return_zero():
    """證明 age == 0 不是假想值：今年出生、生日已過的病患真的會拿到 0。

    沒有這一條的話，上面兩個測試只是在測一個永遠不會發生的輸入。
    """
    from app.pipelines.patient_context import calculate_age

    today = date.today()
    assert calculate_age(date(today.year, 1, 1)) == 0


# ── 3. red_flag alert 的 llm_analysis 必須真的被帶進 AlertService ──────


def test_alert_payload_carries_llm_analysis():
    """handler 組 AlertService.create payload 時必須帶 llm_analysis。

    用原始碼斷言而非行為斷言：這段在 `_handle_text_message` 深處、需要整個
    WS 迴圈才跑得到，而缺陷本身是「payload 少一個 key」的純接線問題。
    同時斷言 service 端真的會讀它，避免哪天 service 改名而 handler 這行變無效。
    """
    from app.services.alert_service import AlertService
    from app.websocket import conversation_handler as ch

    handler_src = inspect.getsource(ch)
    assert '"llm_analysis": alert.get("llm_analysis")' in handler_src, (
        "conversation_handler 的 AlertService.create payload 沒帶 llm_analysis，"
        "red_flag_alerts.llm_analysis 會永遠是 NULL"
    )
    assert 'data.get("llm_analysis")' in inspect.getsource(AlertService.create), (
        "AlertService.create 不再讀 llm_analysis，handler 那一行已失效"
    )


def test_red_flag_alert_model_has_llm_analysis_column():
    """DB 欄位存在——否則上面那條接線是接到空氣。"""
    from app.models.red_flag_alert import RedFlagAlert

    assert "llm_analysis" in RedFlagAlert.__table__.columns


def test_semantic_layer_actually_produces_llm_analysis():
    """語意層真的會產出這個 key（證明接線的上游有東西可接）。"""
    from app.pipelines import red_flag_detector as rfd

    assert '"llm_analysis"' in inspect.getsource(rfd), (
        "red_flag_detector 不再產出 llm_analysis，handler 帶的會永遠是 None"
    )
