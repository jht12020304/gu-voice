"""iOS 直接 APNs、失敗時回退 FCM 的推播重試任務。"""

import base64
import logging
import time
from typing import NamedTuple

import firebase_admin.messaging as messaging
import httpx
import jwt

from app.core.config import settings
from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 醫療通知不分時段（2026-09-09 拍板）：醫師開專注／睡眠模式時也要亮鎖定畫面，
# 所以每一則推播都用 time-sensitive，不再只給 red_flag。
# ⚠️ 這個等級要 App 端宣告 `com.apple.developer.usernotifications.time-sensitive`
# entitlement 才會生效；沒宣告時 iOS 不會報錯，會安靜降級成一般通知。
INTERRUPTION_LEVEL = "time-sensitive"


class ApnsResult(NamedTuple):
    """APNs 直送結果。

    ``token_invalid``：token 對本 App／環境無效（BadDeviceToken、DeviceTokenNotForTopic），
    只清掉 ``apns_token``、仍要回退 FCM——可能只是憑證環境不符，不能停用裝置。
    ``unregistered``：Apple 明確回 410 Unregistered（App 已從裝置移除），
    連 FCM 都不必再打，整台裝置停用。
    """

    sent: bool
    token_invalid: bool
    unregistered: bool = False


def _build_message(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> messaging.Message:
    """建立含明確 APNs 警示的 FCM 訊息，確保 iOS 顯示系統通知。"""
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        apns=messaging.APNSConfig(
            headers={
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-topic": settings.APNS_TOPIC,
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound="default",
                    # 備援路徑要與 APNs 直送同級：firebase-admin 沒有 interruption-level
                    # 的具名參數，透過 custom_data 併進 aps 字典。
                    custom_data={"interruption-level": INTERRUPTION_LEVEL},
                )
            ),
        ),
        token=token,
    )


async def _send_apns(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> ApnsResult:
    """直接送 Apple production APNs；回傳 :class:`ApnsResult`（成功、token 失效、已解除註冊）。"""
    if not all((settings.APNS_AUTH_KEY_BASE64, settings.APNS_KEY_ID, settings.APNS_TEAM_ID)):
        return ApnsResult(False, False)

    try:
        private_key = base64.b64decode(settings.APNS_AUTH_KEY_BASE64).decode("utf-8")
        auth_token = jwt.encode(
            {"iss": settings.APNS_TEAM_ID, "iat": int(time.time())},
            private_key,
            algorithm="ES256",
            headers={"kid": settings.APNS_KEY_ID},
        )
        aps: dict = {
            "alert": {"title": title, "body": body},
            "sound": "default",
            # 不分通知種類一律 time-sensitive，理由與 entitlement 前提見
            # 檔頭 INTERRUPTION_LEVEL 的說明。
            "interruption-level": INTERRUPTION_LEVEL,
        }
        payload = {"aps": aps, **(data or {})}
        headers = {
            "authorization": f"bearer {auth_token}",
            "apns-topic": settings.APNS_TOPIC,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        async with httpx.AsyncClient(http2=True, timeout=10) as client:
            response = await client.post(
                f"https://api.push.apple.com/3/device/{token}",
                headers=headers,
                json=payload,
            )
        if response.status_code == 200:
            return ApnsResult(True, False)

        reason = response.json().get("reason", "unknown")
        logger.warning("APNs 直接推播失敗: status=%s reason=%s", response.status_code, reason)
        # Unregistered（HTTP 410）＝ Apple 明確告知 App 已從裝置移除，是唯一能推論
        # 「這台裝置不該再收推播」的理由；其餘只代表 token 對本 App／環境無效。
        unregistered = reason == "Unregistered"
        invalid = unregistered or reason in {"BadDeviceToken", "DeviceTokenNotForTopic"}
        return ApnsResult(False, invalid, unregistered)
    except Exception as exc:
        logger.warning("APNs 直接推播例外，改走 FCM: %s", exc)
        return ApnsResult(False, False)


@celery_app.task(
    name="app.tasks.notification_retry.send_push_notification_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,         # 指數退避
    retry_backoff_max=120,      # 最大退避秒數
    acks_late=True,
)
def send_push_notification_task(
    self,
    user_id: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    """
    發送推播通知任務（含重試機制）

    Args:
        user_id: 目標使用者 ID
        title: 通知標題
        body: 通知內容
        data: 附加資料

    Returns:
        發送結果字典
    """
    import asyncio

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _async_send(user_id, title, body, data)
        )
        return result
    except Exception:
        result = asyncio.run(_async_send(user_id, title, body, data))
        return result


async def _async_send(
    user_id: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    """非同步推播核心邏輯"""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.fcm_device import FCMDevice

    async with async_session_factory() as db:
        # 取得使用者所有活躍裝置 token
        result = await db.execute(
            select(FCMDevice)
            .where(FCMDevice.user_id == user_id)
            .where(FCMDevice.is_active.is_(True))
        )
        devices = result.scalars().all()

        if not devices:
            logger.info("使用者 %s 無已註冊裝置，跳過推播", user_id)
            return {"user_id": user_id, "sent": 0, "skipped": True}

        sent_count = 0
        apns_sent_count = 0
        failed_tokens: list[str] = []

        for device in devices:
            if device.apns_token:
                apns_result = await _send_apns(device.apns_token, title, body, data)
                if apns_result.sent:
                    sent_count += 1
                    apns_sent_count += 1
                    continue
                if apns_result.token_invalid:
                    device.apns_token = None
                if apns_result.unregistered:
                    # App 已從裝置移除，FCM 也不會送到；停用裝置並跳過回退。
                    device.is_active = False
                    failed_tokens.append(device.device_token)
                    logger.info(
                        "APNs 回報裝置已解除註冊，停用裝置: user=%s, device=%s",
                        user_id,
                        device.device_name,
                    )
                    continue

            try:
                messaging.send(
                    _build_message(device.device_token, title, body, data)
                )
                sent_count += 1
                logger.debug("推播成功: user=%s, device=%s", user_id, device.device_name)

            except Exception as exc:
                logger.warning(
                    "推播失敗: user=%s, token=%s, error=%s",
                    user_id,
                    device.device_token[:20],
                    exc,
                )
                failed_tokens.append(device.device_token)

                # 如果是 token 無效，標記裝置為非活躍
                exc_str = str(exc).lower()
                if "unregistered" in exc_str or "invalid" in exc_str:
                    device.is_active = False

        await db.commit()

        return {
            "user_id": user_id,
            "sent": sent_count,
            "apns_sent": apns_sent_count,
            "failed": len(failed_tokens),
        }
