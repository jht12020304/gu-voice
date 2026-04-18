"""
WebSocket canonical code payload schema（TODO-E2）。

設計動機
--------
WS 先前多半直接送 `{message: "錄音時間過長..."}` 這類 CJK 字串；
前端無法跟隨使用者切換語言重新渲染，也難在不同 client 做本地化。

因此新增 canonical payload 契約：

    { "code": "errors.ws.audio_too_long",
      "params": {"duration": 601},
      "severity": "warning" }

- `code` 採 dot-namespaced，與前端 `i18n/locales/{lang}/ws.json` key 一對一。
- `params` 給 `i18next` `t(code, params)` 做 interpolation。
- `severity` 讓前端決定要用 toast / banner / modal 呈現。

此 schema 只描述「可本地化的訊息 body」，不取代 `ConnectionManager` 的外層信封
（`{type, id, timestamp, payload}`）；實際送出時仍包成信封後由 `send_json` 發出。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, Field

WSSeverity = Literal["info", "warning", "error", "critical"]


class WSMessage(BaseModel):
    """Canonical localizable WS 訊息 body。

    `code`、`params`、`severity` 三欄由前端 `t(code, params)` 直接消費。
    """

    code: str = Field(
        ...,
        description=(
            "Dot-namespaced 訊息代碼，與前端 ws.json 一對一。"
            "例：errors.ws.invalid_token、events.session.red_flag_triggered。"
        ),
        min_length=1,
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="給 i18next t(code, params) 的插值；值必須為可 JSON-serialize。",
    )
    severity: WSSeverity = Field(
        default="info",
        description="提示嚴重度：info / warning / error / critical。",
    )

    model_config = ConfigDict(extra="forbid")


async def send_ws_message(
    websocket: WebSocket,
    code: str,
    params: dict[str, Any] | None = None,
    severity: WSSeverity = "info",
) -> None:
    """直接送 canonical WSMessage 給單一 client（不經 ConnectionManager）。

    專用於 handshake / init / authenticate 失敗前等尚未登錄 connection 的場景。
    已登錄的 session/dashboard 推播請用 `ConnectionManager.send_localized_to_session`
    或 `ConnectionManager.broadcast_localized_dashboard`。

    Raises：
        pydantic.ValidationError：code 空 / severity 非法時。
    """
    msg = WSMessage(code=code, params=params or {}, severity=severity)
    await websocket.send_json(msg.model_dump(mode="json"))


__all__ = ["WSMessage", "WSSeverity", "send_ws_message"]
