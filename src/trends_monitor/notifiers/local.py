"""Local filesystem report writer (Markdown and HTML)."""

from __future__ import annotations

from pathlib import Path

from trends_monitor.config import LocalNotificationSettings
from trends_monitor.models import NotifyResult, RunReport
from trends_monitor.notifiers.base import BaseNotifier
from trends_monitor.report import render_html, render_markdown


class LocalFileNotifier(BaseNotifier):
    """Writes digest reports to the local output directory."""

    name = "local"

    def __init__(self, settings: LocalNotificationSettings, base_data_dir: str | Path) -> None:
        self.settings = settings
        self.base_data_dir = Path(base_data_dir)

    def send(self, report: RunReport) -> NotifyResult:
        output_dir = report.output_dir or (self.base_data_dir / report.run_date)
        output_dir.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        try:
            if "markdown" in self.settings.formats:
                md_path = output_dir / f"digest_{report.run_date}.md"
                md_path.write_text(render_markdown(report), encoding="utf-8")
                written.append(md_path)

            if "html" in self.settings.formats:
                html_path = output_dir / f"digest_{report.run_date}.html"
                html_path.write_text(render_html(report), encoding="utf-8")
                written.append(html_path)

            return NotifyResult(
                channel=self.name,
                success=True,
                message=f"Saved {len(written)} local report file(s) to {output_dir}",
                artifacts=written,
            )
        except Exception as exc:
            return NotifyResult(
                channel=self.name,
                success=False,
                message=f"Failed to write local report: {exc}",
            )

    def check(self) -> tuple[bool, str]:
        try:
            self.base_data_dir.mkdir(parents=True, exist_ok=True)
            return True, f"Writable local directory: {self.base_data_dir}"
        except Exception as exc:
            return False, f"Cannot access local directory {self.base_data_dir}: {exc}"
