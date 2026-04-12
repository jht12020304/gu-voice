"""
Celery 應用程式設定
- 使用 Redis 作為 broker 與 result backend
- JSON 序列化
- 時區設定為 Asia/Taipei
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# 建立 Celery app
celery_app = Celery(
    "gu_voice",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# ── 序列化設定 ────────────────────────────────────────────
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    # 任務結果保留 24 小時
    result_expires=86400,
    # 任務執行逾時 10 分鐘
    task_soft_time_limit=600,
    task_time_limit=660,
    # Worker 預取倍數（降低記憶體使用）
    worker_prefetch_multiplier=1,
)

# ── 自動發現任務 ──────────────────────────────────────────
celery_app.autodiscover_tasks([
    "app.tasks.report_queue",
    "app.tasks.notification_retry",
    "app.tasks.session_timeout",
    "app.tasks.partition_manager",
])

# ── 定時任務排程 ──────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # 每 5 分鐘檢查場次超時
    "check-session-timeouts": {
        "task": "app.tasks.session_timeout.check_session_timeouts",
        "schedule": 300.0,  # 每 5 分鐘
    },
    # 每月 25 日凌晨 3 點自動建立下月分區
    "ensure-monthly-partitions": {
        "task": "app.tasks.partition_manager.ensure_monthly_partitions",
        "schedule": crontab(hour=3, minute=0, day_of_month=25),
    },
}
