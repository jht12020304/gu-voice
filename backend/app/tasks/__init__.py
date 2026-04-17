"""
Celery 應用程式設定
- 使用 Redis 作為 broker 與 result backend
- JSON 序列化
- 時區設定為 Asia/Taipei
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings

# 建立 Celery app
# P3 #29：broker / result 走獨立 Redis DB index（預設 1 / 2），
# 避免 cache FLUSHDB 誤清 Celery 佇列。
celery_app = Celery(
    "gu_voice",
    broker=settings.REDIS_URL_CELERY_BROKER,
    backend=settings.REDIS_URL_CELERY_RESULT,
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
    "app.tasks.audit_retention",
    "app.tasks.audio_lifecycle",
])

# ── Worker 啟動：初始化 Firebase（推播任務需要） ─────────────
@worker_process_init.connect
def _init_worker(**_: object) -> None:
    from app.core.firebase import initialize_firebase

    initialize_firebase()


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
    # 每月 1 日凌晨 4 點清理 audit_logs 超過 7 年的分區（錯開 ensure_monthly 的 25 日 03:00）
    "cleanup-audit-retention": {
        "task": "app.tasks.audit_retention.cleanup_old_audit_partitions",
        "schedule": crontab(hour=4, minute=0, day_of_month=1),
    },
    # 每月 1 日凌晨 5 點清理超過 AUDIO_RETENTION_DAYS 的音訊 blob（錯開 04:00 的 audit 任務）
    "cleanup-audio-lifecycle": {
        "task": "app.tasks.audio_lifecycle.cleanup_old_audio_files",
        "schedule": crontab(hour=5, minute=0, day_of_month=1),
    },
}
