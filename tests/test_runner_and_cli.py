"""End-to-end tests for TrendsMonitorRunner (partial failure + resume) and CLI commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from trends_monitor.cli import main
from trends_monitor.collector import TrendsCollector
from trends_monitor.config import AppConfig
from trends_monitor.models import (
    ErrorType,
    KeywordCollectionResult,
    KeywordStatus,
    QueryRecord,
    QueryType,
)
from trends_monitor.runner import TrendsMonitorRunner


class FakeCollector(TrendsCollector):
    def __init__(self, responses: dict[str, KeywordCollectionResult]) -> None:
        self.responses = responses
        self.called: list[str] = []

    def fetch_keyword(
        self,
        keyword: str,
        *,
        geo: str,
        timeframe: str,
        cat: int = 0,
    ) -> KeywordCollectionResult:
        self.called.append(keyword)
        return self.responses[keyword]


def test_runner_partial_failure_and_resume(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.keywords = ["AI", "Python", "Video"]
    cfg.storage.data_dir = str(tmp_path / "data")
    cfg.storage.db_path = str(tmp_path / "data" / "history.sqlite3")
    cfg.rate_limit.min_delay_seconds = 0.0
    cfg.rate_limit.max_delay_seconds = 0.0
    cfg.rate_limit.batch_interval_seconds = 0.0

    # First run: Python fails with 429, AI and Video succeed
    first_collector = FakeCollector(
        {
            "AI": KeywordCollectionResult(
                keyword="AI",
                status=KeywordStatus.SUCCESS,
                rising=[QueryRecord("ai browser", 1200, QueryType.RISING)],
            ),
            "Python": KeywordCollectionResult(
                keyword="Python",
                status=KeywordStatus.FAILED,
                error_type=ErrorType.QUOTA_EXCEEDED,
                error_message="429",
            ),
            "Video": KeywordCollectionResult(
                keyword="Video",
                status=KeywordStatus.SUCCESS,
                rising=[QueryRecord("ai video maker", 6000, QueryType.RISING, is_breakout=True)],
            ),
        }
    )

    runner1 = TrendsMonitorRunner(
        cfg,
        collector=first_collector,
        sleep_fn=lambda _: None,
        now_fn=lambda: datetime(2026, 11, 22, 10, 0, 0),
    )
    exec1 = runner1.run()
    assert exec1.status == "partial"
    assert exec1.report.succeeded_keywords == 2
    assert exec1.report.failed_keywords == 1
    assert len(exec1.report.new_rising) == 2
    assert (tmp_path / "data" / "2026-11-22" / "digest_2026-11-22.md").exists()

    # Resume run: only Python should be queried!
    second_collector = FakeCollector(
        {
            "Python": KeywordCollectionResult(
                keyword="Python",
                status=KeywordStatus.SUCCESS,
                rising=[QueryRecord("uv python", 950, QueryType.RISING)],
            )
        }
    )
    runner2 = TrendsMonitorRunner(
        cfg,
        collector=second_collector,
        sleep_fn=lambda _: None,
        now_fn=lambda: datetime(2026, 11, 22, 10, 15, 0),
    )
    exec2 = runner2.run(resume=True)
    assert exec2.resumed is True
    assert exec2.status == "completed"
    assert second_collector.called == ["Python"]
    assert exec2.report.succeeded_keywords == 3
    assert exec2.report.failed_keywords == 0
    assert len(exec2.report.new_rising) == 3


def test_cli_init_check_and_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cli = CliRunner()
    res_init = cli.invoke(main, ["init"])
    assert res_init.exit_code == 0
    assert Path("config.yaml").exists()
    assert Path(".env").exists()

    # Check should succeed out-of-the-box without SMTP credentials (email disabled by default)
    res_check = cli.invoke(main, ["check"])
    assert res_check.exit_code == 0
    assert "[OK] Config loaded" in res_check.output
    assert "[OK] Notifier (local)" in res_check.output

    # History on empty DB should exit cleanly
    res_hist = cli.invoke(main, ["history"])
    assert res_hist.exit_code == 0
    assert "No matching historical rising queries" in res_hist.output
