"""Core domain models for TrendSpy Related Keywords Monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class QueryType(str, Enum):
    RISING = "rising"
    TOP = "top"


class KeywordStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class ErrorType(str, Enum):
    QUOTA_EXCEEDED = "quota_exceeded"
    EMPTY_RESPONSE = "empty_response"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class QueryRecord:
    """Single related query returned by Google Trends."""

    query: str
    value: int
    query_type: QueryType
    is_breakout: bool = False


@dataclass
class KeywordCollectionResult:
    """Result of collecting related queries for a single seed keyword."""

    keyword: str
    status: KeywordStatus
    rising: list[QueryRecord] = field(default_factory=list)
    top: list[QueryRecord] = field(default_factory=list)
    error_type: ErrorType | None = None
    error_message: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class RisingSignal:
    """Enriched rising query item ready for reporting."""

    keyword: str
    related_query: str
    value: int
    is_breakout: bool
    is_new: bool
    seen_count: int = 1
    previous_max_value: int | None = None
    first_seen_date: str | None = None


@dataclass(frozen=True)
class FailedKeywordItem:
    """Failed seed keyword recorded during a run."""

    keyword: str
    error_type: str
    error_message: str


@dataclass
class RunReport:
    """Structured digest data for a single monitor run."""

    run_id: str
    run_date: str
    generated_at: str
    timeframe: str
    resolved_timeframe: str
    geo: str
    rising_threshold: int
    total_keywords: int
    succeeded_keywords: int
    failed_keywords: int
    new_rising: list[RisingSignal] = field(default_factory=list)
    recurring_rising: list[RisingSignal] = field(default_factory=list)
    failures: list[FailedKeywordItem] = field(default_factory=list)
    csv_path: Path | None = None
    output_dir: Path | None = None

    @property
    def geo_display(self) -> str:
        return self.geo if self.geo else "Worldwide"

    @property
    def total_highlighted(self) -> int:
        return len(self.new_rising) + len(self.recurring_rising)


@dataclass(frozen=True)
class NotifyResult:
    """Result returned by a single notifier channel."""

    channel: str
    success: bool
    message: str
    artifacts: list[Path] = field(default_factory=list)
