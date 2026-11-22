"""Tests for SQLite storage, cross-day deduplication, resume checkpoints, and CSV export."""

from __future__ import annotations

from pathlib import Path

from trends_monitor.models import (
    ErrorType,
    KeywordCollectionResult,
    KeywordStatus,
    QueryRecord,
    QueryType,
)
from trends_monitor.storage import SQLiteStore, sanitize_filename


def test_sanitize_filename() -> None:
    assert sanitize_filename("AI / Machine Learning?") == "AI_Machine_Learning"
    assert sanitize_filename("   ") == "keyword"


def test_cross_day_dedup_and_resurface_window(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "history.sqlite3")

    # Day 1: first time seeing "new tool ai"
    store.create_run(
        run_id="run_day1",
        run_date="2026-11-01",
        keywords=["AI"],
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="",
        rising_threshold=500,
    )
    store.record_keyword_result(
        run_id="run_day1",
        run_date="2026-11-01",
        geo="",
        timeframe="now 7-d",
        dedup_days=7,
        result=KeywordCollectionResult(
            keyword="AI",
            status=KeywordStatus.SUCCESS,
            rising=[QueryRecord("New Tool AI", 1200, QueryType.RISING, is_breakout=False)],
            top=[QueryRecord("ai", 100, QueryType.TOP)],
        ),
    )
    store.finalize_run("run_day1")
    r1 = store.build_run_report("run_day1")
    assert len(r1.new_rising) == 1
    assert len(r1.recurring_rising) == 0

    # Day 2 (within 7 days): case-insensitive match should be recurring, not new
    store.create_run(
        run_id="run_day2",
        run_date="2026-11-02",
        keywords=["AI"],
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="",
        rising_threshold=500,
    )
    store.record_keyword_result(
        run_id="run_day2",
        run_date="2026-11-02",
        geo="",
        timeframe="now 7-d",
        dedup_days=7,
        result=KeywordCollectionResult(
            keyword="AI",
            status=KeywordStatus.SUCCESS,
            rising=[
                QueryRecord("new tool ai", 1500, QueryType.RISING, is_breakout=False),
                QueryRecord("fresh breakout", 5500, QueryType.RISING, is_breakout=True),
            ],
        ),
    )
    store.finalize_run("run_day2")
    r2 = store.build_run_report("run_day2")
    assert [x.related_query for x in r2.new_rising] == ["fresh breakout"]
    assert [x.related_query for x in r2.recurring_rising] == ["new tool ai"]
    assert r2.recurring_rising[0].seen_count == 2
    assert r2.recurring_rising[0].previous_max_value == 1200

    # Day 15 (past 7-day dedup window): "new tool ai" resurfaces as New
    store.create_run(
        run_id="run_day15",
        run_date="2026-11-15",
        keywords=["AI"],
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="",
        rising_threshold=500,
    )
    store.record_keyword_result(
        run_id="run_day15",
        run_date="2026-11-15",
        geo="",
        timeframe="now 7-d",
        dedup_days=7,
        result=KeywordCollectionResult(
            keyword="AI",
            status=KeywordStatus.SUCCESS,
            rising=[QueryRecord("new tool ai", 900, QueryType.RISING)],
        ),
    )
    store.finalize_run("run_day15")
    r3 = store.build_run_report("run_day15")
    assert [x.related_query for x in r3.new_rising] == ["new tool ai"]


def test_resume_pending_keywords_and_csv_export(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "history.sqlite3")
    store.create_run(
        run_id="run_partial",
        run_date="2026-11-22",
        keywords=["AI", "Python", "Video"],
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="US",
        rising_threshold=500,
    )
    store.record_keyword_result(
        run_id="run_partial",
        run_date="2026-11-22",
        geo="US",
        timeframe="now 7-d",
        result=KeywordCollectionResult(
            keyword="AI",
            status=KeywordStatus.SUCCESS,
            rising=[QueryRecord("ai coding", 800, QueryType.RISING)],
        ),
    )
    store.record_keyword_result(
        run_id="run_partial",
        run_date="2026-11-22",
        geo="US",
        timeframe="now 7-d",
        result=KeywordCollectionResult(
            keyword="Python",
            status=KeywordStatus.FAILED,
            error_type=ErrorType.QUOTA_EXCEEDED,
            error_message="429",
        ),
    )
    status = store.finalize_run("run_partial")
    assert status == "partial"

    incomplete = store.find_latest_incomplete_run()
    assert incomplete is not None
    assert incomplete["run_id"] == "run_partial"
    assert store.get_pending_keywords("run_partial") == ["Python", "Video"]

    csv_path = store.export_run_csv("run_partial", tmp_path / "out.csv")
    assert csv_path is not None and csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "ai coding" in content

    history = store.query_history(keyword="ai", new_only=True, limit=10)
    assert len(history) == 1
    assert history[0]["related_query"] == "ai coding"
