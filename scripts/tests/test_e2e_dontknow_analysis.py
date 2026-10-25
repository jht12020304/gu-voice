"""First asks and forbidden re-asks must recognize the same duration wording."""

import importlib.util
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location(
    "e2e_driver", Path(__file__).resolve().parents[1] / "e2e_realopenai/driver.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_duration_paraphrase_sets_cutoff_and_still_detects_reasks(monkeypatch):
    # Isolate transcript classification from unrelated SOAP / red-flag checks.
    for name in (
        "_soap_generated_check", "_patient_facing_wording_check",
        "_rule_layer_check", "_common_diagnostics",
    ):
        monkeypatch.setattr(driver, name, lambda *args: {})
    result = {
        "transcript": [
            {"role": "patient", "content": "頻尿", "patient_turn": 1},
            {"role": "assistant", "content": "是一直持續，還是有時候才出現？"},
            {"role": "patient", "content": "我不知道，不記得了。", "patient_turn": 2},
            {"role": "assistant", "content": "有什麼情況會讓症狀比較嚴重？"},
        ],
        "guidance_timeline": [], "completed_event": None, "patient_turns": 2,
    }
    key = "a2_no_duration_reask_after_dontknow"
    check = driver.analyze_dontknow(result, {})[key]
    assert check["first_dontknow_turn"] == 2
    assert check["status"] == driver.PASS

    result["transcript"].append({"role": "assistant", "content": "是持續性還是間歇性？"})
    check = driver.analyze_dontknow(result, {})[key]
    assert check["status"] == driver.FAIL
    assert len(check["paraphrase_reask_hits"]) == 1

    # A modifier question or words split across sentences must not create a cutoff.
    for question in ("有沒有某些時候比較嚴重？", "請持續觀察。有時候會疼痛嗎？"):
        result["transcript"] = result["transcript"][:3]
        result["transcript"][1]["content"] = question
        check = driver.analyze_dontknow(result, {})[key]
        assert check["first_dontknow_turn"] is None
        assert check["status"] == driver.PRECONDITION_NOT_MET


def test_refusal_fixture_is_reliable_but_other_answers_use_the_simulator(monkeypatch):
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="沒有發燒。"))]
    ))
    monkeypatch.setattr(driver, "AsyncOpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    ))
    patient = driver.PatientSimulator(driver.DONTKNOW_ZH_PERSONA, "synthetic")
    for question in ("什麼時候開始？", "持續多久了？", "是一直持續還是有時候才出現？"):
        reply = asyncio.run(patient.reply([{"role": "assistant", "content": question}], 1))
        assert reply == "我真的不知道，不記得了。"
    create.assert_not_called()
    reply = asyncio.run(patient.reply([{"role": "assistant", "content": "有發燒嗎？"}], 2))
    assert reply == "沒有發燒。"
    create.assert_awaited_once()
