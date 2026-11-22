"""Tests for Trends collector, error classification, timeframe parsing, and bounded retries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests

from trends_monitor.collector import (
    TrendspyCollector,
    classify_error,
    parse_related_dataframe,
    parse_trend_value,
    resolve_timeframe,
)
from trends_monitor.config import AppConfig
from trends_monitor.models import ErrorType, KeywordStatus, QueryType


def test_resolve_timeframe() -> None:
    fixed = datetime(2026, 11, 22, 12, 0, 0)
    assert resolve_timeframe("now 7-d", now=fixed) == "now 7-d"
    assert resolve_timeframe("last-3-d", now=fixed) == "2026-11-19 2026-11-22"
    assert resolve_timeframe("last-0-d", now=fixed) == "now 7-d"


def test_parse_trend_value_variants() -> None:
    assert parse_trend_value(5250, breakout_threshold=5000) == (5250, True)
    assert parse_trend_value(850, breakout_threshold=5000) == (850, False)
    assert parse_trend_value("Breakout", breakout_threshold=5000) == (5000, True)
    assert parse_trend_value("+1,250%", breakout_threshold=5000) == (1250, False)
    assert parse_trend_value("N/A", breakout_threshold=5000) == (0, False)


def test_parse_related_dataframe_handles_empty_and_missing_columns() -> None:
    assert parse_related_dataframe(None, QueryType.RISING) == []
    assert parse_related_dataframe(pd.DataFrame(), QueryType.RISING) == []
    assert parse_related_dataframe(pd.DataFrame({"foo": [1]}), QueryType.RISING) == []

    df = pd.DataFrame({"query": ["claude ai", ""], "value": ["Breakout", 100]})
    records = parse_related_dataframe(df, QueryType.RISING, breakout_threshold=5000)
    assert len(records) == 1
    assert records[0].query == "claude ai"
    assert records[0].value == 5000
    assert records[0].is_breakout is True


def test_classify_error() -> None:
    assert classify_error(RuntimeError("API quota exceeded (429)")) == ErrorType.QUOTA_EXCEEDED
    assert classify_error(AttributeError("'NoneType' object has no attribute 'raise_for_status'")) == ErrorType.EMPTY_RESPONSE
    assert classify_error(requests.Timeout("timed out")) == ErrorType.NETWORK_ERROR
    assert classify_error(ValueError("unexpected format")) == ErrorType.UNKNOWN_ERROR


def test_collector_bounded_retries_and_recovery() -> None:
    cfg = AppConfig()
    cfg.rate_limit.max_retries = 3
    cfg.rate_limit.quota_backoff_seconds = 10.0

    calls = {"n": 0}
    sleeps: list[float] = []

    class FlakyClient:
        def related_queries(self, keyword: str, **kwargs: Any) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("API quota exceeded")
            return {
                "rising": pd.DataFrame({"query": ["ai agent"], "value": [1200]}),
                "top": pd.DataFrame({"query": ["ai"], "value": [100]}),
            }

    collector = TrendspyCollector(cfg, client_factory=FlakyClient, sleep_fn=sleeps.append)
    res = collector.fetch_keyword("AI", geo="", timeframe="now 7-d")

    assert res.status == KeywordStatus.SUCCESS
    assert res.attempts == 2
    assert len(sleeps) == 1
    assert res.rising[0].query == "ai agent"


def test_collector_stops_at_max_retries_never_infinite() -> None:
    cfg = AppConfig()
    cfg.rate_limit.max_retries = 2
    cfg.rate_limit.quota_backoff_seconds = 5.0

    sleeps: list[float] = []

    class Always429Client:
        def related_queries(self, keyword: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("HTTP 429 Too Many Requests")

    collector = TrendspyCollector(cfg, client_factory=Always429Client, sleep_fn=sleeps.append)
    res = collector.fetch_keyword("AI", geo="US", timeframe="now 7-d")

    assert res.status == KeywordStatus.FAILED
    assert res.error_type == ErrorType.QUOTA_EXCEEDED
    assert res.attempts == 2
    assert len(sleeps) == 1
