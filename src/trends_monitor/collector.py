"""Google Trends data collector with bounded retries, error classification, and proxy support."""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from trendspy import Trends

from trends_monitor.config import AppConfig
from trends_monitor.models import (
    ErrorType,
    KeywordCollectionResult,
    KeywordStatus,
    QueryRecord,
    QueryType,
)

logger = logging.getLogger(__name__)

DEFAULT_REFERERS = [
    "https://www.google.com/",
    "https://trends.google.com/trends/explore",
]


def resolve_timeframe(timeframe: str, now: datetime | None = None) -> str:
    """Resolve dynamic timeframe shortcuts such as `last-3-d` into Google Trends date ranges."""
    cleaned = timeframe.strip()
    match = re.fullmatch(r"last-(\d+)-d", cleaned, flags=re.IGNORECASE)
    if not match:
        return cleaned

    days = int(match.group(1))
    if days <= 0:
        logger.warning("Invalid timeframe %r (days must be > 0); falling back to 'now 7-d'", timeframe)
        return "now 7-d"

    ref = now or datetime.now()
    start = ref - timedelta(days=days)
    return f"{start.strftime('%Y-%m-%d')} {ref.strftime('%Y-%m-%d')}"


def classify_error(exc: Exception) -> ErrorType:
    """Classify collector exceptions into actionable error categories."""
    exc_name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if "quota" in exc_name or "quota exceeded" in msg or "429" in msg or "too many requests" in msg:
        return ErrorType.QUOTA_EXCEEDED

    if (
        "nonetype" in msg
        and ("raise_for_status" in msg or "subscriptable" in msg or "attribute" in msg)
    ) or "empty response" in msg:
        return ErrorType.EMPTY_RESPONSE

    if isinstance(exc, requests.RequestException) or any(
        token in msg for token in ("connection", "timeout", "proxy", "ssl", "max retries exceeded")
    ):
        return ErrorType.NETWORK_ERROR

    return ErrorType.UNKNOWN_ERROR


def parse_trend_value(raw_value: Any, breakout_threshold: int = 5000) -> tuple[int, bool]:
    """Parse a Google Trends query value (int, numeric string, '+500%', or 'Breakout')."""
    if isinstance(raw_value, bool):
        return int(raw_value), False

    if isinstance(raw_value, (int, float)):
        val = int(round(raw_value))
        return val, val >= breakout_threshold

    text = str(raw_value).strip()
    if text.lower() == "breakout":
        return breakout_threshold, True

    digits = re.sub(r"[^\d\-]", "", text)
    if digits and digits != "-":
        val = int(digits)
        return val, val >= breakout_threshold

    return 0, False


def parse_related_dataframe(
    df: Any,
    query_type: QueryType,
    breakout_threshold: int = 5000,
) -> list[QueryRecord]:
    """Safely convert a trendspy DataFrame (which may be None or empty with no columns) into records."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    if "query" not in df.columns or "value" not in df.columns:
        logger.debug("DataFrame for %s missing expected columns: %s", query_type.value, list(df.columns))
        return []

    records: list[QueryRecord] = []
    for _, row in df.iterrows():
        query_text = str(row["query"]).strip()
        if not query_text:
            continue
        value, is_breakout = parse_trend_value(row["value"], breakout_threshold=breakout_threshold)
        records.append(
            QueryRecord(
                query=query_text,
                value=value,
                query_type=query_type,
                is_breakout=is_breakout if query_type == QueryType.RISING else False,
            )
        )
    return records


class TrendsCollector(ABC):
    """Abstract interface for fetching related queries."""

    @abstractmethod
    def fetch_keyword(self, keyword: str, *, geo: str, timeframe: str) -> KeywordCollectionResult:
        """Fetch top and rising related queries for a single keyword."""


class TrendspyCollector(TrendsCollector):
    """Production collector backed by `trendspy` with bounded retries and backoff."""

    def __init__(
        self,
        config: AppConfig,
        *,
        client_factory: Callable[[], Any] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep_fn
        self._client_factory = client_factory or self._create_client
        self._client = self._client_factory()

    def _create_client(self) -> Trends:
        proxy = self.config.trends.proxy.strip() or None
        return Trends(
            language=self.config.trends.language,
            # Keep a polite delay between trendspy's internal token + widget sub-requests
            request_delay=2.0,
            max_retries=1,  # Bounded retry and backoff are controlled here
            proxy=proxy,
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "referer": random.choice(DEFAULT_REFERERS),
        }

    def fetch_keyword(self, keyword: str, *, geo: str, timeframe: str) -> KeywordCollectionResult:
        max_retries = self.config.rate_limit.max_retries
        breakout_threshold = self.config.monitor.breakout_threshold
        last_error_type = ErrorType.UNKNOWN_ERROR
        last_error_msg = ""

        for attempt in range(1, max_retries + 1):
            try:
                raw = self._client.related_queries(
                    keyword,
                    timeframe=timeframe,
                    geo=geo,
                    headers=self._build_headers(),
                )
                if raw is None or not isinstance(raw, dict):
                    raise ValueError("Empty response returned by trendspy")

                rising = parse_related_dataframe(
                    raw.get("rising"),
                    QueryType.RISING,
                    breakout_threshold=breakout_threshold,
                )
                top = parse_related_dataframe(
                    raw.get("top"),
                    QueryType.TOP,
                    breakout_threshold=breakout_threshold,
                )
                return KeywordCollectionResult(
                    keyword=keyword,
                    status=KeywordStatus.SUCCESS,
                    rising=rising,
                    top=top,
                    attempts=attempt,
                )

            except Exception as exc:
                last_error_type = classify_error(exc)
                last_error_msg = str(exc) or type(exc).__name__
                logger.warning(
                    "Keyword %r failed on attempt %d/%d [%s]: %s",
                    keyword,
                    attempt,
                    max_retries,
                    last_error_type.value,
                    last_error_msg,
                )

                if attempt < max_retries:
                    backoff = self._compute_backoff(last_error_type, attempt)
                    logger.info("Backing off %.1fs before retrying %r", backoff, keyword)
                    self._sleep(backoff)
                    # Refresh session cookies on retry
                    self._client = self._client_factory()

        return KeywordCollectionResult(
            keyword=keyword,
            status=KeywordStatus.FAILED,
            error_type=last_error_type,
            error_message=last_error_msg,
            attempts=max_retries,
        )

    def _compute_backoff(self, error_type: ErrorType, attempt: int) -> float:
        base = self.config.rate_limit.quota_backoff_seconds
        jitter = random.uniform(0.0, 5.0)
        if error_type == ErrorType.QUOTA_EXCEEDED:
            return base * (2 ** (attempt - 1)) + jitter
        if error_type == ErrorType.EMPTY_RESPONSE:
            return min(base, 15.0) * attempt + jitter
        return 5.0 * (2 ** (attempt - 1)) + jitter
