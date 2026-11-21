"""Account switching must change the real push worker's recipient selection."""

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import database
from app.models.enums import DevicePlatform, UserRole
from app.models.fcm_device import FCMDevice
from app.models.user import User
from app.services.notification_service import NotificationService
from app.tasks import notification_retry
from tests.integration.conftest import requires_db, run_with_session

pytestmark = requires_db


def test_switching_ios_accounts_revokes_all_same_device_aliases(monkeypatch):
    async def scenario(db):
        key = uuid.uuid4().hex
        a = User(email=f"a-{key}@example.com", password_hash="test", name="Doctor A", role=UserRole.DOCTOR)
        b = User(email=f"b-{key}@example.com", password_hash="test", name="Doctor B", role=UserRole.DOCTOR)
        db.add_all([a, b])
        await db.flush()
        user_ids = [a.id, b.id]
        this_apns = key + "a0"
        other_apns = key + "b0"
        current = key + "-flutter-current"
        db.add_all(
            [
                FCMDevice(
                    user_id=a.id, platform=DevicePlatform.IOS,
                    apns_token=this_apns.upper(), device_token=key + "-flutter-stale",
                ),
                FCMDevice(user_id=a.id, platform=DevicePlatform.IOS, apns_token=this_apns, device_token=current),
                FCMDevice(
                    user_id=a.id, platform=DevicePlatform.IOS, apns_token=other_apns, device_token=key + "-other-device",
                ),
            ]
        )
        await db.commit()
        sent = []

        async def send_to_apns(token, title, body, data):
            sent.append(token.lower())
            return notification_retry.ApnsResult(sent=True, token_invalid=False)

        def unexpected_fcm(message):
            raise AssertionError("Successful APNs delivery should never fall back to FCM")

        monkeypatch.setattr(database, "async_session_factory", async_sessionmaker(db.bind, expire_on_commit=False))
        monkeypatch.setattr(notification_retry, "_send_apns", send_to_apns)
        monkeypatch.setattr(notification_retry.messaging, "send", unexpected_fcm)

        async def deliveries(user_id):
            sent.clear()
            await notification_retry._async_send(str(user_id), "Test", "Generic synthetic event")
            return sent.copy()

        try:
            before = await deliveries(a.id)
            assert before.count(this_apns) == 2
            assert other_apns in before

            await NotificationService.unbind_device(db, a.id, [current], this_apns)
            await db.commit()
            assert await deliveries(a.id) == [other_apns]

            await NotificationService.register_fcm_token(db, b.id, key + "-native", this_apns, DevicePlatform.IOS)
            await db.commit()
            assert await deliveries(a.id) == [other_apns]
            assert await deliveries(b.id) == [this_apns]

            await NotificationService.unbind_device(db, a.id, [], this_apns)
            await db.commit()
            assert await deliveries(b.id) == [this_apns]
        finally:
            await db.rollback()
            await db.execute(delete(FCMDevice).where(FCMDevice.user_id.in_(user_ids)))
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()

    run_with_session(scenario)
