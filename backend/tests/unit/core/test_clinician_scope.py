"""臨床帳號的可見範圍：自己負責的 ＋ 尚未指派的（kiosk 共享佇列）。

2026-09-09 生產缺陷：四位醫師（admin + license_number）被歸為臨床帳號後，
未指派場次（kiosk 的 doctor_id 恆 NULL）全部 403/404，但紅旗與 report_ready
推播仍照 fan-out 發給他們——點推播必失敗。這裡把「未指派也放行」釘住。
"""

from __future__ import annotations

import uuid

from app.core.authz import clinician_can_access_session, clinician_session_filter


def test_own_session_is_accessible():
    me = uuid.uuid4()
    assert clinician_can_access_session(me, me) is True


def test_unassigned_session_is_accessible():
    assert clinician_can_access_session(None, uuid.uuid4()) is True


def test_other_doctor_session_is_not_accessible():
    assert clinician_can_access_session(uuid.uuid4(), uuid.uuid4()) is False


def test_sql_filter_covers_own_and_unassigned():
    """SQL 版與 Python 版必須是同一條規則——兩邊走樣就是清單看得到、點進去 403。"""
    sql = str(clinician_session_filter(uuid.uuid4()).compile())
    assert "doctor_id = " in sql
    assert "doctor_id IS NULL" in sql
    assert " OR " in sql
