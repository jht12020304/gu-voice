"""Fixed clinical notification text for the inbox and both push transports."""

from app.models.enums import NotificationType
from app.utils.i18n_messages import get_message


def notification_copy(kind: str, language: str | None) -> tuple[str, str]:
    return (
        get_message(f"notifications.{kind}.title", language),
        get_message(f"notifications.{kind}.body", language),
    )


def clinical_notification_kind(kind: str | None, data: dict) -> str | None:
    if kind in (NotificationType.RED_FLAG, NotificationType.REPORT_READY, NotificationType.SESSION_COMPLETE):
        return NotificationType(kind).value
    if data.get("status") == "failed" and "session_id" in data:
        return "report_failed"
    return None


def queued_push_kind(data: dict) -> str:
    # Older Celery jobs carried only routing IDs and pre-rendered sensitive text.
    kind = clinical_notification_kind(data.get("type"), data)
    if kind:
        return kind
    if "report_id" in data:
        return "report_ready"
    if "session_id" in data:
        return "session_complete"
    return "generic"
