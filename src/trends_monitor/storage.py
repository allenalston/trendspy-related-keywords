"""SQLite historical store, deduplication/streak engine, resume checkpointing, and raw/CSV export."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trends_monitor.filters import QueryFilter
from trends_monitor.models import (
    FailedKeywordItem,
    KeywordCollectionResult,
    KeywordStatus,
    KeywordTarget,
    QueryType,
    RisingSignal,
    RunReport,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
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

CREATE TABLE IF NOT EXISTS run_keywords (
    run_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    position INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    rising_count INTEGER NOT NULL DEFAULT 0,
    top_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    geo TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '',
    resolved_timeframe TEXT NOT NULL DEFAULT '',
    cat INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, keyword),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS observations (
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
    previous_value INTEGER,
    previous_max_value INTEGER,
    consecutive_days INTEGER NOT NULL DEFAULT 1,
    first_seen_date TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_observations_run_id ON observations(run_id);
CREATE INDEX IF NOT EXISTS idx_observations_run_date ON observations(run_date);
CREATE INDEX IF NOT EXISTS idx_observations_keyword ON observations(keyword, query_type);

CREATE TABLE IF NOT EXISTS seen_queries (
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
    consecutive_days INTEGER NOT NULL DEFAULT 1,
    max_value INTEGER NOT NULL DEFAULT 0,
    last_value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (keyword, geo, query_type, query_normalized)
);
"""

# Backward-compatible schema migrations for databases created by v0.2.0
MIGRATIONS: list[tuple[str, str, str]] = [
    ("run_keywords", "geo", "TEXT NOT NULL DEFAULT ''"),
    ("run_keywords", "timeframe", "TEXT NOT NULL DEFAULT ''"),
    ("run_keywords", "resolved_timeframe", "TEXT NOT NULL DEFAULT ''"),
    ("run_keywords", "cat", "INTEGER NOT NULL DEFAULT 0"),
    ("observations", "previous_value", "INTEGER"),
    ("observations", "consecutive_days", "INTEGER NOT NULL DEFAULT 1"),
    ("seen_queries", "consecutive_days", "INTEGER NOT NULL DEFAULT 1"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_filename(name: str, max_length: int = 64) -> str:
    """Convert arbitrary keyword strings into safe filesystem slugs."""
    cleaned = re.sub(r"[^\w\-.]+", "_", name.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._") or "keyword"
    return cleaned[:max_length]


def save_raw_json(
    output_dir: Path,
    result: KeywordCollectionResult,
    *,
    geo: str,
    timeframe: str,
    cat: int = 0,
) -> Path:
    """Persist raw collected records for a single keyword to JSON."""
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    slug = sanitize_filename(result.keyword)
    filepath = raw_dir / f"related_queries_{slug}.json"
    payload = {
        "keyword": result.keyword,
        "geo": geo,
        "timeframe": timeframe,
        "cat": cat,
        "collected_at": utc_now_iso(),
        "status": result.status.value,
        "related_queries": {
            "rising": [
                {
                    "query": r.query,
                    "value": r.value,
                    "is_breakout": r.is_breakout,
                }
                for r in result.rising
            ],
            "top": [
                {
                    "query": r.query,
                    "value": r.value,
                }
                for r in result.top
            ],
        },
    }
    filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return filepath


class SQLiteStore:
    """SQLite-backed state store supporting deduplication, streaks, resume, and history."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        existing_cols_cache: dict[str, set[str]] = {}
        for table, column, ddl in MIGRATIONS:
            if table not in existing_cols_cache:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                existing_cols_cache[table] = {str(r["name"]) for r in rows}
            if column not in existing_cols_cache[table]:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                existing_cols_cache[table].add(column)

    def create_run(
        self,
        *,
        run_id: str,
        run_date: str,
        keywords: list[str] | None = None,
        targets: list[KeywordTarget] | None = None,
        timeframe: str,
        resolved_timeframe: str,
        geo: str,
        rising_threshold: int,
    ) -> None:
        now = utc_now_iso()
        resolved_targets = (
            list(targets)
            if targets is not None
            else [
                KeywordTarget(
                    keyword=kw,
                    geo=geo,
                    timeframe=timeframe,
                    resolved_timeframe=resolved_timeframe,
                    cat=0,
                )
                for kw in (keywords or [])
            ]
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, run_date, started_at, status, timeframe,
                    resolved_timeframe, geo, rising_threshold, total_keywords
                )
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_date,
                    now,
                    timeframe,
                    resolved_timeframe,
                    geo,
                    rising_threshold,
                    len(resolved_targets),
                ),
            )
            conn.executemany(
                """
                INSERT INTO run_keywords (
                    run_id, keyword, position, status, updated_at,
                    geo, timeframe, resolved_timeframe, cat
                )
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        t.keyword,
                        idx,
                        now,
                        t.geo,
                        t.timeframe,
                        t.resolved_timeframe,
                        t.cat,
                    )
                    for idx, t in enumerate(resolved_targets)
                ],
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def find_latest_incomplete_run(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE status IN ('running', 'partial', 'failed')
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def find_latest_run(self, *, run_date: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if run_date:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_date = ? ORDER BY started_at DESC LIMIT 1",
                    (run_date,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            return dict(row) if row else None

    def get_pending_targets(self, run_id: str) -> list[KeywordTarget]:
        """Return unfinished KeywordTarget items (pending or failed) for resume."""
        with self._connect() as conn:
            run = conn.execute(
                "SELECT geo, timeframe, resolved_timeframe FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                return []
            rows = conn.execute(
                """
                SELECT keyword, geo, timeframe, resolved_timeframe, cat
                FROM run_keywords
                WHERE run_id = ? AND status != 'success'
                ORDER BY position ASC
                """,
                (run_id,),
            ).fetchall()

        targets: list[KeywordTarget] = []
        for row in rows:
            # Handle legacy v0.2.0 rows where per-keyword fields default to ''
            tf = str(row["timeframe"] or run["timeframe"])
            rtf = str(row["resolved_timeframe"] or run["resolved_timeframe"])
            geo = str(row["geo"]) if row["timeframe"] else str(run["geo"])
            targets.append(
                KeywordTarget(
                    keyword=str(row["keyword"]),
                    geo=geo,
                    timeframe=tf,
                    resolved_timeframe=rtf,
                    cat=int(row["cat"] or 0),
                )
            )
        return targets

    def get_pending_keywords(self, run_id: str) -> list[str]:
        return [t.keyword for t in self.get_pending_targets(run_id)]

    def record_keyword_result(
        self,
        *,
        run_id: str,
        run_date: str,
        geo: str,
        timeframe: str,
        result: KeywordCollectionResult,
        dedup_days: int = 7,
    ) -> None:
        """Persist a single keyword result immediately for crash-safe checkpointing."""
        now = utc_now_iso()
        run_date_obj = date.fromisoformat(run_date)

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_keywords
                SET status = ?, error_type = ?, error_message = ?,
                    rising_count = ?, top_count = ?, updated_at = ?
                WHERE run_id = ? AND keyword = ?
                """,
                (
                    result.status.value,
                    result.error_type.value if result.error_type else None,
                    result.error_message,
                    len(result.rising),
                    len(result.top),
                    now,
                    run_id,
                    result.keyword,
                ),
            )

            # Clear any previous observations for this (run_id, keyword) if retried during resume
            conn.execute(
                "DELETE FROM observations WHERE run_id = ? AND keyword = ?",
                (run_id, result.keyword),
            )

            if result.status == KeywordStatus.SUCCESS:
                all_records = [*result.rising, *result.top]
                for rec in all_records:
                    norm_query = rec.query.strip().lower()
                    existing = conn.execute(
                        """
                        SELECT first_seen_date, last_seen_date, seen_count,
                               consecutive_days, max_value, last_value
                        FROM seen_queries
                        WHERE keyword = ? AND geo = ? AND query_type = ? AND query_normalized = ?
                        """,
                        (result.keyword, geo, rec.query_type.value, norm_query),
                    ).fetchone()

                    if existing is None:
                        is_new = True
                        new_seen_count = 1
                        new_streak = 1
                        prev_val: int | None = None
                        prev_max: int | None = None
                        first_seen_date = run_date
                        conn.execute(
                            """
                            INSERT INTO seen_queries (
                                keyword, geo, query_type, query_normalized, display_query,
                                first_seen_at, first_seen_date, last_seen_at, last_seen_date,
                                seen_count, consecutive_days, max_value, last_value
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                            """,
                            (
                                result.keyword,
                                geo,
                                rec.query_type.value,
                                norm_query,
                                rec.query,
                                now,
                                run_date,
                                now,
                                run_date,
                                rec.value,
                                rec.value,
                            ),
                        )
                    else:
                        prev_last_date = date.fromisoformat(existing["last_seen_date"])
                        days_since = (run_date_obj - prev_last_date).days
                        is_new = dedup_days > 0 and days_since > dedup_days
                        new_seen_count = int(existing["seen_count"]) + 1
                        prev_streak = int(existing["consecutive_days"] or 1)
                        if days_since == 1:
                            new_streak = prev_streak + 1
                        elif days_since == 0:
                            new_streak = prev_streak
                        else:
                            new_streak = 1
                        prev_val = int(existing["last_value"])
                        prev_max = int(existing["max_value"])
                        first_seen_date = str(existing["first_seen_date"])
                        updated_max = max(prev_max, rec.value)
                        conn.execute(
                            """
                            UPDATE seen_queries
                            SET display_query = ?, last_seen_at = ?, last_seen_date = ?,
                                seen_count = ?, consecutive_days = ?, max_value = ?, last_value = ?
                            WHERE keyword = ? AND geo = ? AND query_type = ? AND query_normalized = ?
                            """,
                            (
                                rec.query,
                                now,
                                run_date,
                                new_seen_count,
                                new_streak,
                                updated_max,
                                rec.value,
                                result.keyword,
                                geo,
                                rec.query_type.value,
                                norm_query,
                            ),
                        )

                    conn.execute(
                        """
                        INSERT INTO observations (
                            run_id, run_date, observed_at, keyword, geo, timeframe,
                            query_type, related_query, value, is_breakout,
                            is_new, seen_count, previous_value, previous_max_value,
                            consecutive_days, first_seen_date
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            run_date,
                            now,
                            result.keyword,
                            geo,
                            timeframe,
                            rec.query_type.value,
                            rec.query,
                            rec.value,
                            1 if rec.is_breakout else 0,
                            1 if is_new else 0,
                            new_seen_count,
                            prev_val,
                            prev_max,
                            new_streak,
                            first_seen_date,
                        ),
                    )

            self._refresh_run_counts(conn, run_id)

    def _refresh_run_counts(self, conn: sqlite3.Connection, run_id: str) -> None:
        counts = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM run_keywords
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE runs
            SET total_keywords = ?, succeeded_keywords = ?, failed_keywords = ?
            WHERE run_id = ?
            """,
            (
                int(counts["total"] or 0),
                int(counts["succeeded"] or 0),
                int(counts["failed"] or 0),
                run_id,
            ),
        )

    def finalize_run(self, run_id: str) -> str:
        """Compute final run status ('completed', 'partial', or 'failed') and stamp finished_at."""
        now = utc_now_iso()
        with self._connect() as conn:
            self._refresh_run_counts(conn, run_id)
            row = conn.execute(
                "SELECT total_keywords, succeeded_keywords, failed_keywords FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            total = int(row["total_keywords"])
            succeeded = int(row["succeeded_keywords"])
            failed = int(row["failed_keywords"])

            if total > 0 and succeeded == total:
                status = "completed"
            elif succeeded > 0:
                status = "partial"
            elif failed > 0:
                status = "failed"
            else:
                status = "completed"

            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )
            return status

    def export_run_csv(self, run_id: str, csv_path: Path) -> Path | None:
        """Export all observations for a run into a clean UTF-8 CSV file."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT keyword, related_query, query_type, value, is_breakout,
                       is_new, seen_count, consecutive_days, previous_value,
                       previous_max_value, geo, timeframe, observed_at
                FROM observations
                WHERE run_id = ?
                ORDER BY
                    CASE WHEN query_type = 'rising' THEN 0 ELSE 1 END,
                    is_new DESC,
                    consecutive_days DESC,
                    value DESC,
                    keyword ASC
                """,
                (run_id,),
            ).fetchall()

        if not rows:
            return None

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        headers = [
            "keyword",
            "related_query",
            "query_type",
            "value",
            "is_breakout",
            "is_new",
            "seen_count",
            "consecutive_days",
            "previous_value",
            "previous_max_value",
            "geo",
            "timeframe",
            "observed_at",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(
                    [
                        row["keyword"],
                        row["related_query"],
                        row["query_type"],
                        row["value"],
                        bool(row["is_breakout"]),
                        bool(row["is_new"]),
                        row["seen_count"],
                        int(row["consecutive_days"] or 1),
                        "" if row["previous_value"] is None else row["previous_value"],
                        "" if row["previous_max_value"] is None else row["previous_max_value"],
                        row["geo"],
                        row["timeframe"],
                        row["observed_at"],
                    ]
                )
        return csv_path

    def build_run_report(
        self,
        run_id: str,
        *,
        max_items_per_section: int = 50,
        query_filter: QueryFilter | None = None,
        csv_path: Path | None = None,
        output_dir: Path | None = None,
    ) -> RunReport:
        """Build a structured RunReport directly from persisted SQLite data."""
        with self._connect() as conn:
            run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"Run not found: {run_id}")

            rising_rows = conn.execute(
                """
                SELECT keyword, related_query, value, is_breakout, is_new, geo,
                       seen_count, consecutive_days, previous_value,
                       previous_max_value, first_seen_date
                FROM observations
                WHERE run_id = ?
                  AND query_type = ?
                  AND (value >= ? OR is_breakout = 1)
                ORDER BY is_new DESC, is_breakout DESC, consecutive_days DESC, value DESC, keyword ASC
                """,
                (run_id, QueryType.RISING.value, int(run["rising_threshold"])),
            ).fetchall()

            failed_rows = conn.execute(
                """
                SELECT keyword, error_type, error_message
                FROM run_keywords
                WHERE run_id = ? AND status = 'failed'
                ORDER BY position ASC
                """,
                (run_id,),
            ).fetchall()

            pending_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM run_keywords WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            ).fetchone()
            pending_count = int(pending_row["cnt"] or 0)

        all_signals = [
            RisingSignal(
                keyword=str(row["keyword"]),
                related_query=str(row["related_query"]),
                value=int(row["value"]),
                is_breakout=bool(row["is_breakout"]),
                is_new=bool(row["is_new"]),
                geo=str(row["geo"] or run["geo"]),
                seen_count=int(row["seen_count"]),
                consecutive_days=int(row["consecutive_days"] or 1),
                previous_value=(
                    int(row["previous_value"]) if row["previous_value"] is not None else None
                ),
                previous_max_value=(
                    int(row["previous_max_value"])
                    if row["previous_max_value"] is not None
                    else None
                ),
                first_seen_date=row["first_seen_date"],
            )
            for row in rising_rows
        ]

        filtered_count = 0
        if query_filter is not None:
            all_signals, filtered_count = query_filter.filter_signals(all_signals)

        new_rising: list[RisingSignal] = []
        recurring_rising: list[RisingSignal] = []

        for signal in all_signals:
            if signal.is_new:
                if len(new_rising) < max_items_per_section:
                    new_rising.append(signal)
            else:
                if len(recurring_rising) < max_items_per_section:
                    recurring_rising.append(signal)

        failures = [
            FailedKeywordItem(
                keyword=str(row["keyword"]),
                error_type=str(row["error_type"] or "unknown_error"),
                error_message=str(row["error_message"] or "Failed"),
            )
            for row in failed_rows
        ]

        return RunReport(
            run_id=str(run["run_id"]),
            run_date=str(run["run_date"]),
            generated_at=str(run["finished_at"] or utc_now_iso()),
            timeframe=str(run["timeframe"]),
            resolved_timeframe=str(run["resolved_timeframe"]),
            geo=str(run["geo"]),
            rising_threshold=int(run["rising_threshold"]),
            total_keywords=int(run["total_keywords"]),
            succeeded_keywords=int(run["succeeded_keywords"]),
            failed_keywords=int(run["failed_keywords"]),
            pending_keywords=pending_count,
            filtered_count=filtered_count,
            new_rising=new_rising,
            recurring_rising=recurring_rising,
            failures=failures,
            csv_path=csv_path,
            output_dir=output_dir,
        )

    def query_history(
        self,
        *,
        keyword: str | None = None,
        new_only: bool = False,
        min_value: int | None = None,
        min_streak: int | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Query historical rising observations for CLI inspection or export."""
        clauses = ["query_type = ?"]
        params: list[Any] = [QueryType.RISING.value]

        if keyword:
            clauses.append("LOWER(keyword) = LOWER(?)")
            params.append(keyword.strip())
        if new_only:
            clauses.append("is_new = 1")
        if min_value is not None:
            clauses.append("(value >= ? OR is_breakout = 1)")
            params.append(min_value)
        if min_streak is not None:
            clauses.append("consecutive_days >= ?")
            params.append(min_streak)

        params.append(limit)
        sql = f"""
            SELECT run_date, keyword, related_query, value, is_breakout,
                   is_new, seen_count, consecutive_days, previous_value, geo, timeframe
            FROM observations
            WHERE {' AND '.join(clauses)}
            ORDER BY run_date DESC, is_new DESC, consecutive_days DESC, value DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
