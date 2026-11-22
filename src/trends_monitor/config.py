"""Configuration loading and validation using YAML + .env + Pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


class TrendsSettings(BaseModel):
    timeframe: str = "now 7-d"
    geo: str = ""
    language: str = "en"
    proxy: str = ""

    @field_validator("geo")
    @classmethod
    def normalize_geo(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        cleaned = v.strip().lower()
        return cleaned if cleaned else "en"


class MonitorSettings(BaseModel):
    rising_threshold: int = Field(default=500, ge=0)
    breakout_threshold: int = Field(default=5000, ge=100)
    dedup_days: int = Field(default=7, ge=0)
    max_items_per_section: int = Field(default=50, ge=1)


class RateLimitSettings(BaseModel):
    min_delay_seconds: float = Field(default=5.0, ge=0.0)
    max_delay_seconds: float = Field(default=12.0, ge=0.0)
    batch_size: int = Field(default=5, ge=1)
    batch_interval_seconds: float = Field(default=60.0, ge=0.0)
    max_retries: int = Field(default=3, ge=1)
    quota_backoff_seconds: float = Field(default=60.0, ge=1.0)

    @model_validator(mode="after")
    def validate_delay_bounds(self) -> RateLimitSettings:
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("rate_limit.max_delay_seconds must be >= min_delay_seconds")
        return self


class StorageSettings(BaseModel):
    data_dir: str = "data"
    db_path: str = "data/trends_history.sqlite3"
    save_raw_json: bool = True
    save_csv: bool = True


class LocalNotificationSettings(BaseModel):
    enabled: bool = True
    formats: list[str] = Field(default_factory=lambda: ["markdown", "html"])

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, v: list[str]) -> list[str]:
        allowed = {"markdown", "html"}
        normalized = [item.strip().lower() for item in v if item.strip()]
        invalid = [item for item in normalized if item not in allowed]
        if invalid:
            raise ValueError(f"Unsupported local report formats: {invalid}. Allowed: {sorted(allowed)}")
        return normalized


class EmailNotificationSettings(BaseModel):
    enabled: bool = False
    smtp_server: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    use_ssl: bool | None = None
    sender_email: str = ""
    sender_password: str = ""
    recipient_emails: list[str] = Field(default_factory=list)
    attach_csv: bool = True

    @property
    def resolved_use_ssl(self) -> bool:
        if self.use_ssl is not None:
            return self.use_ssl
        return self.smtp_port == 465


class FeishuNotificationSettings(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class WeComNotificationSettings(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class GenericWebhookSettings(BaseModel):
    enabled: bool = False
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class NotificationSettings(BaseModel):
    local: LocalNotificationSettings = Field(default_factory=LocalNotificationSettings)
    email: EmailNotificationSettings = Field(default_factory=EmailNotificationSettings)
    feishu: FeishuNotificationSettings = Field(default_factory=FeishuNotificationSettings)
    wecom: WeComNotificationSettings = Field(default_factory=WeComNotificationSettings)
    webhook: GenericWebhookSettings = Field(default_factory=GenericWebhookSettings)


class AppConfig(BaseModel):
    keywords: list[str] = Field(default_factory=lambda: ["AI", "Image", "Video", "Music", "Voice"])
    trends: TrendsSettings = Field(default_factory=TrendsSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for kw in v:
            item = str(kw).strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)
        return cleaned


def _parse_recipients(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _apply_env_fallbacks(config: AppConfig) -> AppConfig:
    """Populate empty secret/endpoint fields from environment variables."""
    if not config.trends.proxy:
        env_proxy = os.getenv("TRENDS_PROXY", "").strip()
        if env_proxy:
            config.trends.proxy = env_proxy

    email = config.notifications.email
    if not email.smtp_server:
        email.smtp_server = os.getenv("TRENDS_SMTP_SERVER", "").strip()
    if env_port := os.getenv("TRENDS_SMTP_PORT", "").strip():
        # Only override default port if config did not explicitly specify a custom one
        # or if smtp_server was populated from env
        if email.smtp_port == 587 or not config.notifications.email.smtp_server:
            try:
                email.smtp_port = int(env_port)
            except ValueError as exc:
                raise ValueError(f"Invalid TRENDS_SMTP_PORT value: {env_port!r}") from exc
    if not email.sender_email:
        email.sender_email = os.getenv("TRENDS_SENDER_EMAIL", "").strip()
    if not email.sender_password:
        email.sender_password = os.getenv("TRENDS_SENDER_PASSWORD", "").strip()
    if not email.recipient_emails:
        env_recipients = os.getenv("TRENDS_RECIPIENT_EMAIL", "").strip()
        if env_recipients:
            email.recipient_emails = _parse_recipients(env_recipients)

    if not config.notifications.feishu.webhook_url:
        config.notifications.feishu.webhook_url = os.getenv("TRENDS_FEISHU_WEBHOOK", "").strip()

    if not config.notifications.wecom.webhook_url:
        config.notifications.wecom.webhook_url = os.getenv("TRENDS_WECOM_WEBHOOK", "").strip()

    if not config.notifications.webhook.url:
        config.notifications.webhook.url = os.getenv("TRENDS_WEBHOOK_URL", "").strip()

    return config


def load_config(
    config_path: str | Path | None = None,
    *,
    env_file: str | Path | None = ".env",
    allow_missing: bool = False,
) -> AppConfig:
    """Load configuration from YAML file and overlay `.env` environment variables."""
    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path, override=False)
    else:
        load_dotenv(override=False)

    raw_data: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
            if content is None:
                raw_data = {}
            elif not isinstance(content, dict):
                raise ValueError(f"Config file must contain a YAML mapping: {path}")
            else:
                raw_data = content
        elif not allow_missing:
            raise FileNotFoundError(
                f"Config file not found: {path}. Run `trends-monitor init` to create one."
            )

    config = AppConfig.model_validate(raw_data)
    return _apply_env_fallbacks(config)
