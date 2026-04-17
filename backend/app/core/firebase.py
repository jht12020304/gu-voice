"""
Firebase Admin SDK 初始化

- 讀 `FCM_CREDENTIALS_JSON`（base64 編碼的 service account JSON）
- 應用程式啟動時呼叫一次；未設憑證只 log warning 不阻擋啟動
- 其他模組（如 `app.tasks.notification_retry`）直接 `import firebase_admin.messaging`
  無需各自初始化
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import firebase_admin
from firebase_admin import credentials

from app.core.config import settings

logger = logging.getLogger(__name__)

_initialized: bool = False


def initialize_firebase() -> Optional[firebase_admin.App]:
    """
    初始化 Firebase Admin SDK（冪等，重複呼叫安全）。

    Returns:
        初始化成功的 App，或未設憑證時回 None。
    """
    global _initialized

    if _initialized:
        return firebase_admin.get_app()

    raw = settings.FCM_CREDENTIALS_JSON
    if not raw:
        logger.warning(
            "FCM_CREDENTIALS_JSON 未設定 → Firebase 未初始化；"
            "推播通知將無法發送（本機開發可忽略）。"
        )
        return None

    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        cred_dict = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("FCM_CREDENTIALS_JSON 解碼失敗：%s", exc)
        return None

    try:
        cred = credentials.Certificate(cred_dict)
        app = firebase_admin.initialize_app(cred)
    except ValueError:
        # 已初始化過（e.g. 多 worker 熱重載）→ 直接拿現成的 app
        app = firebase_admin.get_app()
    except Exception as exc:  # noqa: BLE001
        logger.error("Firebase 初始化失敗：%s", exc)
        return None

    _initialized = True
    logger.info("Firebase Admin SDK 初始化完成 project=%s", cred_dict.get("project_id"))
    return app
