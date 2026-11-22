"""Webhook notifiers for Feishu (Lark), WeCom (Enterprise WeChat), and generic JSON endpoints."""

from __future__ import annotations

import logging
from typing import Any

import requests

from trends_monitor.config import (
    FeishuNotificationSettings,
    GenericWebhookSettings,
    WeComNotificationSettings,
)
from trends_monitor.models import NotifyResult, RunReport
from trends_monitor.notifiers.base import BaseNotifier
from trends_monitor.report import build_subject, format_growth, trends_explore_url

logger = logging.getLogger(__name__)


def _build_compact_markdown(report: RunReport, *, max_items: int = 15, max_bytes: int = 3800) -> str:
    """Build a concise Markdown summary suitable for chat bots with message size limits."""
    lines = [
        f"### {build_subject(report)}",
        f"- **Timeframe**: `{report.timeframe}` | **Region**: `{report.geo_display}`",
        f"- **Keywords**: {report.succeeded_keywords}/{report.total_keywords} succeeded ({report.failed_keywords} failed)",
        f"- **Signals**: **{len(report.new_rising)}** New / {len(report.recurring_rising)} Recurring (>= +{report.rising_threshold}%)",
        "",
    ]

    if report.new_rising:
        lines.append("**✨ New Rising Queries**")
        for item in report.new_rising[:max_items]:
            url = trends_explore_url(item.related_query, report.geo)
            lines.append(f"- `{item.keyword}` → [{item.related_query}]({url}) (**{format_growth(item)}**)")
        if len(report.new_rising) > max_items:
            lines.append(f"- _...and {len(report.new_rising) - max_items} more new signals_")
        lines.append("")
    else:
        lines.append("_No newly discovered rising queries exceeded the threshold._\n")

    if report.recurring_rising:
        top_rec = report.recurring_rising[: min(5, max_items)]
        lines.append("**📈 Top Recurring Rising**")
        for item in top_rec:
            lines.append(
                f"- `{item.keyword}` → {item.related_query} ({format_growth(item)}, seen {item.seen_count}x)"
            )
        lines.append("")

    if report.failures:
        lines.append(f"**⚠️ Failed Keywords ({len(report.failures)})**")
        for fail in report.failures[:5]:
            lines.append(f"- `{fail.keyword}`: `{fail.error_type}`")
        if len(report.failures) > 5:
            lines.append(f"- _...and {len(report.failures) - 5} more failures_")

    text = "\n".join(lines).strip()
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    # Gracefully truncate on UTF-8 boundary
    suffix = "\n\n_(truncated)_"
    budget = max_bytes - len(suffix.encode("utf-8"))
    truncated = encoded[:budget].decode("utf-8", errors="ignore").rstrip()
    return truncated + suffix


class FeishuNotifier(BaseNotifier):
    """Feishu / Lark custom bot webhook notifier using an interactive card."""

    name = "feishu"

    def __init__(self, settings: FeishuNotificationSettings, timeout: int = 15) -> None:
        self.settings = settings
        self.timeout = timeout

    def send(self, report: RunReport) -> NotifyResult:
        if not self.settings.webhook_url:
            return NotifyResult(
                channel=self.name,
                success=False,
                message="Missing Feishu webhook_url / TRENDS_FEISHU_WEBHOOK",
            )

        content = _build_compact_markdown(report, max_items=15, max_bytes=12000)
        payload: dict[str, Any] = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": build_subject(report)},
                    "template": "blue" if report.failed_keywords == 0 else "orange",
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "Rising % is a relative Google Trends signal. 'New' = first seen by this monitor.",
                            }
                        ],
                    },
                ],
            },
        }
        try:
            resp = requests.post(self.settings.webhook_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            code = data.get("code", data.get("StatusCode", 0))
            if code != 0:
                return NotifyResult(
                    channel=self.name,
                    success=False,
                    message=f"Feishu API error (code={code}): {data.get('msg', data)}",
                )
            return NotifyResult(channel=self.name, success=True, message="Sent Feishu card digest")
        except Exception as exc:
            logger.error("Feishu notification failed: %s", exc)
            return NotifyResult(channel=self.name, success=False, message=f"Feishu webhook failed: {exc}")

    def check(self) -> tuple[bool, str]:
        url = self.settings.webhook_url
        if not url:
            return False, "Missing webhook_url / TRENDS_FEISHU_WEBHOOK"
        if not url.startswith(("https://", "http://")):
            return False, f"Invalid Feishu webhook URL: {url}"
        return True, "Feishu webhook URL configured"


class WeComNotifier(BaseNotifier):
    """WeCom (Enterprise WeChat) group bot webhook notifier."""

    name = "wecom"

    def __init__(self, settings: WeComNotificationSettings, timeout: int = 15) -> None:
        self.settings = settings
        self.timeout = timeout

    def send(self, report: RunReport) -> NotifyResult:
        if not self.settings.webhook_url:
            return NotifyResult(
                channel=self.name,
                success=False,
                message="Missing WeCom webhook_url / TRENDS_WECOM_WEBHOOK",
            )

        # WeCom markdown limit is 4096 bytes
        content = _build_compact_markdown(report, max_items=12, max_bytes=3900)
        payload = {"msgtype": "markdown", "markdown": {"content": content}}

        try:
            resp = requests.post(self.settings.webhook_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            errcode = data.get("errcode", 0)
            if errcode != 0:
                return NotifyResult(
                    channel=self.name,
                    success=False,
                    message=f"WeCom API error (errcode={errcode}): {data.get('errmsg', data)}",
                )
            return NotifyResult(channel=self.name, success=True, message="Sent WeCom markdown digest")
        except Exception as exc:
            logger.error("WeCom notification failed: %s", exc)
            return NotifyResult(channel=self.name, success=False, message=f"WeCom webhook failed: {exc}")

    def check(self) -> tuple[bool, str]:
        url = self.settings.webhook_url
        if not url:
            return False, "Missing webhook_url / TRENDS_WECOM_WEBHOOK"
        if not url.startswith(("https://", "http://")):
            return False, f"Invalid WeCom webhook URL: {url}"
        return True, "WeCom webhook URL configured"


class GenericWebhookNotifier(BaseNotifier):
    """Generic JSON POST webhook notifier for n8n, Zapier, Slack/Discord bridges, etc."""

    name = "webhook"

    def __init__(self, settings: GenericWebhookSettings, timeout: int = 15) -> None:
        self.settings = settings
        self.timeout = timeout

    def send(self, report: RunReport) -> NotifyResult:
        if not self.settings.url:
            return NotifyResult(
                channel=self.name,
                success=False,
                message="Missing webhook url / TRENDS_WEBHOOK_URL",
            )

        payload: dict[str, Any] = {
            "subject": build_subject(report),
            "run_id": report.run_id,
            "run_date": report.run_date,
            "generated_at": report.generated_at,
            "timeframe": report.timeframe,
            "resolved_timeframe": report.resolved_timeframe,
            "geo": report.geo,
            "rising_threshold": report.rising_threshold,
            "summary": {
                "total_keywords": report.total_keywords,
                "succeeded_keywords": report.succeeded_keywords,
                "failed_keywords": report.failed_keywords,
                "new_rising_count": len(report.new_rising),
                "recurring_rising_count": len(report.recurring_rising),
            },
            "new_rising": [
                {
                    "keyword": item.keyword,
                    "related_query": item.related_query,
                    "value": item.value,
                    "is_breakout": item.is_breakout,
                    "explore_url": trends_explore_url(item.related_query, report.geo),
                }
                for item in report.new_rising
            ],
            "recurring_rising": [
                {
                    "keyword": item.keyword,
                    "related_query": item.related_query,
                    "value": item.value,
                    "is_breakout": item.is_breakout,
                    "seen_count": item.seen_count,
                    "previous_max_value": item.previous_max_value,
                    "first_seen_date": item.first_seen_date,
                }
                for item in report.recurring_rising
            ],
            "failures": [
                {
                    "keyword": fail.keyword,
                    "error_type": fail.error_type,
                    "error_message": fail.error_message,
                }
                for fail in report.failures
            ],
        }
        try:
            resp = requests.post(
                self.settings.url,
                json=payload,
                headers=self.settings.headers or None,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return NotifyResult(
                channel=self.name,
                success=True,
                message=f"POST {self.settings.url} succeeded (HTTP {resp.status_code})",
            )
        except Exception as exc:
            logger.error("Generic webhook failed: %s", exc)
            return NotifyResult(channel=self.name, success=False, message=f"Webhook POST failed: {exc}")

    def check(self) -> tuple[bool, str]:
        url = self.settings.url
        if not url:
            return False, "Missing url / TRENDS_WEBHOOK_URL"
        if not url.startswith(("https://", "http://")):
            return False, f"Invalid webhook URL: {url}"
        return True, f"Generic webhook URL configured ({url})"
