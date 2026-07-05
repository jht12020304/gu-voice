"""
守護 raw_transcript 單一格式來源（session_data_inventory §11-5 修復）：

WS 結束路徑與 Celery 重生路徑都必須經由 format_raw_transcript 產出
`[patient] ...` / `[assistant] ...` 中性標籤格式；任何一邊 inline 重寫
（歷史上曾漂移成「病患：/AI 助手：」）都是 regression。
"""

from __future__ import annotations

import inspect

from app.utils.transcript import format_raw_transcript


def test_format_uses_neutral_role_labels():
    entries = [
        {"role": "assistant", "content": "請描述您的症狀。", "timestamp": "t0"},
        {"role": "patient", "content": "我最近血尿。", "timestamp": "t1"},
    ]
    out = format_raw_transcript(entries)
    assert out == "[assistant] 請描述您的症狀。\n[patient] 我最近血尿。"
    # 不得再出現寫死的中文角色標籤
    assert "病患：" not in out and "AI 助手：" not in out


def test_format_tolerates_missing_keys():
    assert format_raw_transcript([{}]) == "[unknown] "
    assert format_raw_transcript([]) == ""


def test_both_generation_paths_use_shared_formatter():
    """WS 與 Celery 兩條 SOAP 路徑的原始碼都必須引用 format_raw_transcript。"""
    import app.tasks.report_queue as report_queue
    import app.websocket.conversation_handler as ch

    assert "format_raw_transcript" in inspect.getsource(
        ch._generate_soap_report_async
    )
    assert "format_raw_transcript" in inspect.getsource(report_queue._async_generate)
