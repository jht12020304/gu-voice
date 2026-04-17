"""
Email 客戶端（P3 #31）

寄信優先順序：
1. `SENDGRID_API_KEY` 設了 → 走 SendGrid HTTP API
2. `SMTP_HOST` 設了 → 走 aiosmtplib（若套件沒裝則降級到 log）
3. 皆未設 → 只記 log（dev / CI 模式，不會阻擋流程）

DI 友善：`send_email` 可注入 `client` 替換 transport；單元測試直接餵 AsyncMock 即可。
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailClient(Protocol):
    """可注入的 email 客戶端介面。"""

    async def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        ...


class _LoggingEmailClient:
    """dev 模式：只 log，不實際寄信。"""

    async def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        logger.info(
            "[email:log-only] to=%s subject=%r body_text=%r",
            to, subject, body_text,
        )


class _SendGridClient:
    """透過 SendGrid HTTP API 寄信（v3）。"""

    def __init__(self, api_key: str, from_address: str) -> None:
        self.api_key = api_key
        self.from_address = from_address

    async def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        import httpx

        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.from_address},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
                {"type": "text/html", "value": body_html},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()


class _SmtpClient:
    """透過 aiosmtplib 寄信；aiosmtplib 未安裝就降級到 log。"""

    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        from_address: str,
        use_tls: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.use_tls = use_tls

    async def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> None:
        try:
            import aiosmtplib  # type: ignore
            from email.message import EmailMessage
        except ImportError:
            logger.warning(
                "[email:smtp] aiosmtplib 未安裝，降級為 log-only (to=%s subject=%r)",
                to, subject,
            )
            return

        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            start_tls=self.use_tls,
        )


def _build_default_client() -> EmailClient:
    """依 settings 挑選 transport；每次呼叫都重新讀設定，方便測試覆寫。"""
    if settings.SENDGRID_API_KEY:
        return _SendGridClient(
            api_key=settings.SENDGRID_API_KEY,
            from_address=settings.SMTP_FROM_ADDRESS,
        )
    if settings.SMTP_HOST:
        return _SmtpClient(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            from_address=settings.SMTP_FROM_ADDRESS,
            use_tls=settings.SMTP_USE_TLS,
        )
    return _LoggingEmailClient()


async def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: str,
    client: Optional[EmailClient] = None,
) -> None:
    """
    寄送一封 email；`client` 用來注入 fake 以利測試。

    失敗時不 raise，只 log——寄信是 best-effort，不該因 SMTP 爆掉阻斷
    `forgot_password` 的呼叫鏈（並且仍要回成功以避免洩漏帳號存在與否）。
    """
    transport: EmailClient = client or _build_default_client()
    try:
        await transport.send(to=to, subject=subject, body_html=body_html, body_text=body_text)
    except Exception:  # noqa: BLE001 — 不對呼叫端拋
        logger.exception("send_email failed | to=%s subject=%r", to, subject)
