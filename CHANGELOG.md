# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-11-22

### Added
- Standard Python package structure (`pyproject.toml`, `src/trends_monitor/`) with `trends-monitor` CLI (`init`, `run`, `check`, `notify`, `history`).
- Externalized YAML + `.env` configuration with Pydantic validation (`config.example.yaml`, `.env.example`).
- SQLite historical storage (`data/trends_history.sqlite3`) supporting cross-day deduplication (`New` vs `Recurring` signals) and crash-safe `--resume` checkpointing.
- Single consolidated digest report renderer in Markdown, responsive HTML, plain-text, and CSV formats.
- Pluggable notification channels: Local files (default, zero-config), SMTP Email (auto-supports 465 SSL & 587 STARTTLS), Feishu bot, WeCom bot, and generic JSON Webhook.
- Proxy support (`trends.proxy` / `TRENDS_PROXY`), bounded exponential backoff retries, structured error classification, and safe handling of empty DataFrames / Breakout values.
- Turnkey deployment templates: GitHub Actions daily monitor with SQLite cache persistence, Dockerfile, docker-compose, and `systemd` timer.
- Automated `pytest` test suite, `ruff` linting, GitHub Actions CI, MIT License, and bilingual documentation.

### Changed
- Default timeframe changed to `now 7-d` (more reliable for rising queries than custom short date ranges; `last-N-d` remains supported).
- Email credentials are no longer required when running local-only or webhook-only modes.

### Removed
- Removed accidentally committed virtual environment artifacts (`bin/`, `share/`, `pyvenv.cfg`).
- Removed deprecated `itchat-uos` personal WeChat login due to protocol breakage and account suspension risks.
- Removed legacy `urllib3<2.0.0` pin and `TRENDS_NID` env placeholder.

## [0.1.0] - 2025-01-17

- Initial script release archived under Git tag `v0.1.0`.
