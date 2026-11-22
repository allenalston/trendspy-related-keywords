"""Noise-reduction query filter engine (exclude/include regexes and minimum word count)."""

from __future__ import annotations

import re

from trends_monitor.config import FilterSettings
from trends_monitor.models import RisingSignal


class QueryFilter:
    """Filters low-signal related queries before rendering digest reports."""

    def __init__(self, settings: FilterSettings) -> None:
        self.settings = settings
        self._exclude = [re.compile(p, re.IGNORECASE) for p in settings.exclude_patterns]
        self._include = [re.compile(p, re.IGNORECASE) for p in settings.include_patterns]

    def matches(self, query: str) -> bool:
        """Return True if the related query passes word-count, exclude, and include rules."""
        text = query.strip()
        if not text:
            return False

        if self.settings.min_word_count > 1:
            words = [w for w in text.split() if w]
            if len(words) < self.settings.min_word_count:
                return False

        if any(pattern.search(text) for pattern in self._exclude):
            return False

        if self._include and not any(pattern.search(text) for pattern in self._include):
            return False

        return True

    def filter_signals(self, signals: list[RisingSignal]) -> tuple[list[RisingSignal], int]:
        """Partition signals into kept items and count of filtered-out noise items."""
        kept: list[RisingSignal] = []
        dropped = 0
        for signal in signals:
            if self.matches(signal.related_query):
                kept.append(signal)
            else:
                dropped += 1
        return kept, dropped
