"""`_validate_session` 的 patient_info 必須走共用的 `patient_context.build_patient_info`。

過去這段組裝有兩份分岔實作：WS 這份是完整版（讀 sessions.intake_data 組出病史 /
用藥 / 過敏 / 家族史），`app/tasks/report_queue.py` 那份只給 name/gender/age，
於是 `soap_generator` 的四個病史分支在 Celery（＝生產）路徑是死碼——實測後果是
SOAP 的家族史寫「未提供」，而 intake 明載「父親：膀胱癌」。

同時鎖住搬移過程順手修掉的一個實測缺陷：WS 這份把 SQLAlchemy `Gender` enum
member 原樣放進 dict，下游 f-string 會輸出 `Gender: Gender.MALE` 而不是 `male`。
⚠️ `Gender` 是 `str, Enum`，`Gender.MALE == "male"` 為 True——**用 == 比對抓不到
這個 bug**，必須比對「渲染後」的字串。
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date
from types import SimpleNamespace
from typing import Any

import app.websocket.conversation_handler as ch
from app.models.enums import Gender


class _Result:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> Any:
        return self._obj


class _DB:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    async def execute(self, stmt: Any) -> _Result:
        return _Result(self._obj)


def _patient(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = dict(
        name="王小明",
        gender=Gender.MALE,
        date_of_birth=date(1970, 1, 1),
        user_id=None,
        medical_history=None,
        current_medications=None,
        allergies=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _session(patient: Any, intake: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        status="in_progress",
        patient=patient,
        chief_complaint=None,
        chief_complaint_text="血尿",
        intake_data=intake,
        language="zh-TW",
        doctor_id=None,
    )


def _validate(session_obj: Any) -> dict[str, Any] | None:
    return asyncio.run(ch._validate_session("11111111-1111-4111-8111-111111111111", _DB(session_obj)))


# ── gender 渲染 ────────────────────────────────────────
def test_gender_renders_as_internal_code_not_enum_repr():
    info = _validate(_session(_patient()))["patient_info"]
    assert f"Gender: {info['gender']}" == "Gender: male", (
        "gender 仍是 enum member，prompt 會寫成 `Gender: Gender.MALE`"
    )
    assert "Gender." not in f"{info['gender']}"


# ── intake 串接（Celery 那份殘缺版看不到的四類） ──────────
def test_intake_family_history_is_carried_into_patient_info():
    intake = {
        "family_history": [
            {"relation": "父親", "condition": "膀胱癌"},
            {"relation": "母親", "condition": "腎結石"},
        ]
    }
    info = _validate(_session(_patient(), intake))["patient_info"]
    assert info["family_history"] == "父親：膀胱癌、母親：腎結石"


def test_intake_four_categories_all_present():
    intake = {
        "medical_history": [{"condition": "高血壓"}],
        "current_medications": [{"medication": "Amlodipine"}],
        "allergies": [{"allergen": "Penicillin"}],
        "family_history": [{"relation": "父親", "condition": "膀胱癌"}],
    }
    info = _validate(_session(_patient(), intake))["patient_info"]
    assert info["medical_history"] == "高血壓"
    assert info["medications"] == "Amlodipine"
    assert info["allergies"] == "Penicillin"
    assert info["family_history"] == "父親：膀胱癌"


def test_no_flags_render_explicit_none_over_stale_patient_row():
    """病患本次勾了「沒有」→ 必須明寫「無」，不可 fallback 回 patients 表舊資料
    （否則 LLM 分不清「已表明沒有」與「還沒問」）。"""
    patient = _patient(
        medical_history=[{"condition": "三年前的舊資料"}],
        current_medications=[{"medication": "舊藥"}],
        allergies=[{"allergen": "舊過敏"}],
    )
    intake = {
        "no_past_medical_history": True,
        "no_current_medications": True,
        "no_known_allergies": True,
    }
    info = _validate(_session(patient, intake))["patient_info"]
    assert info["medical_history"] == "無"
    assert info["medications"] == "無"
    assert info["allergies"] == "無"


def test_intake_absent_falls_back_to_patient_row():
    patient = _patient(medical_history=[{"condition": "糖尿病"}])
    info = _validate(_session(patient, None))["patient_info"]
    assert info["medical_history"] == "糖尿病"


def test_age_zero_survives(monkeypatch):
    """今年出生 → age 為 0；不可被 truthy 判斷吃掉（回傳 dict 這層先鎖住）。"""
    patient = _patient(date_of_birth=date(date.today().year, 1, 1))
    info = _validate(_session(patient))["patient_info"]
    assert info["age"] == 0
    assert info["age"] is not None


def test_no_patient_yields_empty_patient_info():
    data = _validate(_session(None))
    assert data["patient_info"] == {}


def test_returned_keys_match_soap_generator_contract():
    """`intake_fields` 於 2026-07-27 Gate 加入（§3b 安全 gate 的來源標記）。

    扁平四欄在本次 intake 空白時會 fallback 到 patients 表的長期資料，分不出
    「這次填的」與「病歷上本來就有的」；§3b 關鍵風險因子必問不能被舊資料關掉，
    故另開一個只含本次 intake 的子 dict。語意見 test_patient_context.py。
    """
    info = _validate(_session(_patient()))["patient_info"]
    assert set(info) == {
        "name",
        "age",
        "gender",
        "medical_history",
        "medications",
        "allergies",
        "family_history",
        "intake_fields",
    }


def test_intake_fields_never_reaches_the_prompt_text():
    """`intake_fields` 是 gating 用的結構化資料，不得被渲染進任何 LLM prompt。

    supervisor / SOAP 的 prompt builder 都用具名 `.get()` 取值，多這個 key 不會
    冒出來——但這是靠慣例，值得釘住：一旦有人改成 iterate patient_info 的 keys，
    prompt 裡就會出現一段機器結構，浪費 token 又可能誤導 LLM。
    """
    from app.pipelines.supervisor import build_patient_info_str

    info = _validate(_session(_patient()))["patient_info"]
    assert "intake_fields" in info  # 前提：確實有這個 key
    assert "intake_fields" not in build_patient_info_str(info)


# ── 單一來源：本檔不可再有自己的一份組裝 ───────────────────
def test_validate_session_delegates_to_shared_builder():
    src = inspect.getsource(ch._validate_session)
    assert "build_patient_info(" in src
    assert "def format_jsonb_list" not in src, "巢狀組裝函式沒刪乾淨，又會分岔"
    assert "def format_family_history" not in src
    assert ch.build_patient_info is __import__(
        "app.pipelines.patient_context", fromlist=["build_patient_info"]
    ).build_patient_info
