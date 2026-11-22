"""Notification plugin registry and dispatcher."""

from __future__ import annotations

from trends_monitor.config import AppConfig
from trends_monitor.models import NotifyResult, RunReport
from trends_monitor.notifiers.base import BaseNotifier
from trends_monitor.notifiers.email import EmailNotifier
from trends_monitor.notifiers.local import LocalFileNotifier
from trends_monitor.notifiers.webhook import FeishuNotifier, GenericWebhookNotifier, WeComNotifier


def build_notifiers(config: AppConfig, *, include_local: bool = True) -> list[BaseNotifier]:
    """Instantiate all enabled notification channels based on AppConfig."""
    notifiers: list[BaseNotifier] = []
    notif = config.notifications

    if include_local and notif.local.enabled:
        notifiers.append(LocalFileNotifier(notif.local, config.storage.data_dir))
    if notif.email.enabled:
        notifiers.append(EmailNotifier(notif.email))
    if notif.feishu.enabled:
        notifiers.append(FeishuNotifier(notif.feishu))
    if notif.wecom.enabled:
        notifiers.append(WeComNotifier(notif.wecom))
    if notif.webhook.enabled:
        notifiers.append(GenericWebhookNotifier(notif.webhook))

    return notifiers


def dispatch_notifications(
    report: RunReport,
    notifiers: list[BaseNotifier],
) -> list[NotifyResult]:
    """Send a RunReport to all configured notifiers independently (one failure never blocks others)."""
    results: list[NotifyResult] = []
    for notifier in notifiers:
        results.append(notifier.send(report))
    return results


__all__ = [
    "BaseNotifier",
    "EmailNotifier",
    "FeishuNotifier",
    "GenericWebhookNotifier",
    "LocalFileNotifier",
    "WeComNotifier",
    "build_notifiers",
    "dispatch_notifications",
]
