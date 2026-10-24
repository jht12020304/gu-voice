"""`parse_cursor`：垃圾 cursor 不得進到 UUID 欄位比對（Postgres 會回 500）。"""

import uuid

from app.utils.pagination import parse_cursor


def test_valid_uuid_string_round_trips():
    value = uuid.uuid4()
    assert parse_cursor(str(value)) == value
    assert parse_cursor(value) == value


def test_garbage_and_empty_cursor_mean_no_cursor():
    assert parse_cursor("not-a-uuid") is None
    assert parse_cursor("") is None
    assert parse_cursor(None) is None
