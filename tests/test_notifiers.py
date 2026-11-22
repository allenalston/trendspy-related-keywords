"""Tests for local, SMTP email (465 SSL & 587 STARTTLS), and webhook notifiers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from trends_monitor.config import (
    EmailNotificationSettings,
    FeishuNotificationSettings,
    GenericWebhookSettings,
    LocalNotificationSettings,
    WeComNotificationSettings,
)
from trends_monitor.models import RisingSignal, RunReport
from trends_monitor.notifiers import (
    EmailNotifier,
    FeishuNotifier,
    GenericWebhookNotifier,
    LocalFileNotifier,
    WeComNotifier,
)


def _sample_report(tmp_path: Path) -> RunReport:
    csv_file = tmp_path / "daily_report_2026-11-22.csv"
    csv_file.write_text("keyword,related_query\nAI,claude ai\n", encoding="utf-8")
    return RunReport(
        run_id="run_test",
        run_date="2026-11-22",
        generated_at="2026-11-22T12:00:00Z",
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="",
        rising_threshold=500,
        total_keywords=1,
        succeeded_keywords=1,
        failed_keywords=0,
        new_rising=[
            RisingSignal("AI", "claude ai", 2500, is_breakout=False, is_new=True),
        ],
        csv_path=csv_file,
        output_dir=tmp_path,
    )


def test_local_file_notifier(tmp_path: Path) -> None:
    notifier = LocalFileNotifier(LocalNotificationSettings(enabled=True, formats=["markdown", "html"]), tmp_path)
    result = notifier.send(_sample_report(tmp_path))
    assert result.success is True
    assert len(result.artifacts) == 2
    assert (tmp_path / "digest_2026-11-22.md").exists()
    assert (tmp_path / "digest_2026-11-22.html").exists()


def test_email_notifier_supports_465_ssl_and_587_starttls(tmp_path: Path) -> None:
    report = _sample_report(tmp_path)

    # Port 465 -> SMTP_SSL
    ssl_settings = EmailNotificationSettings(
        enabled=True,
        smtp_server="smtp.qq.com",
        smtp_port=465,
        sender_email="me@qq.com",
        sender_password="pw",
        recipient_emails=["to@example.com"],
        attach_csv=True,
    )
    with patch("smtplib.SMTP_SSL") as mock_ssl:
        ctx = mock_ssl.return_value.__enter__.return_value
        res = EmailNotifier(ssl_settings).send(report)
        assert res.success is True
        mock_ssl.assert_called_once()
        ctx.login.assert_called_once_with("me@qq.com", "pw")
        ctx.send_message.assert_called_once()

    # Port 587 -> SMTP + starttls
    tls_settings = EmailNotificationSettings(
        enabled=True,
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        sender_email="me@gmail.com",
        sender_password="pw",
        recipient_emails=["a@example.com", "b@example.com"],
    )
    with patch("smtplib.SMTP") as mock_smtp:
        ctx = mock_smtp.return_value.__enter__.return_value
        res = EmailNotifier(tls_settings).send(report)
        assert res.success is True
        ctx.starttls.assert_called_once()
        ctx.send_message.assert_called_once()


def test_webhook_notifiers(tmp_path: Path) -> None:
    report = _sample_report(tmp_path)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b'{"code": 0, "errcode": 0}'
    fake_resp.json.return_value = {"code": 0, "errcode": 0}
    fake_resp.raise_for_status.return_value = None

    with patch("requests.post", return_value=fake_resp) as mock_post:
        r_feishu = FeishuNotifier(FeishuNotificationSettings(enabled=True, webhook_url="https://example.com/feishu")).send(report)
        r_wecom = WeComNotifier(WeComNotificationSettings(enabled=True, webhook_url="https://example.com/wecom")).send(report)
        r_generic = GenericWebhookNotifier(GenericWebhookSettings(enabled=True, url="https://example.com/hook")).send(report)

        assert r_feishu.success is True
        assert r_wecom.success is True
        assert r_generic.success is True
        assert mock_post.call_count == 3

        # Verify WeCom payload respects markdown byte limit
        wecom_call_kwargs: dict[str, Any] = mock_post.call_args_list[1].kwargs
        assert len(wecom_call_kwargs["json"]["markdown"]["content"].encode("utf-8")) <= 4096
