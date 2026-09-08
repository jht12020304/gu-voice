import asyncio

from app.core.config import settings
from app.tasks import notification_retry
from app.tasks.notification_retry import _build_message


def test_ios_push_is_a_visible_high_priority_alert():
    message = _build_message("token", "問診完成", "報告已產生", {"type": "report_ready"})

    assert message.apns.headers == {
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-topic": "com.guvoice.guVoice",
    }
    assert message.apns.payload.aps.alert.title == "問診完成"
    assert message.apns.payload.aps.alert.body == "報告已產生"
    assert message.apns.payload.aps.sound == "default"


def test_direct_apns_sends_visible_red_flag(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return Response()

    monkeypatch.setattr(settings, "APNS_AUTH_KEY_BASE64", "a2V5")
    monkeypatch.setattr(settings, "APNS_KEY_ID", "key-id")
    monkeypatch.setattr(settings, "APNS_TEAM_ID", "team-id")
    monkeypatch.setattr(notification_retry.jwt, "encode", lambda *_, **__: "jwt")
    monkeypatch.setattr(notification_retry.httpx, "AsyncClient", lambda **_: Client())

    result = asyncio.run(
        notification_retry._send_apns(
            "apns-token",
            "紅旗警示",
            "請立即查看",
            {"type": "red_flag"},
        )
    )

    assert result == (True, False)
    assert captured["headers"]["apns-topic"] == "com.guvoice.guVoice"
    assert captured["json"]["aps"]["interruption-level"] == "time-sensitive"
