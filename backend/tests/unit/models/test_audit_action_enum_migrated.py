"""AuditAction 的 Python enum 必須與 migration 寫進 DB 的值一致。

為什麼需要這條測試：`LANGUAGE_SWITCH_END_SESSION` 被加進 `models/enums.py` 之後，
**沒有任何 migration 把它加進 DB 的 `auditaction` type**。後果是
`POST /sessions/{id}/end-for-language-switch` 只要走到寫 audit log 就 500，
而且這個端點在生產從來沒成功過——沒人發現，因為 React 只顯示「切換失敗」的 toast，
看起來像使用者操作問題而不是伺服器錯誤。

單元測試看不到「DB 現況」，但看得到「migration 檔裡有沒有出現過這個值」，
而那是唯一會讓 DB 拿到新值的途徑。新增 AuditAction 成員卻忘了寫 migration 時，這條會紅。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import AuditAction

_VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic" / "versions"


def _values_present_in_migrations() -> set[str]:
    """掃 migration 檔裡出現過的 auditaction 值（初始 schema 的列舉 + 後續 ADD VALUE）。"""
    seen: set[str] = set()
    for path in _VERSIONS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "auditaction" not in text.lower():
            continue
        seen.update(re.findall(r"'([a-z_]+)'", text))
        seen.update(re.findall(r'"([a-z_]+)"', text))
    return seen


def test_every_audit_action_value_appears_in_a_migration() -> None:
    present = _values_present_in_migrations()
    missing = [a.value for a in AuditAction if a.value not in present]
    assert not missing, (
        f"這些 AuditAction 值沒有出現在任何 migration，DB enum 不會有它們，"
        f"寫 audit log 時會 InvalidTextRepresentationError 500：{missing}。"
        f"請加一支 migration：ALTER TYPE auditaction ADD VALUE IF NOT EXISTS '<值>'"
    )
