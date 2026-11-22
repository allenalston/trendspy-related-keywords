"""Google Trends collectors (trendspy with proxy pool + optional SerpApi provider)."""

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

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


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

    if any(token in msg for token in ("401", "403", "invalid api key", "unauthorized")):
        return ErrorType.AUTH_ERROR

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

    provider_name: str = "base"

    @abstractmethod
    def fetch_keyword(
        self,
        keyword: str,
        *,
        geo: str,
        timeframe: str,
        cat: int = 0,
    ) -> KeywordCollectionResult:
        """Fetch top and rising related queries for a single keyword."""

    def check(self) -> tuple[bool, str]:
        """Validate provider configuration without spending quota."""
        return True, f"Provider `{self.provider_name}` ready"


class TrendspyCollector(TrendsCollector):
    """Free collector backed by `trendspy` with bounded retries and proxy-pool rotation."""

    provider_name = "trendspy"

    def __init__(
        self,
        config: AppConfig,
        *,
        client_factory: Callable[[str | None], Any] | Callable[[], Any] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep_fn
        self._proxies = config.trends.resolved_proxies
        self._proxy_index = 0
        self._client_factory = client_factory
        self._client = self._instantiate_client(self._current_proxy())

    def _current_proxy(self) -> str | None:
        if not self._proxies:
            return None
        return self._proxies[self._proxy_index % len(self._proxies)]

    def _rotate_proxy(self) -> str | None:
        if len(self._proxies) > 1:
            self._proxy_index = (self._proxy_index + 1) % len(self._proxies)
            logger.info(
                "Rotated to proxy #%d/%d",
                self._proxy_index + 1,
                len(self._proxies),
            )
        return self._current_proxy()

    def _instantiate_client(self, proxy: str | None) -> Any:
        if self._client_factory is not None:
            try:
                return self._client_factory(proxy)  # type: ignore[call-arg]
            except TypeError:
                return self._client_factory()  # type: ignore[call-arg]
        return Trends(
            language=self.config.trends.language,
            # Keep a polite delay between trendspy's internal token + widget sub-requests
            request_delay=2.0,
            max_retries=1,
            proxy=proxy,
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "referer": random.choice(DEFAULT_REFERERS),
        }

    def check(self) -> tuple[bool, str]:
        proxy_info = (
            f"{len(self._proxies)} proxy endpoint(s) configured"
            if self._proxies
            else "direct connection (no proxy)"
        )
        return True, f"Provider `trendspy` ready ({proxy_info})"

    def fetch_keyword(
        self,
        keyword: str,
        *,
        geo: str,
        timeframe: str,
        cat: int = 0,
    ) -> KeywordCollectionResult:
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
                    cat=cat,
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
                    rotated_proxy = self._rotate_proxy()
                    backoff = self._compute_backoff(
                        last_error_type,
                        attempt,
                        has_proxy_pool=len(self._proxies) > 1,
                    )
                    logger.info("Backing off %.1fs before retrying %r", backoff, keyword)
                    self._sleep(backoff)
                    self._client = self._instantiate_client(rotated_proxy)

        return KeywordCollectionResult(
            keyword=keyword,
            status=KeywordStatus.FAILED,
            error_type=last_error_type,
            error_message=last_error_msg,
            attempts=max_retries,
        )

    def _compute_backoff(
        self,
        error_type: ErrorType,
        attempt: int,
        *,
        has_proxy_pool: bool = False,
    ) -> float:
        base = self.config.rate_limit.quota_backoff_seconds
        jitter = random.uniform(0.0, 5.0)
        if error_type == ErrorType.QUOTA_EXCEEDED:
            if has_proxy_pool:
                # Shorter backoff when rotating to a fresh proxy IP
                return min(base, 10.0) + jitter
            return base * (2 ** (attempt - 1)) + jitter
        if error_type == ErrorType.EMPTY_RESPONSE:
            return min(base, 15.0) * attempt + jitter
        return 5.0 * (2 ** (attempt - 1)) + jitter


class SerpApiCollector(TrendsCollector):
    """Commercial-grade Google Trends collector via SerpApi (zero Google 429 headaches)."""

    provider_name = "serpapi"

    def __init__(
        self,
        config: AppConfig,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        timeout: int = 30,
    ) -> None:
        self.config = config
        self._sleep = sleep_fn
        self.timeout = timeout

    def check(self) -> tuple[bool, str]:
        if not self.config.trends.serpapi_api_key:
            return False, "Missing SerpApi key (set trends.serpapi_api_key or TRENDS_SERPAPI_KEY)"
        return True, "Provider `serpapi` API key configured"

    def _parse_serpapi_items(
        self,
        items: Any,
        query_type: QueryType,
        breakout_threshold: int,
    ) -> list[QueryRecord]:
        if not isinstance(items, list):
            return []
        records: list[QueryRecord] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            query_text = str(entry.get("query", "")).strip()
            if not query_text:
                continue
            raw_val = entry.get("value")
            if raw_val is None or str(raw_val).strip() == "":
                raw_val = entry.get("extracted_value", 0)
            # SerpApi reports "Breakout" in `value` and may set `extracted_value: 5000`
            value, is_breakout = parse_trend_value(raw_val, breakout_threshold=breakout_threshold)
            extracted = entry.get("extracted_value")
            if isinstance(extracted, (int, float)) and extracted > value:
                value = int(round(extracted))
                if value >= breakout_threshold:
                    is_breakout = True
            records.append(
                QueryRecord(
                    query=query_text,
                    value=value,
                    query_type=query_type,
                    is_breakout=is_breakout if query_type == QueryType.RISING else False,
                )
            )
        return records

    def fetch_keyword(
        self,
        keyword: str,
        *,
        geo: str,
        timeframe: str,
        cat: int = 0,
    ) -> KeywordCollectionResult:
        api_key = self.config.trends.serpapi_api_key
        if not api_key:
            return KeywordCollectionResult(
                keyword=keyword,
                status=KeywordStatus.FAILED,
                error_type=ErrorType.AUTH_ERROR,
                error_message="Missing SerpApi key (set TRENDS_SERPAPI_KEY)",
                attempts=1,
            )

        max_retries = self.config.rate_limit.max_retries
        breakout_threshold = self.config.monitor.breakout_threshold
        params: dict[str, Any] = {
            "engine": "google_trends",
            "q": keyword,
            "data_type": "RELATED_QUERIES",
            "date": timeframe,
            "hl": self.config.trends.language,
            "api_key": api_key,
        }
        if geo:
            params["geo"] = geo
        if cat:
            params["cat"] = str(cat)

        last_error_type = ErrorType.UNKNOWN_ERROR
        last_error_msg = ""

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=self.timeout)
                if resp.status_code in (401, 403):
                    return KeywordCollectionResult(
                        keyword=keyword,
                        status=KeywordStatus.FAILED,
                        error_type=ErrorType.AUTH_ERROR,
                        error_message=f"SerpApi authentication failed (HTTP {resp.status_code})",
                        attempts=attempt,
                    )
                resp.raise_for_status()
                payload = resp.json()
                if "error" in payload:
                    err_text = str(payload["error"])
                    err_type = classify_error(RuntimeError(err_text))
                    if err_type == ErrorType.AUTH_ERROR:
                        return KeywordCollectionResult(
                            keyword=keyword,
                            status=KeywordStatus.FAILED,
                            error_type=ErrorType.AUTH_ERROR,
                            error_message=err_text,
                            attempts=attempt,
                        )
                    raise RuntimeError(err_text)

                related = payload.get("related_queries", {}) or {}
                rising = self._parse_serpapi_items(
                    related.get("rising"),
                    QueryType.RISING,
                    breakout_threshold,
                )
                top = self._parse_serpapi_items(
                    related.get("top"),
                    QueryType.TOP,
                    breakout_threshold,
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
                    "SerpApi keyword %r failed on attempt %d/%d [%s]: %s",
                    keyword,
                    attempt,
                    max_retries,
                    last_error_type.value,
                    last_error_msg,
                )
                if attempt < max_retries:
                    self._sleep(3.0 * attempt)

        return KeywordCollectionResult(
            keyword=keyword,
            status=KeywordStatus.FAILED,
            error_type=last_error_type,
            error_message=last_error_msg,
            attempts=max_retries,
        )


def build_collector(
    config: AppConfig,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> TrendsCollector:
    """Instantiate the configured TrendsCollector provider."""
    if config.trends.provider == "serpapi":
        return SerpApiCollector(config, sleep_fn=sleep_fn)
    return TrendspyCollector(config, sleep_fn=sleep_fn)
