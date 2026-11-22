# Contributing

Thank you for considering contributing to **TrendSpy Related Keywords Monitor**!

## Guiding Principle

> **Do one thing exceptionally well: monitor rising related keywords.**

We intentionally keep this project lightweight, predictable, and easy to self-host. Before proposing large features (such as full web dashboards or multi-platform scrapers), please open an issue to discuss scope first.

## Development Setup

```bash
git clone https://github.com/allenalston/trendspy-related-keywords.git
cd trendspy-related-keywords
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Checks

Before opening a pull request, please ensure linting and tests pass:

```bash
ruff check src tests
pytest
```

## Pull Request Checklist

- Keep changes focused and well-scoped.
- Add or update unit tests in `tests/` for new behavior or bug fixes.
- Avoid committing secrets, `.env`, `config.yaml`, or runtime `data/` artifacts.
