"""Tests for v0.3.0 features: presets, per-keyword cat/geo, filters, streaks, proxy pool, SerpApi, sharding, and DB migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner

from trends_monitor.cli import main
from trends_monitor.collector import SerpApiCollector, TrendsCollector, TrendspyCollector
from trends_monitor.config import AppConfig, FilterSettings, KeywordSpec, load_config
from trends_monitor.filters import QueryFilter
from trends_monitor.models import (
    ErrorType,
    KeywordCollectionResult,
    KeywordStatus,
    QueryRecord,
    QueryType,
    RisingSignal,
    RunReport,
)
from trends_monitor.presets import PRESETS
from trends_monitor.report import render_html, render_markdown
from trends_monitor.runner import TrendsMonitorRunner
from trends_monitor.storage import SQLiteStore


def test_all_presets_load_and_validate(tmp_path: Path) -> None:
    for name, preset in PRESETS.items():
        cfg_file = tmp_path / f"{name}.yaml"
        cfg_file.write_text(preset.yaml_content, encoding="utf-8")
        cfg = load_config(cfg_file, env_file=None)
        assert len(cfg.get_keyword_specs()) >= 5


def test_per_keyword_specs_and_proxy_pool_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
keywords:
  - "generator"
  - keyword: "Python"
    cat: 31
    geo: "us"
    timeframe: "now 1-d"
trends:
  provider: "serpapi"
filters:
  min_word_count: 2
  exclude_patterns:
    - "\\\\bdown\\\\b"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRENDS_PROXIES", "http://p1:8080, http://p2:8080")
    monkeypatch.setenv("TRENDS_SERPAPI_KEY", "test_serp_key")

    cfg = load_config(cfg_file, env_file=None)
    specs = cfg.get_keyword_specs()
    assert len(specs) == 2
    assert specs[0] == KeywordSpec(keyword="generator")
    assert specs[1] == KeywordSpec(keyword="Python", cat=31, geo="US", timeframe="now 1-d")
    assert cfg.trends.resolved_proxies == ["http://p1:8080", "http://p2:8080"]
    assert cfg.trends.provider == "serpapi"
    assert cfg.trends.serpapi_api_key == "test_serp_key"


def test_invalid_filter_regex_rejected(tmp_path: Path) -> None:
    cfg_file = tmp_path / "bad_regex.yaml"
    cfg_file.write_text("filters:\n  exclude_patterns: ['[unclosed']\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid regex"):
        load_config(cfg_file, env_file=None)


def test_query_filter_rules() -> None:
    qf = QueryFilter(
        FilterSettings(
            min_word_count=2,
            exclude_patterns=[r"\bdown\b", r"\blogin\b"],
            include_patterns=[r"generator|tool|ai"],
        )
    )
    assert qf.matches("free ai generator") is True
    assert qf.matches("generator") is False  # only 1 word
    assert qf.matches("janitor ai down") is False  # excluded
    assert qf.matches("python boots") is False  # does not match include_patterns


def test_proxy_pool_rotates_on_429() -> None:
    cfg = AppConfig()
    cfg.trends.proxies = ["http://proxy1:8080", "http://proxy2:8080"]
    cfg.rate_limit.max_retries = 3
    cfg.rate_limit.quota_backoff_seconds = 5.0

    used_proxies: list[str | None] = []

    class ProxyTrackingClient:
        def __init__(self, proxy: str | None) -> None:
            self.proxy = proxy
            used_proxies.append(proxy)

        def related_queries(self, keyword: str, **kwargs: Any) -> dict[str, Any]:
            if self.proxy == "http://proxy1:8080":
                raise RuntimeError("429 Too Many Requests")
            return {
                "rising": pd.DataFrame({"query": ["ai tool"], "value": [900]}),
                "top": pd.DataFrame({"query": ["ai"], "value": [100]}),
            }

    collector = TrendspyCollector(
        cfg,
        client_factory=ProxyTrackingClient,
        sleep_fn=lambda _: None,
    )
    res = collector.fetch_keyword("AI", geo="US", timeframe="now 7-d", cat=5)
    assert res.status == KeywordStatus.SUCCESS
    assert used_proxies == ["http://proxy1:8080", "http://proxy2:8080"]


def test_serpapi_collector_success_and_auth_fail_fast() -> None:
    cfg = AppConfig()
    cfg.trends.provider = "serpapi"
    cfg.trends.serpapi_api_key = "valid_key"
    cfg.rate_limit.max_retries = 3

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = {
        "related_queries": {
            "rising": [
                {"query": "ai code generator", "value": "Breakout", "extracted_value": 5000},
                {"query": "resume tool", "value": "+850%", "extracted_value": 850},
            ],
            "top": [{"query": "generator", "value": "100", "extracted_value": 100}],
        }
    }

    with patch("requests.get", return_value=fake_resp) as mock_get:
        res = SerpApiCollector(cfg, sleep_fn=lambda _: None).fetch_keyword(
            "generator", geo="US", timeframe="now 7-d", cat=31
        )
        assert res.status == KeywordStatus.SUCCESS
        assert len(res.rising) == 2
        assert res.rising[0].is_breakout is True
        assert res.rising[0].value == 5000
        assert mock_get.call_args.kwargs["params"]["cat"] == "31"

    # HTTP 401 should fail immediately on attempt 1 without retrying
    unauth_resp = MagicMock()
    unauth_resp.status_code = 401
    with patch("requests.get", return_value=unauth_resp) as mock_get_401:
        res_401 = SerpApiCollector(cfg, sleep_fn=lambda _: None).fetch_keyword(
            "generator", geo="US", timeframe="now 7-d"
        )
        assert res_401.status == KeywordStatus.FAILED
        assert res_401.error_type == ErrorType.AUTH_ERROR
        assert res_401.attempts == 1
        assert mock_get_401.call_count == 1


def test_streak_and_acceleration_across_consecutive_days(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "streak.sqlite3")

    for day, run_id, val in [
        ("2026-11-20", "r1", 600),
        ("2026-11-21", "r2", 1400),
        ("2026-11-22", "r3", 2800),
    ]:
        store.create_run(
            run_id=run_id,
            run_date=day,
            keywords=["generator"],
            timeframe="now 7-d",
            resolved_timeframe="now 7-d",
            geo="US",
            rising_threshold=500,
        )
        store.record_keyword_result(
            run_id=run_id,
            run_date=day,
            geo="US",
            timeframe="now 7-d",
            result=KeywordCollectionResult(
                keyword="generator",
                status=KeywordStatus.SUCCESS,
                rising=[QueryRecord("favicon generator", val, QueryType.RISING)],
            ),
        )
        store.finalize_run(run_id)

    report = store.build_run_report("r3")
    assert len(report.recurring_rising) == 1
    sig = report.recurring_rising[0]
    assert sig.consecutive_days == 3
    assert sig.previous_value == 1400
    assert sig.is_streak is True
    assert sig.is_accelerating is True

    # Query history with min_streak=3
    hist = store.query_history(min_streak=3)
    assert len(hist) == 1
    assert hist[0]["related_query"] == "favicon generator"


def test_v020_sqlite_schema_migrates_in_place(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy_v020.sqlite3"
    # Create an authentic v0.2.0 schema without the new v0.3.0 columns
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            run_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            resolved_timeframe TEXT NOT NULL,
            geo TEXT NOT NULL,
            rising_threshold INTEGER NOT NULL,
            total_keywords INTEGER NOT NULL DEFAULT 0,
            succeeded_keywords INTEGER NOT NULL DEFAULT 0,
            failed_keywords INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE run_keywords (
            run_id TEXT NOT NULL,
            keyword TEXT NOT NULL,
            position INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            rising_count INTEGER NOT NULL DEFAULT 0,
            top_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, keyword)
        );
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            keyword TEXT NOT NULL,
            geo TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            query_type TEXT NOT NULL,
            related_query TEXT NOT NULL,
            value INTEGER NOT NULL,
            is_breakout INTEGER NOT NULL DEFAULT 0,
            is_new INTEGER NOT NULL DEFAULT 0,
            seen_count INTEGER NOT NULL DEFAULT 1,
            previous_max_value INTEGER,
            first_seen_date TEXT
        );
        CREATE TABLE seen_queries (
            keyword TEXT NOT NULL,
            geo TEXT NOT NULL,
            query_type TEXT NOT NULL,
            query_normalized TEXT NOT NULL,
            display_query TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            first_seen_date TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_seen_date TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1,
            max_value INTEGER NOT NULL DEFAULT 0,
            last_value INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (keyword, geo, query_type, query_normalized)
        );
        INSERT INTO runs VALUES (
            'legacy_run', '2026-11-20', '2026-11-20T00:00:00Z', NULL,
            'partial', 'now 7-d', 'now 7-d', 'US', 500, 1, 0, 0
        );
        INSERT INTO run_keywords VALUES (
            'legacy_run', 'AI', 0, 'pending', NULL, NULL, 0, 0, '2026-11-20T00:00:00Z'
        );
        """
    )
    conn.commit()
    conn.close()

    # Opening with v0.3.0 SQLiteStore must auto-migrate cleanly
    store = SQLiteStore(db_file)
    targets = store.get_pending_targets("legacy_run")
    assert len(targets) == 1
    assert targets[0].keyword == "AI"
    assert targets[0].geo == "US"
    assert targets[0].cat == 0


def test_sharded_run_with_limit_and_cat_preserved(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.keywords = [
        KeywordSpec(keyword="Python", cat=31, geo="US"),
        KeywordSpec(keyword="generator", cat=0, geo="US"),
        KeywordSpec(keyword="converter", cat=5, geo="US"),
    ]
    cfg.filters = FilterSettings(min_word_count=2, exclude_patterns=[r"\bdown\b"])
    cfg.storage.data_dir = str(tmp_path / "data")
    cfg.storage.db_path = str(tmp_path / "data" / "history.sqlite3")
    cfg.rate_limit.min_delay_seconds = 0.0
    cfg.rate_limit.max_delay_seconds = 0.0
    cfg.rate_limit.batch_interval_seconds = 0.0

    recorded_calls: list[tuple[str, int]] = []

    class RecordingCollector(TrendsCollector):
        def fetch_keyword(
            self,
            keyword: str,
            *,
            geo: str,
            timeframe: str,
            cat: int = 0,
        ) -> KeywordCollectionResult:
            recorded_calls.append((keyword, cat))
            return KeywordCollectionResult(
                keyword=keyword,
                status=KeywordStatus.SUCCESS,
                rising=[
                    QueryRecord(f"cool {keyword} tool", 900, QueryType.RISING),
                    QueryRecord(f"{keyword} down", 1200, QueryType.RISING),  # should be filtered out
                ],
            )

    runner = TrendsMonitorRunner(
        cfg,
        collector=RecordingCollector(),
        sleep_fn=lambda _: None,
        now_fn=lambda: datetime(2026, 11, 22, 10, 0, 0),
    )

    # First shard: only process 2 keywords
    exec1 = runner.run(max_keywords=2)
    assert exec1.status == "partial"
    assert exec1.report.succeeded_keywords == 2
    assert exec1.report.pending_keywords == 1
    assert exec1.report.failed_keywords == 0
    assert exec1.report.filtered_count == 2  # both "* down" queries filtered
    assert len(exec1.report.new_rising) == 2
    assert recorded_calls == [("Python", 31), ("generator", 0)]

    # Second shard via resume: finishes converter with its cat=5 preserved!
    exec2 = runner.run(resume=True, max_keywords=2)
    assert exec2.status == "completed"
    assert exec2.report.succeeded_keywords == 3
    assert exec2.report.pending_keywords == 0
    assert recorded_calls[-1] == ("converter", 5)


def test_report_includes_quick_links_and_momentum_badges() -> None:
    report = RunReport(
        run_id="r_test",
        run_date="2026-11-22",
        generated_at="2026-11-22T12:00:00Z",
        timeframe="now 7-d",
        resolved_timeframe="now 7-d",
        geo="US",
        rising_threshold=500,
        total_keywords=2,
        succeeded_keywords=2,
        failed_keywords=0,
        filtered_count=7,
        new_rising=[
            RisingSignal("generator", "svg wave generator", 1200, False, True, geo="US"),
        ],
        recurring_rising=[
            RisingSignal(
                "converter",
                "heic to jpg converter",
                2400,
                False,
                False,
                geo="US",
                seen_count=3,
                consecutive_days=3,
                previous_value=800,
                previous_max_value=800,
            )
        ],
    )
    md = render_markdown(report)
    assert "Noise Filtered Out" in md
    assert "🔥 3d streak" in md
    assert "🚀 +800%→+2,400%" in md
    assert "[Google](https://www.google.com/search?q=" in md
    assert "[Exact](https://www.google.com/search?q=" in md

    html_doc = render_html(report)
    assert "Noise Filtered" in html_doc
    assert "🔥 3d" in html_doc
    assert "🚀 +800%→+2,400%" in html_doc
    assert "Exact</a>" in html_doc


def test_cli_init_presets_and_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cli = CliRunner()

    res_list = cli.invoke(main, ["init", "--list-presets"])
    assert res_list.exit_code == 0
    assert "saas-tools" in res_list.output
    assert "ai-products" in res_list.output

    res_init = cli.invoke(main, ["init", "--preset", "saas-tools"])
    assert res_init.exit_code == 0
    assert "preset: saas-tools" in res_init.output

    res_check = cli.invoke(main, ["check"])
    assert res_check.exit_code == 0
    assert "[OK] Collector: Provider `trendspy` ready" in res_check.output
