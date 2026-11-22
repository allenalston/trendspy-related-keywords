"""Command-line interface for TrendSpy Related Keywords Monitor."""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import click

from trends_monitor import __version__
from trends_monitor.collector import build_collector, resolve_timeframe
from trends_monitor.config import load_config
from trends_monitor.models import KeywordStatus
from trends_monitor.notifiers import build_notifiers
from trends_monitor.presets import PRESETS, get_preset
from trends_monitor.runner import TrendsMonitorRunner
from trends_monitor.storage import SQLiteStore

DEFAULT_ENV_TEMPLATE = """\
# Optional proxy or comma-separated proxy pool for Google Trends requests
# TRENDS_PROXY=http://127.0.0.1:7890
# TRENDS_PROXIES=http://user:pass@proxy1:8080,http://user:pass@proxy2:8080

# Optional SerpApi key (only needed when trends.provider is "serpapi")
# TRENDS_SERPAPI_KEY=

# Optional SMTP settings (only needed when notifications.email.enabled is true)
TRENDS_SMTP_SERVER=smtp.gmail.com
TRENDS_SMTP_PORT=587
TRENDS_SENDER_EMAIL=
TRENDS_SENDER_PASSWORD=
TRENDS_RECIPIENT_EMAIL=

# Optional Webhook URLs
TRENDS_FEISHU_WEBHOOK=
TRENDS_WECOM_WEBHOOK=
TRENDS_WEBHOOK_URL=
"""


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="trends-monitor")
def main() -> None:
    """Google Trends rising related keywords monitor."""


@main.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Target YAML config path.")
@click.option("--env", "env_path", default=".env", show_default=True, help="Target .env file path.")
@click.option(
    "--preset",
    default="default",
    show_default=True,
    help=f"Starter keyword & filter preset ({', '.join(sorted(PRESETS))}).",
)
@click.option("--list-presets", is_flag=True, help="List available starter presets and exit.")
@click.option("--force", is_flag=True, help="Overwrite existing config files.")
def init(config_path: str, env_path: str, preset: str, list_presets: bool, force: bool) -> None:
    """Initialize starter `config.yaml` (with optional preset) and `.env` files."""
    if list_presets:
        click.echo("Available presets:")
        for key in sorted(PRESETS):
            p = PRESETS[key]
            click.echo(f"  - {p.name:<14} {p.description}")
        return

    try:
        preset_def = get_preset(preset)
    except ValueError as exc:
        click.secho(str(exc), fg="red", err=True)
        sys.exit(2)

    cfg_file = Path(config_path)
    env_file = Path(env_path)

    if cfg_file.exists() and not force:
        click.echo(f"Skipped {cfg_file} (already exists; use --force to overwrite).")
    else:
        cfg_file.write_text(preset_def.yaml_content, encoding="utf-8")
        click.echo(f"Created {cfg_file} (preset: {preset_def.name})")

    if env_file.exists() and not force:
        click.echo(f"Skipped {env_file} (already exists; use --force to overwrite).")
    else:
        env_file.write_text(DEFAULT_ENV_TEMPLATE, encoding="utf-8")
        click.echo(f"Created {env_file}")

    click.echo("\nNext steps:")
    click.echo(f"  1. Review {cfg_file} and adjust keywords / filters if needed.")
    click.echo("  2. Run `trends-monitor run` to collect data and generate a local digest.")
    click.echo("  3. Optionally configure email/Feishu/WeCom or proxies in `.env` and run `trends-monitor check`.")


@main.command()
@click.option("-c", "--config", "config_path", default="config.yaml", show_default=True, help="Path to YAML config file.")
@click.option("-k", "--keywords", multiple=True, help="Override seed keywords (repeatable, e.g. -k AI -k Python).")
@click.option("--geo", default=None, help="Override region code (e.g. US, JP, or '' for Worldwide).")
@click.option("--timeframe", default=None, help="Override timeframe (e.g. 'now 1-d', 'now 7-d', 'last-3-d').")
@click.option("--cat", type=int, default=None, help="Override Google Trends category ID (e.g. 31 for Programming).")
@click.option("--limit", "max_keywords", type=int, default=None, help="Process at most N pending keywords in this pass (pair with --resume).")
@click.option("--resume", is_flag=True, help="Resume the latest incomplete run from SQLite checkpoint.")
@click.option("--run-id", default=None, help="Resume a specific run ID.")
@click.option("--no-notify", is_flag=True, help="Skip external notifications (email/webhooks); still writes local reports.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose debug logging.")
def run(
    config_path: str,
    keywords: tuple[str, ...],
    geo: str | None,
    timeframe: str | None,
    cat: int | None,
    max_keywords: int | None,
    resume: bool,
    run_id: str | None,
    no_notify: bool,
    verbose: bool,
) -> None:
    """Run a collection pass, deduplicate & filter against history, and send digest."""
    _configure_logging(verbose)

    allow_missing = bool(keywords) or resume or bool(run_id)
    try:
        cfg = load_config(config_path, allow_missing=allow_missing)
    except Exception as exc:
        click.secho(f"Configuration error: {exc}", fg="red", err=True)
        sys.exit(2)

    runner = TrendsMonitorRunner(cfg)

    def _progress(idx: int, total: int, kw: str, status_text: str) -> None:
        color = "green" if status_text.startswith("success") else "red"
        click.echo(f"[{idx}/{total}] {kw}: ", nl=False)
        click.secho(status_text, fg=color)

    try:
        execution = runner.run(
            keywords_override=list(keywords) if keywords else None,
            geo_override=geo,
            timeframe_override=timeframe,
            cat_override=cat,
            max_keywords=max_keywords,
            resume=resume,
            run_id=run_id,
            no_notify=no_notify,
            on_progress=_progress,
        )
    except Exception as exc:
        click.secho(f"Run aborted: {exc}", fg="red", err=True)
        sys.exit(1)

    report = execution.report
    click.echo("")
    click.secho(f"Run {report.run_id} finished ({execution.status})", bold=True)
    pending_suffix = f", {report.pending_keywords} pending" if report.pending_keywords else ""
    click.echo(
        f"  Keywords: {report.succeeded_keywords}/{report.total_keywords} succeeded "
        f"({report.failed_keywords} failed{pending_suffix})"
    )
    filter_suffix = f" ({report.filtered_count} noise filtered)" if report.filtered_count else ""
    click.echo(
        f"  Rising signals (>= +{report.rising_threshold}%): "
        f"{len(report.new_rising)} New, {len(report.recurring_rising)} Recurring{filter_suffix}"
    )
    if report.pending_keywords > 0:
        click.echo("  Tip: Run `trends-monitor run --resume` to continue remaining pending keywords.")
    if report.csv_path:
        click.echo(f"  CSV export: {report.csv_path}")

    for res in execution.notify_results:
        icon = "OK" if res.success else "FAIL"
        color = "green" if res.success else "red"
        click.echo(f"  Notify [{res.channel}]: ", nl=False)
        click.secho(f"{icon} - {res.message}", fg=color)
        for artifact in res.artifacts:
            click.echo(f"    -> {artifact}")

    if report.succeeded_keywords == 0 and report.total_keywords > 0:
        sys.exit(1)


@main.command()
@click.option("-c", "--config", "config_path", default="config.yaml", show_default=True, help="Path to YAML config file.")
@click.option("--live", is_flag=True, help="Also run a live 1-keyword Google Trends connectivity probe.")
@click.option("--probe-keyword", default="Python", show_default=True, help="Keyword used with --live.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose debug logging.")
def check(config_path: str, live: bool, probe_keyword: str, verbose: bool) -> None:
    """Validate configuration, provider, storage, notifiers, and optional live Trends access."""
    _configure_logging(verbose)
    all_ok = True

    try:
        cfg = load_config(config_path, allow_missing=False)
        click.secho(
            f"[OK] Config loaded ({len(cfg.get_keyword_specs())} keywords, "
            f"provider={cfg.trends.provider}, timeframe={cfg.trends.timeframe}, "
            f"geo={cfg.trends.geo or 'Worldwide'})",
            fg="green",
        )
    except Exception as exc:
        click.secho(f"[FAIL] Config: {exc}", fg="red")
        sys.exit(2)

    collector = build_collector(cfg)
    ok, msg = collector.check()
    if ok:
        click.secho(f"[OK] Collector: {msg}", fg="green")
    else:
        click.secho(f"[FAIL] Collector: {msg}", fg="red")
        all_ok = False

    try:
        store = SQLiteStore(cfg.storage.db_path)
        click.secho(f"[OK] SQLite store ready: {store.db_path}", fg="green")
    except Exception as exc:
        click.secho(f"[FAIL] SQLite store: {exc}", fg="red")
        all_ok = False

    notifiers = build_notifiers(cfg)
    if not notifiers:
        click.secho("[WARN] No notification channels are enabled.", fg="yellow")
    for notifier in notifiers:
        n_ok, n_msg = notifier.check()
        if n_ok:
            click.secho(f"[OK] Notifier ({notifier.name}): {n_msg}", fg="green")
        else:
            click.secho(f"[FAIL] Notifier ({notifier.name}): {n_msg}", fg="red")
            all_ok = False

    if live:
        click.echo(f"Running live Google Trends probe for {probe_keyword!r} via {cfg.trends.provider}...")
        resolved = resolve_timeframe(cfg.trends.timeframe)
        res = collector.fetch_keyword(
            probe_keyword,
            geo=cfg.trends.geo,
            timeframe=resolved,
            cat=cfg.trends.cat,
        )
        if res.status == KeywordStatus.SUCCESS:
            click.secho(
                f"[OK] Live probe succeeded: {len(res.rising)} rising, {len(res.top)} top queries",
                fg="green",
            )
        else:
            click.secho(
                f"[FAIL] Live probe failed [{res.error_type.value if res.error_type else 'error'}]: {res.error_message}",
                fg="red",
            )
            all_ok = False

    if not all_ok:
        sys.exit(1)


@main.command()
@click.option("-c", "--config", "config_path", default="config.yaml", show_default=True, help="Path to YAML config file.")
@click.option("--date", "run_date", default=None, help="Resend the latest run from YYYY-MM-DD.")
@click.option("--run-id", default=None, help="Resend a specific run ID.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose debug logging.")
def notify(config_path: str, run_date: str | None, run_id: str | None, verbose: bool) -> None:
    """Resend digest notifications for a previously stored run without re-querying Trends."""
    _configure_logging(verbose)
    try:
        cfg = load_config(config_path, allow_missing=True)
        runner = TrendsMonitorRunner(cfg)
        report, results = runner.resend_notification(run_id=run_id, run_date=run_date)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)

    click.echo(f"Dispatched report for run {report.run_id} ({report.run_date}):")
    any_failed = False
    for res in results:
        icon = "OK" if res.success else "FAIL"
        color = "green" if res.success else "red"
        click.echo(f"  [{res.channel}] ", nl=False)
        click.secho(f"{icon} - {res.message}", fg=color)
        if not res.success:
            any_failed = True

    if any_failed:
        sys.exit(1)


@main.command()
@click.option("-c", "--config", "config_path", default="config.yaml", show_default=True, help="Path to YAML config file.")
@click.option("-k", "--keyword", default=None, help="Filter by seed keyword.")
@click.option("--new-only", is_flag=True, help="Only show queries marked as New.")
@click.option("--min-value", type=int, default=None, help="Minimum rising growth percentage.")
@click.option("--min-streak", type=int, default=None, help="Minimum consecutive days observed (e.g. 2).")
@click.option("--limit", type=int, default=30, show_default=True, help="Maximum rows to display.")
@click.option("--export", "export_path", default=None, help="Optional CSV path to export matching history.")
def history(
    config_path: str,
    keyword: str | None,
    new_only: bool,
    min_value: int | None,
    min_streak: int | None,
    limit: int,
    export_path: str | None,
) -> None:
    """Inspect historical rising related queries stored in SQLite."""
    try:
        cfg = load_config(config_path, allow_missing=True)
    except Exception as exc:
        click.secho(f"Configuration error: {exc}", fg="red", err=True)
        sys.exit(2)

    store = SQLiteStore(cfg.storage.db_path)
    rows = store.query_history(
        keyword=keyword,
        new_only=new_only,
        min_value=min_value,
        min_streak=min_streak,
        limit=limit,
    )

    if not rows:
        click.echo("No matching historical rising queries found.")
        return

    if export_path:
        out = Path(export_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        click.secho(f"Exported {len(rows)} rows to {out}", fg="green")
        return

    click.echo(f"{'Date':<12} {'New':<5} {'Streak':<7} {'Keyword':<14} {'Growth':>10}  {'Related Query'}")
    click.echo("-" * 84)
    for row in rows:
        tag = "NEW" if row["is_new"] else " - "
        streak = f"{int(row.get('consecutive_days') or 1)}d"
        growth = f"+{row['value']}%" + ("*" if row["is_breakout"] else "")
        click.echo(
            f"{row['run_date']:<12} {tag:<5} {streak:<7} {row['keyword'][:13]:<14} {growth:>10}  {row['related_query']}"
        )
