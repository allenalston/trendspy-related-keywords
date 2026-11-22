"""Tests for YAML + .env configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from trends_monitor.config import load_config


def test_load_config_defaults_when_missing_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDS_SMTP_SERVER", raising=False)
    monkeypatch.delenv("TRENDS_SMTP_PORT", raising=False)
    monkeypatch.delenv("TRENDS_SENDER_EMAIL", raising=False)
    monkeypatch.delenv("TRENDS_SENDER_PASSWORD", raising=False)
    monkeypatch.delenv("TRENDS_RECIPIENT_EMAIL", raising=False)
    monkeypatch.delenv("TRENDS_PROXY", raising=False)

    cfg = load_config(tmp_path / "missing.yaml", env_file=None, allow_missing=True)
    assert len(cfg.keywords) > 0
    assert cfg.trends.timeframe == "now 7-d"
    assert cfg.notifications.local.enabled is True
    assert cfg.notifications.email.enabled is False


def test_load_config_missing_raises_by_default(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml", env_file=None, allow_missing=False)


def test_load_config_yaml_and_env_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
keywords:
  - " AI "
  - "Python"
  - "AI"
  - ""
trends:
  geo: " us "
  timeframe: "now 1-d"
notifications:
  email:
    enabled: true
  feishu:
    enabled: true
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRENDS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("TRENDS_SMTP_SERVER", "smtp.qq.com")
    monkeypatch.setenv("TRENDS_SMTP_PORT", "465")
    monkeypatch.setenv("TRENDS_SENDER_EMAIL", "sender@qq.com")
    monkeypatch.setenv("TRENDS_SENDER_PASSWORD", "secret")
    monkeypatch.setenv("TRENDS_RECIPIENT_EMAIL", "a@example.com, b@example.com")
    monkeypatch.setenv("TRENDS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")

    cfg = load_config(cfg_file, env_file=None)
    assert cfg.keywords == ["AI", "Python"]
    assert cfg.trends.geo == "US"
    assert cfg.trends.proxy == "http://127.0.0.1:7890"
    assert cfg.notifications.email.smtp_server == "smtp.qq.com"
    assert cfg.notifications.email.smtp_port == 465
    assert cfg.notifications.email.resolved_use_ssl is True
    assert cfg.notifications.email.recipient_emails == ["a@example.com", "b@example.com"]
    assert cfg.notifications.feishu.webhook_url.startswith("https://open.feishu.cn/")


def test_invalid_rate_limit_bounds_rejected(tmp_path: Path) -> None:
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(
        """
rate_limit:
  min_delay_seconds: 20
  max_delay_seconds: 5
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_delay_seconds"):
        load_config(cfg_file, env_file=None)
