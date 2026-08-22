"""SOAPReportResponse 的場次上下文攤平（2026-08-22）。

醫師端報告列表每列要顯示病患姓名、主訴、場次狀態與紅旗。這四個欄位在 Session 上，
report 只有 session_id，所以前端過去是「拿 20 筆報告，再對每一筆打一次
GET /sessions/{id}」——開一次列表 22 個 round trip，而且先畫出 20 行 UUID 再逐筆
補值重排。現在改由 `list_reports` eager-load `SOAPReport.session` 一起帶回來。

這裡釘住兩件會安靜壞掉的事：

1. **關聯沒載到時絕對不能碰它。** validator 若改用 `getattr(data, "session")`，
   在沒有 eager-load 的路徑（單筆 detail 端點）上就是一次 lazy load；SQLAlchemy 的
   async session 對 lazy load 直接丟 `MissingGreenlet`，也就是生產環境 500。
   本地跑同步 session 的測試看不出來，所以用 fake 明確把「碰到關聯」變成失敗。
2. **有載到時真的要攤平。** 少了這一半，前端拿到的是四個 null，會安靜退回顯示
   UUID——跟修之前一模一樣，而且沒有任何錯誤。
"""

import datetime
import uuid

import pytest

from app.models.enums import ReportStatus, ReviewStatus, SessionStatus
from app.schemas.report import SOAPReportResponse

_RELATIONSHIPS = {"session", "patient"}


class _Row:
    """ORM row 的替身。

    關聯屬性（`session` / `patient`）只有放進 `__dict__` 才讀得到——透過 `__getattr__`
    取用一律炸掉，模擬 asyncio 下 lazy load 的 `MissingGreenlet`。其餘屬性缺席時丟
    `AttributeError`，這正是未賦值的欄位在 pydantic `from_attributes` 下的行為
    （落回預設值）。
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        if name in _RELATIONSHIPS:
            raise AssertionError(
                f"validator 觸發了 {name!r} 的 lazy load——async session 下這是 MissingGreenlet"
            )
        raise AttributeError(name)


def _base():
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "status": ReportStatus.GENERATED,
        "review_status": ReviewStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }


def test_unloaded_session_relationship_is_never_touched():
    """沒 eager-load 時：四欄留 None，而且完全不去碰 `session`。"""
    report = SOAPReportResponse.model_validate(_Row(**_base()), from_attributes=True)

    assert report.patient_name is None
    assert report.chief_complaint_text is None
    assert report.session_status is None
    assert report.session_red_flag is None


def test_loaded_session_is_flattened_onto_the_report():
    row = _Row(
        session=_Row(
            patient=_Row(name="王小明"),
            chief_complaint_text="血尿三天",
            status=SessionStatus.COMPLETED,
            red_flag=True,
        ),
        **_base(),
    )

    report = SOAPReportResponse.model_validate(row, from_attributes=True)

    assert report.patient_name == "王小明"
    assert report.chief_complaint_text == "血尿三天"
    assert report.session_status is SessionStatus.COMPLETED
    assert report.session_red_flag is True


def test_session_loaded_without_patient_still_flattens_the_rest():
    """`selectinload(...).selectinload(Patient)` 只斷一半時不得整個放棄。"""
    row = _Row(
        session=_Row(
            chief_complaint_text="頻尿",
            status=SessionStatus.IN_PROGRESS,
            red_flag=False,
        ),
        **_base(),
    )

    report = SOAPReportResponse.model_validate(row, from_attributes=True)

    assert report.patient_name is None
    assert report.chief_complaint_text == "頻尿"
    assert report.session_red_flag is False


@pytest.mark.parametrize(
    "key",
    ["patient_name", "chief_complaint_text", "session_status", "session_red_flag"],
)
def test_context_fields_are_serialized(key):
    """欄位要真的出現在 JSON 裡——Flutter 端讀的是 camelCase 後的這四個 key。"""
    row = _Row(
        session=_Row(
            patient=_Row(name="李小華"),
            chief_complaint_text="排尿困難",
            status=SessionStatus.COMPLETED,
            red_flag=False,
        ),
        **_base(),
    )

    payload = SOAPReportResponse.model_validate(row, from_attributes=True).model_dump(
        mode="json"
    )

    assert key in payload


def test_dict_input_is_passed_through_untouched():
    """非 ORM 來源（測試 fixture、快取重建）不得被攤平邏輯改寫。"""
    data = {**_base(), "patient_name": "既有值"}

    report = SOAPReportResponse.model_validate(data)

    assert report.patient_name == "既有值"
    assert report.session_status is None
