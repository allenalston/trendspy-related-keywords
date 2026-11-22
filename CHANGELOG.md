# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-11-22

### Added
- **Per-keyword category/region/timeframe overrides**: `keywords` now accepts both simple strings and structured objects (`{keyword, cat, geo, timeframe}`), e.g., monitoring `"Python"` with `cat: 31` (Programming) to eliminate unrelated noise.
- **Noise-reduction filter engine (`filters`)**: Case-insensitive regex `exclude_patterns`, optional `include_patterns` whitelist, and `min_word_count` filtering, with filtered noise counts summarized in the digest.
- **Zero-API-cost momentum signals**: Local SQLite history now tracks `consecutive_days` (`🔥 3d streak`) and growth acceleration (`🚀 +500%→+2,400%`) without extra Google Trends requests, plus `trends-monitor history --min-streak`.
- **Built-in starter presets**: `trends-monitor init --preset <name>` (`default`, `saas-tools`, `ai-products`, `ecommerce`) and `--list-presets`.
- **Quick-decision links in digests**: Every rising query includes one-click **Trends · Google · Exact** links for 3-second opportunity & SERP competition checks.
- **Proxy pool rotation & sharded execution**: Support for `trends.proxies` / `TRENDS_PROXIES` auto-rotation on 429/network errors, and `trends-monitor run --limit N` paired with `--resume` to spread large keyword lists across multiple runs.
- **Optional SerpApi provider**: Pluggable `trends.provider: "serpapi"` (`TRENDS_SERPAPI_KEY`) for heavy users who want zero Google 429 interruptions.
- **Automatic SQLite schema migration**: Seamless in-place upgrade for existing v0.2.0 `trends_history.sqlite3` databases.

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
