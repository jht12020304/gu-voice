"""`control: end_session` 的 session_status 必須帶終態 `status`。

沒帶的時候：後端把場次改成 completed、SOAP 也生成了，但病患端的 session_status
handler 認不出這是終態，畫面停在對話頁——按「結束問診」看起來完全沒反應。
2026-07-27 由 Flutter simulator 真跑抓到（docs/TODO.md §V2）。

用原始碼比對而不是拉起 WS：這條契約是「呼叫點有沒有填 extra」，跑一次真連線
要 DB＋Redis＋OpenAI，換不到更多保證。
"""

import ast
import pathlib

_HANDLER = (
    pathlib.Path(__file__).resolve().parents[3]
    / "app"
    / "websocket"
    / "conversation_handler.py"
)


def _end_session_send_call() -> ast.Call:
    """找 end_session 分支裡那個 send_localized_to_session 呼叫。"""
    tree = ast.parse(_HANDLER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "send_localized_to_session"):
            continue
        codes = [
            kw.value.value
            for kw in node.keywords
            if kw.arg == "code" and isinstance(kw.value, ast.Constant)
        ]
        if codes == ["events.session.ended_by_user"]:
            return node
    raise AssertionError("找不到 end_session 的 send_localized_to_session 呼叫")


def test_ended_by_user_carries_terminal_status() -> None:
    call = _end_session_send_call()
    extra = next((kw.value for kw in call.keywords if kw.arg == "extra"), None)
    assert extra is not None, (
        "end_session 的 session_status 沒帶 extra；病患端收不到終態，"
        "按「結束問診」不會導向感謝頁"
    )
    assert isinstance(extra, ast.Dict)
    keys = [k.value for k in extra.keys if isinstance(k, ast.Constant)]
    assert "status" in keys, f"extra 缺 status（目前只有 {keys}）"

    status = next(
        v.value
        for k, v in zip(extra.keys, extra.values)
        if isinstance(k, ast.Constant) and k.value == "status" and isinstance(v, ast.Constant)
    )
    assert status == "completed", f"終態應為 completed，實際 {status!r}"
