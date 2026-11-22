"""Core monitoring pipeline orchestration (collect -> persist -> dedup/filter -> report -> notify)."""

from __future__ import annotations

import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from trends_monitor.collector import TrendsCollector, build_collector, resolve_timeframe
from trends_monitor.config import AppConfig
from trends_monitor.filters import QueryFilter
from trends_monitor.models import KeywordStatus, KeywordTarget, NotifyResult, RunReport
from trends_monitor.notifiers import BaseNotifier, build_notifiers, dispatch_notifications
from trends_monitor.storage import SQLiteStore, save_raw_json

logger = logging.getLogger(__name__)


@dataclass
class RunExecutionResult:
    """Outcome of a single monitor run."""

    report: RunReport
    status: str
    notify_results: list[NotifyResult] = field(default_factory=list)
    resumed: bool = False


class TrendsMonitorRunner:
    """Coordinates collection, SQLite persistence, deduplication, filtering, and notification dispatch."""

    def __init__(
        self,
        config: AppConfig,
        *,
        collector: TrendsCollector | None = None,
        store: SQLiteStore | None = None,
        notifiers: list[BaseNotifier] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.collector = collector or build_collector(config, sleep_fn=sleep_fn)
        self.store = store or SQLiteStore(config.storage.db_path)
        self.query_filter = QueryFilter(config.filters)
        self._custom_notifiers = notifiers
        self._sleep = sleep_fn
        self._now = now_fn

    def _build_targets(
        self,
        *,
        now: datetime,
        keywords_override: list[str] | None,
        geo_override: str | None,
        timeframe_override: str | None,
        cat_override: int | None,
    ) -> list[KeywordTarget]:
        default_geo = (
            geo_override.strip().upper() if geo_override is not None else self.config.trends.geo
        )
        default_tf = (
            timeframe_override if timeframe_override is not None else self.config.trends.timeframe
        )
        default_cat = cat_override if cat_override is not None else self.config.trends.cat

        if keywords_override is not None:
            resolved_tf = resolve_timeframe(default_tf, now=now)
            return [
                KeywordTarget(
                    keyword=kw.strip(),
                    geo=default_geo,
                    timeframe=default_tf,
                    resolved_timeframe=resolved_tf,
                    cat=default_cat,
                )
                for kw in keywords_override
                if kw.strip()
            ]

        targets: list[KeywordTarget] = []
        for spec in self.config.get_keyword_specs():
            geo = (
                geo_override.strip().upper()
                if geo_override is not None
                else (spec.geo if spec.geo is not None else self.config.trends.geo)
            )
            tf = (
                timeframe_override
                if timeframe_override is not None
                else (spec.timeframe if spec.timeframe is not None else self.config.trends.timeframe)
            )
            cat = (
                cat_override
                if cat_override is not None
                else (spec.cat if spec.cat is not None else self.config.trends.cat)
            )
            targets.append(
                KeywordTarget(
                    keyword=spec.keyword,
                    geo=geo,
                    timeframe=tf,
                    resolved_timeframe=resolve_timeframe(tf, now=now),
                    cat=cat,
                )
            )
        return targets

    def run(
        self,
        *,
        keywords_override: list[str] | None = None,
        geo_override: str | None = None,
        timeframe_override: str | None = None,
        cat_override: int | None = None,
        max_keywords: int | None = None,
        resume: bool = False,
        run_id: str | None = None,
        no_notify: bool = False,
        on_progress: Callable[[int, int, str, str], None] | None = None,
    ) -> RunExecutionResult:
        """Execute a monitoring run (or resume an incomplete one, optionally sharded via max_keywords)."""
        resumed = False
        now = self._now()

        if resume or run_id:
            existing = (
                self.store.get_run(run_id)
                if run_id
                else self.store.find_latest_incomplete_run()
            )
            if existing is None:
                if run_id:
                    raise ValueError(f"Run ID not found: {run_id}")
                logger.info("No incomplete run found to resume; starting a new run.")
            else:
                resumed = True
                active_run_id = str(existing["run_id"])
                run_date = str(existing["run_date"])
                pending_targets = self.store.get_pending_targets(active_run_id)
                logger.info(
                    "Resuming run %s (%d pending/failed keywords remaining)",
                    active_run_id,
                    len(pending_targets),
                )

        if not resumed:
            targets = self._build_targets(
                now=now,
                keywords_override=keywords_override,
                geo_override=geo_override,
                timeframe_override=timeframe_override,
                cat_override=cat_override,
            )
            if not targets:
                raise ValueError("No keywords configured. Add keywords to config.yaml or pass --keywords.")
            run_tf = timeframe_override if timeframe_override is not None else self.config.trends.timeframe
            run_resolved_tf = resolve_timeframe(run_tf, now=now)
            run_geo = geo_override.strip().upper() if geo_override is not None else self.config.trends.geo
            run_date = now.strftime("%Y-%m-%d")
            active_run_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            pending_targets = targets

            self.store.create_run(
                run_id=active_run_id,
                run_date=run_date,
                targets=targets,
                timeframe=run_tf,
                resolved_timeframe=run_resolved_tf,
                geo=run_geo,
                rising_threshold=self.config.monitor.rising_threshold,
            )

        if max_keywords is not None and max_keywords > 0:
            pending_targets = pending_targets[:max_keywords]

        output_dir = Path(self.config.storage.data_dir) / run_date
        output_dir.mkdir(parents=True, exist_ok=True)

        batch_size = self.config.rate_limit.batch_size
        total_pending = len(pending_targets)

        for idx, target in enumerate(pending_targets, start=1):
            logger.info(
                "[%d/%d] Querying keyword %r (geo=%s, timeframe=%s, cat=%d)",
                idx,
                total_pending,
                target.keyword,
                target.geo or "Worldwide",
                target.resolved_timeframe,
                target.cat,
            )
            result = self.collector.fetch_keyword(
                target.keyword,
                geo=target.geo,
                timeframe=target.resolved_timeframe,
                cat=target.cat,
            )

            self.store.record_keyword_result(
                run_id=active_run_id,
                run_date=run_date,
                geo=target.geo,
                timeframe=target.resolved_timeframe,
                result=result,
                dedup_days=self.config.monitor.dedup_days,
            )

            if self.config.storage.save_raw_json and result.status == KeywordStatus.SUCCESS:
                save_raw_json(
                    output_dir,
                    result,
                    geo=target.geo,
                    timeframe=target.resolved_timeframe,
                    cat=target.cat,
                )

            if on_progress:
                detail = (
                    f"{len(result.rising)} rising, {len(result.top)} top"
                    if result.status == KeywordStatus.SUCCESS
                    else f"{result.error_type.value if result.error_type else 'error'}: {result.error_message}"
                )
                on_progress(idx, total_pending, target.keyword, f"{result.status.value} ({detail})")

            if idx < total_pending:
                if idx % batch_size == 0 and self.config.rate_limit.batch_interval_seconds > 0:
                    wait = self.config.rate_limit.batch_interval_seconds + random.uniform(0.0, 5.0)
                    logger.info("Batch boundary reached; sleeping %.1fs before next batch", wait)
                    self._sleep(wait)
                elif self.config.rate_limit.max_delay_seconds > 0:
                    wait = random.uniform(
                        self.config.rate_limit.min_delay_seconds,
                        self.config.rate_limit.max_delay_seconds,
                    )
                    if wait > 0:
                        self._sleep(wait)

        final_status = self.store.finalize_run(active_run_id)

        csv_path: Path | None = None
        if self.config.storage.save_csv:
            csv_path = self.store.export_run_csv(
                active_run_id,
                output_dir / f"daily_report_{run_date}.csv",
            )

        report = self.store.build_run_report(
            active_run_id,
            max_items_per_section=self.config.monitor.max_items_per_section,
            query_filter=self.query_filter,
            csv_path=csv_path,
            output_dir=output_dir,
        )

        if self._custom_notifiers is not None:
            notifiers = [] if no_notify else self._custom_notifiers
        else:
            if no_notify:
                notifiers = [n for n in build_notifiers(self.config) if n.name == "local"]
            else:
                notifiers = build_notifiers(self.config)

        notify_results = dispatch_notifications(report, notifiers)
        return RunExecutionResult(
            report=report,
            status=final_status,
            notify_results=notify_results,
            resumed=resumed,
        )

    def resend_notification(
        self,
        *,
        run_id: str | None = None,
        run_date: str | None = None,
    ) -> tuple[RunReport, list[NotifyResult]]:
        """Rebuild a report from SQLite history and dispatch it to enabled notifiers."""
        run_row = (
            self.store.get_run(run_id)
            if run_id
            else self.store.find_latest_run(run_date=run_date)
        )
        if run_row is None:
            target = run_id or run_date or "latest"
            raise ValueError(f"No stored run found for target: {target}")

        active_run_id = str(run_row["run_id"])
        target_date = str(run_row["run_date"])
        output_dir = Path(self.config.storage.data_dir) / target_date
        csv_candidate = output_dir / f"daily_report_{target_date}.csv"
        if not csv_candidate.exists() and self.config.storage.save_csv:
            csv_path = self.store.export_run_csv(active_run_id, csv_candidate)
        else:
            csv_path = csv_candidate if csv_candidate.exists() else None

        report = self.store.build_run_report(
            active_run_id,
            max_items_per_section=self.config.monitor.max_items_per_section,
            query_filter=self.query_filter,
            csv_path=csv_path,
            output_dir=output_dir,
        )

        notifiers = (
            self._custom_notifiers
            if self._custom_notifiers is not None
            else build_notifiers(self.config)
        )
        results = dispatch_notifications(report, notifiers)
        return report, results
