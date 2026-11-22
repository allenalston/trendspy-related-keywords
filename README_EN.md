# TrendSpy Related Keywords Monitor

English | [简体中文](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/allenalston/trendspy-related-keywords/actions/workflows/ci.yml/badge.svg)](https://github.com/allenalston/trendspy-related-keywords/actions/workflows/ci.yml)

A lightweight, self-hostable **Google Trends Rising Related Keywords** monitoring CLI.

Built around one focused workflow: **Fixed seed keywords → Reliable collection → Cross-day deduplication → One low-noise daily digest.**

---

## Key Features

- **Zero-Friction Quickstart**: Generates local Markdown, HTML, and CSV reports out of the box—no SMTP or webhook setup required to test.
- **Cross-Day Deduplication (`New` Signals)**: Backed by a single-file SQLite database (`data/trends_history.sqlite3`). Newly observed rising queries are surfaced first while recurring ones are grouped with historical context.
- **Resilient Collection & Checkpointing**: Bounded retries with exponential backoff, structured error classification (`quota_exceeded`, `empty_response`, `network_error`), HTTP/SOCKS proxy support, and `--resume` support so partial HTTP 429 failures never waste completed work.
- **Single Consolidated Digest**: Sends **one** clean HTML + plain-text email per run (auto-supports both `465 SSL` and `587 STARTTLS` with optional CSV attachment), plus **Feishu (Lark), WeCom, and generic JSON Webhook** notifiers. Re-send any past digest with `trends-monitor notify`.
- **Serverless & Self-Hosted Ready**: Includes a turnkey **GitHub Actions daily workflow** (with Actions Cache SQLite persistence), Dockerfile, and `systemd` timer templates.

---

## 5-Minute Quickstart

### 1. Install (Python 3.10+)

```bash
git clone https://github.com/allenalston/trendspy-related-keywords.git
cd trendspy-related-keywords

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Try an Ad-Hoc Run Immediately

```bash
trends-monitor run -k AI -k Python --timeframe "now 7-d"
```

Outputs are written to `data/YYYY-MM-DD/`:
- `digest_YYYY-MM-DD.md` — Markdown digest
- `digest_YYYY-MM-DD.html` — Responsive HTML digest
- `daily_report_YYYY-MM-DD.csv` — Structured CSV dataset
- `raw/related_queries_*.json` — Raw per-keyword snapshots

### 3. Create Your Config

```bash
trends-monitor init
```

Edit `config.yaml` with your seed keywords and optional notification channels, store secrets in `.env`, then validate:

```bash
trends-monitor check
trends-monitor check --live
```

---

## CLI Reference

| Command | Description |
| --- | --- |
| `trends-monitor init` | Create starter `config.yaml` and `.env` |
| `trends-monitor run` | Collect keywords, deduplicate against history, export & notify |
| `trends-monitor run -k AI -k Video --geo US` | Override seed keywords and region for a quick run |
| `trends-monitor run --resume` | Resume the latest incomplete run (only retries unfinished keywords) |
| `trends-monitor run --no-notify` | Skip external email/webhook channels while saving local reports |
| `trends-monitor check [--live]` | Validate config, SQLite path, notifiers, and optional live Trends access |
| `trends-monitor notify [--date YYYY-MM-DD]` | Re-send a stored run's digest without re-querying Google Trends |
| `trends-monitor history --new-only --limit 30` | Inspect historical rising queries (supports `--export out.csv`) |

---

## Deployment Options

This tool is a **short-lived batch job** (no always-on web server, < 100MB RAM, single-file SQLite state). Choosing where to run it comes down to **cost, SQLite persistence, and how friendly the egress IP is to Google Trends rate limits (HTTP 429)**:

| Environment | Cost | 429 Risk | Cross-Day Persistence | Best For |
| --- | --- | --- | --- | --- |
| **GitHub Actions** (built-in) | Free | Medium-High (datacenter IP; add `TRENDS_PROXY` for 30+ keywords) | Built-in via `actions/cache` | Zero-server quickstart & small keyword lists |
| **Personal Mac / NAS / Raspberry Pi** | Free | **Lowest** (residential IP is far less likely to be rate-limited) | Native local SQLite | **Best for personal long-term use** if you have an always-on machine |
| **Small VPS** (`systemd` or Docker) | ~$3–5/mo | Medium (datacenter IP; tune delays or add proxy) | Native local SQLite | Heavy users tracking 30–100+ seed keywords |
| **PaaS Cron** (Railway / Render / Fly.io) | Free+ | Medium (datacenter IP) | Requires mounted volume for SQLite | Developers avoiding manual Linux ops |

> **Tip**: Avoid short-timeout serverless platforms (like Vercel or Cloudflare Pages), since polite pacing delays across multiple keywords typically take several minutes.

- **GitHub Actions (Serverless / Free)**: Fork the repo, add your `config.yaml`, configure optional Secrets (`TRENDS_SMTP_*`, `TRENDS_FEISHU_WEBHOOK`, `TRENDS_PROXY`, etc.), and run [`.github/workflows/daily-monitor.yml`](.github/workflows/daily-monitor.yml). SQLite history is preserved across daily runs via `actions/cache`, and daily outputs are uploaded as 30-day Artifacts.
- **Docker**: Copy `config.example.yaml` → `config.yaml`, `.env.example` → `.env`, and run `docker compose run --rm trends-monitor`.
- **Linux `systemd` Timer**: See [`deploy/systemd/`](deploy/systemd/).

---

## Data Semantics & Rate Limits

- **Relative Growth Signal**: Rising percentages (e.g., `+1,200%` or `Breakout`) are relative Google Trends signals within the selected timeframe—not absolute search volume or SEO difficulty.
- **Meaning of `New`**: `New` means first recorded by this monitor (or resurfaced after `monitor.dedup_days`), not first appearance on the internet.
- **Handling HTTP 429**: Prefer `"now 7-d"` or `"now 1-d"`. For large keyword lists (30+), increase delays in `rate_limit` or configure `TRENDS_PROXY` in `.env`. Any failed keywords are logged clearly in the digest and can be retried later via `trends-monitor run --resume`.

---

## Upgrading from v0.1.0

- The original v0.1.0 script is preserved at tag `v0.1.0`.
- Legacy `itchat-uos` personal WeChat login was removed due to severe account-ban risks and protocol breakage. Use Email, Feishu, WeCom, or Generic Webhook instead.
- Configuration moved from editing `config.py` to `config.yaml` + `.env`.

## License

[MIT License](LICENSE)
