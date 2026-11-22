"""Consolidated SMTP email notifier supporting both SSL (465) and STARTTLS (587)."""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from trends_monitor.config import EmailNotificationSettings
from trends_monitor.models import NotifyResult, RunReport
from trends_monitor.notifiers.base import BaseNotifier
from trends_monitor.report import build_subject, render_html, render_plain_text

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """Sends a single consolidated HTML + plain-text email digest with optional CSV attachment."""

    name = "email"

    def __init__(self, settings: EmailNotificationSettings, timeout: int = 20) -> None:
        self.settings = settings
        self.timeout = timeout

    def _validate_settings(self) -> tuple[bool, str]:
        missing: list[str] = []
        if not self.settings.smtp_server:
            missing.append("smtp_server / TRENDS_SMTP_SERVER")
        if not self.settings.sender_email:
            missing.append("sender_email / TRENDS_SENDER_EMAIL")
        if not self.settings.sender_password:
            missing.append("sender_password / TRENDS_SENDER_PASSWORD")
        if not self.settings.recipient_emails:
            missing.append("recipient_emails / TRENDS_RECIPIENT_EMAIL")
        if missing:
            return False, f"Missing required email settings: {', '.join(missing)}"
        return True, "OK"

    def _build_message(self, report: RunReport) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = self.settings.sender_email
        msg["To"] = ", ".join(self.settings.recipient_emails)
        msg["Subject"] = build_subject(report)

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(render_plain_text(report), "plain", "utf-8"))
        alternative.attach(MIMEText(render_html(report), "html", "utf-8"))
        msg.attach(alternative)

        if self.settings.attach_csv and report.csv_path and Path(report.csv_path).exists():
            csv_file = Path(report.csv_path)
            part = MIMEApplication(csv_file.read_bytes(), Name=csv_file.name)
            part["Content-Disposition"] = f'attachment; filename="{csv_file.name}"'
            msg.attach(part)

        return msg

    @contextmanager
    def _open_smtp(self) -> Iterator[smtplib.SMTP]:
        if self.settings.resolved_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_server,
                self.settings.smtp_port,
                timeout=self.timeout,
            ) as server:
                server.ehlo()
                yield server
        else:
            with smtplib.SMTP(
                self.settings.smtp_server,
                self.settings.smtp_port,
                timeout=self.timeout,
            ) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                yield server

    def send(self, report: RunReport) -> NotifyResult:
        ok, err = self._validate_settings()
        if not ok:
            return NotifyResult(channel=self.name, success=False, message=err)

        try:
            msg = self._build_message(report)
            with self._open_smtp() as server:
                server.login(self.settings.sender_email, self.settings.sender_password)
                server.send_message(
                    msg,
                    from_addr=self.settings.sender_email,
                    to_addrs=self.settings.recipient_emails,
                )
            return NotifyResult(
                channel=self.name,
                success=True,
                message=(
                    f"Sent digest email to {len(self.settings.recipient_emails)} recipient(s) "
                    f"via {self.settings.smtp_server}:{self.settings.smtp_port}"
                ),
            )
        except Exception as exc:
            logger.error("Email notification failed: %s", exc)
            return NotifyResult(
                channel=self.name,
                success=False,
                message=f"SMTP send failed ({self.settings.smtp_server}:{self.settings.smtp_port}): {exc}",
            )

    def check(self) -> tuple[bool, str]:
        ok, err = self._validate_settings()
        if not ok:
            return False, err
        mode = "SSL" if self.settings.resolved_use_ssl else "STARTTLS"
        try:
            with self._open_smtp() as server:
                server.login(self.settings.sender_email, self.settings.sender_password)
                server.noop()
            return True, (
                f"SMTP login OK ({self.settings.smtp_server}:{self.settings.smtp_port}, {mode})"
            )
        except Exception as exc:
            return False, (
                f"SMTP connection/login failed ({self.settings.smtp_server}:{self.settings.smtp_port}, {mode}): {exc}"
            )
