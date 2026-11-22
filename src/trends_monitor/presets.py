"""Built-in keyword & filter presets for common discovery workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetDefinition:
    name: str
    description: str
    yaml_content: str


_COMMON_TAIL = """\
rate_limit:
  min_delay_seconds: 5.0
  max_delay_seconds: 12.0
  batch_size: 5
  batch_interval_seconds: 60.0
  max_retries: 3
  quota_backoff_seconds: 60.0

storage:
  data_dir: "data"
  db_path: "data/trends_history.sqlite3"
  save_raw_json: true
  save_csv: true

notifications:
  local:
    enabled: true
    formats: ["markdown", "html"]
  email:
    enabled: false
    smtp_server: ""
    smtp_port: 587
    use_ssl: null
    sender_email: ""
    sender_password: ""
    recipient_emails: []
    attach_csv: true
  feishu:
    enabled: false
    webhook_url: ""
  wecom:
    enabled: false
    webhook_url: ""
  webhook:
    enabled: false
    url: ""
    headers: {}
"""

PRESETS: dict[str, PresetDefinition] = {
    "default": PresetDefinition(
        name="default",
        description="Starter general-purpose monitor with example keywords.",
        yaml_content="""\
# TrendSpy Related Keywords Monitor Configuration (preset: default)
# Sensitive secrets (SMTP password, webhooks, proxies, API keys) should go in `.env`.

keywords:
  - "AI"
  - "Image"
  - "Video"
  - "Music"
  - "Voice"

trends:
  provider: "trendspy"    # "trendspy" (free) or "serpapi" (requires TRENDS_SERPAPI_KEY)
  timeframe: "now 7-d"
  geo: ""
  cat: 0
  language: "en"
  proxies: []             # Optional proxy pool; or set TRENDS_PROXY / TRENDS_PROXIES in .env

monitor:
  rising_threshold: 500
  breakout_threshold: 5000
  dedup_days: 7
  max_items_per_section: 50

filters:
  min_word_count: 1
  exclude_patterns:
    - "\\\\bdown\\\\b"
    - "\\\\blogin\\\\b"
    - "\\\\bsign in\\\\b"
    - "\\\\bstatus\\\\b"
  include_patterns: []

"""
        + _COMMON_TAIL,
    ),
    "saas-tools": PresetDefinition(
        name="saas-tools",
        description="Micro-SaaS & web tool demand discovery via intent-modifier seed roots.",
        yaml_content="""\
# TrendSpy Related Keywords Monitor Configuration (preset: saas-tools)
# Uses intent-modifier roots (generator, converter, calculator, etc.) to uncover
# actionable micro-SaaS and web-tool search demand with low news noise.

keywords:
  - "generator"
  - "converter"
  - "calculator"
  - "checker"
  - "formatter"
  - "template"
  - "alternative"
  - "maker"
  - keyword: "Python"
    cat: 31               # Google Trends category 31 = Programming (filters out snakes!)

trends:
  provider: "trendspy"
  timeframe: "now 7-d"
  geo: "US"
  cat: 0
  language: "en"
  proxies: []

monitor:
  rising_threshold: 300
  breakout_threshold: 5000
  dedup_days: 7
  max_items_per_section: 50

filters:
  min_word_count: 2
  exclude_patterns:
    - "\\\\bdown\\\\b"
    - "\\\\blogin\\\\b"
    - "\\\\bsign in\\\\b"
    - "\\\\bstatus\\\\b"
    - "\\\\breddit\\\\b"
    - "\\\\bwiki\\\\b"
    - "\\\\blyrics\\\\b"
    - "\\\\bmeaning\\\\b"
  include_patterns: []

"""
        + _COMMON_TAIL,
    ),
    "ai-products": PresetDefinition(
        name="ai-products",
        description="Emerging AI products, agents, workflows, and creative AI tools.",
        yaml_content="""\
# TrendSpy Related Keywords Monitor Configuration (preset: ai-products)
# Tracks emerging AI tools, agents, and media workflows while filtering outage chatter.

keywords:
  - keyword: "ai agent"
    cat: 5                # Computers & Electronics
  - keyword: "ai video"
    cat: 5
  - keyword: "ai voice"
    cat: 5
  - keyword: "ai generator"
    cat: 5
  - "mcp"
  - "workflow"
  - "prompt"

trends:
  provider: "trendspy"
  timeframe: "now 7-d"
  geo: ""
  cat: 0
  language: "en"
  proxies: []

monitor:
  rising_threshold: 500
  breakout_threshold: 5000
  dedup_days: 7
  max_items_per_section: 50

filters:
  min_word_count: 2
  exclude_patterns:
    - "\\\\bdown\\\\b"
    - "\\\\boutage\\\\b"
    - "\\\\blogin\\\\b"
    - "\\\\bstatus\\\\b"
    - "\\\\bstock\\\\b"
    - "\\\\bshare price\\\\b"
  include_patterns: []

"""
        + _COMMON_TAIL,
    ),
    "ecommerce": PresetDefinition(
        name="ecommerce",
        description="Product research & e-commerce trend discovery.",
        yaml_content="""\
# TrendSpy Related Keywords Monitor Configuration (preset: ecommerce)
# Monitors buyer-intent modifiers to spot rising consumer products early.

keywords:
  - "portable"
  - "mini"
  - "organizer"
  - "gift for"
  - "wireless"
  - "holder"
  - "kit"

trends:
  provider: "trendspy"
  timeframe: "now 7-d"
  geo: "US"
  cat: 18                 # Google Trends category 18 = Shopping
  language: "en"
  proxies: []

monitor:
  rising_threshold: 400
  breakout_threshold: 5000
  dedup_days: 7
  max_items_per_section: 50

filters:
  min_word_count: 2
  exclude_patterns:
    - "\\\\blogin\\\\b"
    - "\\\\bcustomer service\\\\b"
    - "\\\\bnear me\\\\b"
    - "\\\\bstore hours\\\\b"
  include_patterns: []

"""
        + _COMMON_TAIL,
    ),
}


def get_preset(name: str) -> PresetDefinition:
    key = name.strip().lower()
    if key not in PRESETS:
        available = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown preset {name!r}. Available presets: {available}")
    return PRESETS[key]
