"""Tests for Markdown, HTML, and plain-text report rendering."""

from __future__ import annotations

from trends_monitor.models import FailedKeywordItem, RisingSignal, RunReport
from trends_monitor.report import build_subject, render_html, render_markdown, render_plain_text


def _sample_report() -> RunReport:
    return RunReport(
        run_id="20261122_120000_abc123",
        run_date="2026-11-22",
        generated_at="2026-11-22T12:00:00Z",
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="US",
        rising_threshold=500,
        total_keywords=3,
        succeeded_keywords=2,
        failed_keywords=1,
        new_rising=[
            RisingSignal(
                keyword="AI",
                related_query="new <script> ai",
                value=6200,
                is_breakout=True,
                is_new=True,
            )
        ],
        recurring_rising=[
            RisingSignal(
                keyword="Python",
                related_query="python 3.14",
                value=850,
                is_breakout=False,
                is_new=False,
                seen_count=3,
                previous_max_value=900,
                first_seen_date="2026-11-18",
            )
        ],
        failures=[
            FailedKeywordItem(
                keyword="Video",
                error_type="quota_exceeded",
                error_message="429 Too Many Requests",
            )
        ],
    )


def test_report_rendering_formats() -> None:
    report = _sample_report()

    subject = build_subject(report)
    assert "2026-11-22" in subject
    assert "1 New Rising" in subject
    assert "1 Failed" in subject

    md = render_markdown(report)
    assert "Breakout (+6,200%)" in md
    assert "python 3.14" in md
    assert "quota_exceeded" in md

    text = render_plain_text(report)
    assert "NEW RISING QUERIES (1)" in text
    assert "FAILED KEYWORDS (1)" in text

    html_doc = render_html(report)
    assert "BREAKOUT" in html_doc
    # Ensure untrusted query strings are HTML-escaped
    assert "<script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
