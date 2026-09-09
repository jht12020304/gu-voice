import asyncio
import types
import uuid

import pytest
from firebase_admin import _messaging_encoder

from app.core.config import settings
from app.tasks import notification_retry
from app.tasks.notification_retry import _build_message


def _stub_apns_transport(monkeypatch, *, status_code=200, reason=None):
    """把 APNs HTTP 往返換成替身；回傳記錄請求內容的 dict。"""
    captured: dict = {}

    class Response:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return {"reason": reason} if reason else {}

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
    return captured


def _stub_devices(monkeypatch, devices):
    """把 `_async_send` 用到的 DB 會話換成只回傳指定裝置的替身。"""
    import app.core.database as database

    class Result:
        def scalars(self):
            return self

        def all(self):
            return devices

    class Session:
        def __init__(self):
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, _stmt):
            return Result()

        async def commit(self):
            self.committed = True

    monkeypatch.setattr(database, "async_session_factory", lambda: Session())


def _device(**overrides):
    device = types.SimpleNamespace(
        apns_token="apns-token",
        device_token="fcm-token",
        device_name="醫師 iPhone",
        is_active=True,
    )
    for key, value in overrides.items():
        setattr(device, key, value)
    return device


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


def test_fcm_fallback_carries_time_sensitive_interruption_level():
    """備援路徑要與 APNs 直送同級，否則專注模式下會被靜音。"""
    message = _build_message("token", "問診完成", "報告已產生", {"type": "report_ready"})

    assert message.apns.payload.aps.custom_data == {"interruption-level": "time-sensitive"}
    # custom_data 是併進 aps 字典送上線的，這裡用真正的編碼器確認落點。
    encoded = _messaging_encoder.MessageEncoder().default(message)
    assert encoded["apns"]["payload"]["aps"]["interruption-level"] == "time-sensitive"


def test_direct_apns_sends_visible_red_flag(monkeypatch):
    captured = _stub_apns_transport(monkeypatch)

    result = asyncio.run(
        notification_retry._send_apns(
            "apns-token",
            "紅旗警示",
            "請立即查看",
            {"type": "red_flag"},
        )
    )

    assert result == (True, False, False)
    assert result.sent is True
    assert captured["headers"]["apns-topic"] == "com.guvoice.guVoice"
    assert captured["json"]["aps"]["interruption-level"] == "time-sensitive"


@pytest.mark.parametrize(
    "data",
    [
        {"type": "red_flag"},
        {"type": "session_complete"},
        {"type": "report_ready"},
        {"type": "report_failed"},
        {"session_id": "abc"},  # 沒有 type
        None,
    ],
)
def test_every_notification_type_is_time_sensitive(monkeypatch, data):
    """醫療通知不分時段（2026-09-09 拍板）：四類通知都要能亮鎖定畫面。"""
    captured = _stub_apns_transport(monkeypatch)

    result = asyncio.run(
        notification_retry._send_apns("apns-token", "標題", "內容", data)
    )

    assert result.sent is True
    assert captured["json"]["aps"]["interruption-level"] == "time-sensitive"


def test_direct_apns_payload_carries_gcm_message_id(monkeypatch):
    """firebase_messaging iOS plugin 靠頂層 `gcm.message_id` 才把「點了通知」轉給 Dart。"""
    captured = _stub_apns_transport(monkeypatch)

    result = asyncio.run(
        notification_retry._send_apns(
            "apns-token",
            "報告完成",
            "請查看",
            {"type": "report_ready", "session_id": "abc"},
        )
    )

    assert result.sent is True
    message_id = captured["json"]["gcm.message_id"]
    assert isinstance(message_id, str)
    uuid.UUID(message_id)  # 合法 UUID，否則拋 ValueError


def test_gcm_message_id_is_unique_per_notification(monkeypatch):
    """每則通知要有自己的 id；plugin 用它配對 `getInitialMessage`。"""
    captured = _stub_apns_transport(monkeypatch)

    asyncio.run(notification_retry._send_apns("apns-token", "標題", "內容", None))
    first = captured["json"]["gcm.message_id"]
    asyncio.run(notification_retry._send_apns("apns-token", "標題", "內容", None))
    second = captured["json"]["gcm.message_id"]

    assert first != second


def test_gcm_message_id_is_top_level_not_inside_aps(monkeypatch):
    """位置要與 FCM 送到 APNs 時一致：`aps` 之外的頂層。"""
    captured = _stub_apns_transport(monkeypatch)

    asyncio.run(notification_retry._send_apns("apns-token", "標題", "內容", None))

    payload = captured["json"]
    assert "gcm.message_id" in payload
    assert "gcm.message_id" not in payload["aps"]


def test_gcm_message_id_not_overridden_by_caller_data(monkeypatch):
    """呼叫端 data 裡的同名 key 不能蓋掉後端產生的 id。"""
    captured = _stub_apns_transport(monkeypatch)

    asyncio.run(
        notification_retry._send_apns(
            "apns-token", "標題", "內容", {"gcm.message_id": "not-a-uuid"}
        )
    )

    message_id = captured["json"]["gcm.message_id"]
    assert message_id != "not-a-uuid"
    uuid.UUID(message_id)


def test_unregistered_deactivates_device_and_skips_fcm(monkeypatch):
    """410 Unregistered＝App 已被移除，FCM 也送不到，直接停用裝置。"""
    _stub_apns_transport(monkeypatch, status_code=410, reason="Unregistered")
    device = _device()
    _stub_devices(monkeypatch, [device])

    sent_messages = []
    monkeypatch.setattr(
        notification_retry.messaging, "send", lambda message: sent_messages.append(message)
    )

    result = asyncio.run(notification_retry._async_send("user-1", "標題", "內容", None))

    assert device.is_active is False
    assert device.apns_token is None
    assert sent_messages == []  # 不回退 FCM
    assert result["sent"] == 0
    assert result["failed"] == 1


def test_bad_device_token_clears_token_but_keeps_device_and_falls_back(monkeypatch):
    """BadDeviceToken 可能只是憑證環境不符，不能停用裝置，仍要回退 FCM。"""
    _stub_apns_transport(monkeypatch, status_code=400, reason="BadDeviceToken")
    device = _device()
    _stub_devices(monkeypatch, [device])

    sent_messages = []
    monkeypatch.setattr(
        notification_retry.messaging, "send", lambda message: sent_messages.append(message)
    )

    result = asyncio.run(notification_retry._async_send("user-1", "標題", "內容", None))

    assert device.apns_token is None
    assert device.is_active is True
    assert len(sent_messages) == 1
    assert sent_messages[0].token == "fcm-token"
    assert result["sent"] == 1
    assert result["apns_sent"] == 0
