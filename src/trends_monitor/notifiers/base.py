"""Base notifier interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from trends_monitor.models import NotifyResult, RunReport


class BaseNotifier(ABC):
    """Abstract notification channel."""

    name: str = "base"

    @abstractmethod
    def send(self, report: RunReport) -> NotifyResult:
        """Deliver a single consolidated RunReport."""

    @abstractmethod
    def check(self) -> tuple[bool, str]:
        """Verify configuration and (where safe) connectivity without sending spam."""
