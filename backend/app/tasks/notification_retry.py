"""
推播通知重試任務
- 透過 Firebase Admin SDK 發送推播
- 最多重試 3 次，指數退避
"""

import logging

import firebase_admin.messaging as messaging

from app.tasks import celery_app

logger = logging.getLogger(__name__)


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
        failed_tokens: list[str] = []

        for device in devices:
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body,
                    ),
                    data=data or {},
                    token=device.device_token,
                )
                messaging.send(message)
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
            "failed": len(failed_tokens),
        }
