"""Structured digest report rendering (Markdown, HTML email, and plain text)."""

from __future__ import annotations

import html
from urllib.parse import quote_plus

from trends_monitor.models import RisingSignal, RunReport


def format_growth(signal: RisingSignal) -> str:
    """Format a growth percentage with clear Breakout indicator."""
    if signal.is_breakout:
        return f"Breakout (+{signal.value:,}%)"
    return f"+{signal.value:,}%"


def trends_explore_url(query: str, geo: str = "") -> str:
    """Build a direct Google Trends Explore link for quick manual verification."""
    encoded = quote_plus(query)
    if geo:
        return f"https://trends.google.com/trends/explore?q={encoded}&geo={quote_plus(geo)}"
    return f"https://trends.google.com/trends/explore?q={encoded}"


def build_subject(report: RunReport) -> str:
    """Create a concise, informative subject line for email and chat digests."""
    new_count = len(report.new_rising)
    rec_count = len(report.recurring_rising)
    parts = [f"Trends Digest ({report.run_date})"]
    if new_count > 0:
        parts.append(f"{new_count} New Rising")
    elif rec_count > 0:
        parts.append(f"{rec_count} Rising")
    else:
        parts.append("No High-Rising Signals")
    if report.failed_keywords > 0:
        parts.append(f"{report.failed_keywords} Failed")
    return " | ".join(parts)


def render_markdown(report: RunReport) -> str:
    """Render a clean Markdown report suitable for local archiving or chat platforms."""
    lines: list[str] = [
        f"# Google Trends Rising Keywords Digest — {report.run_date}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Run ID | `{report.run_id}` |",
        f"| Timeframe | `{report.timeframe}` (`{report.resolved_timeframe}`) |",
        f"| Region | `{report.geo_display}` |",
        f"| Rising Threshold | `>= +{report.rising_threshold}%` |",
        f"| Keywords Processed | **{report.succeeded_keywords} / {report.total_keywords}** succeeded ({report.failed_keywords} failed) |",
        f"| New Rising Signals | **{len(report.new_rising)}** |",
        f"| Recurring Rising Signals | **{len(report.recurring_rising)}** |",
        "",
    ]

    lines.append(f"## ✨ New Rising Queries ({len(report.new_rising)})")
    lines.append("")
    if report.new_rising:
        lines.append("| Seed Keyword | Related Query | Growth | Explore |")
        lines.append("| --- | --- | ---: | --- |")
        for item in report.new_rising:
            url = trends_explore_url(item.related_query, report.geo)
            lines.append(
                f"| {item.keyword} | **{item.related_query}** | {format_growth(item)} | [View]({url}) |"
            )
    else:
        lines.append("_No newly discovered rising queries exceeded the threshold in this run._")
    lines.append("")

    if report.recurring_rising:
        lines.append(f"## 📈 Recurring Rising Queries ({len(report.recurring_rising)})")
        lines.append("")
        lines.append("| Seed Keyword | Related Query | Current Growth | Seen | Prev Max | First Seen |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for item in report.recurring_rising:
            prev_max = f"+{item.previous_max_value:,}%" if item.previous_max_value is not None else "-"
            first_seen = item.first_seen_date or "-"
            lines.append(
                f"| {item.keyword} | {item.related_query} | {format_growth(item)} "
                f"| {item.seen_count}x | {prev_max} | {first_seen} |"
            )
        lines.append("")

    if report.failures:
        lines.append(f"## ⚠️ Failed Keywords ({len(report.failures)})")
        lines.append("")
        lines.append("| Keyword | Error Type | Details |")
        lines.append("| --- | --- | --- |")
        for fail in report.failures:
            safe_msg = fail.error_message.replace("\n", " ").replace("|", "\\|")[:160]
            lines.append(f"| {fail.keyword} | `{fail.error_type}` | {safe_msg} |")
        lines.append("")

    lines.extend(
        [
            "---",
            "> **Notes:**",
            "> - Growth percentages are relative Google Trends signals within the selected timeframe, not absolute search volume.",
            "> - **New** means first observed by this monitor (or resurfaced after the configured deduplication window).",
        ]
    )
    return "\n".join(lines) + "\n"


def render_plain_text(report: RunReport) -> str:
    """Render a compact plain-text digest (also used as multipart email fallback)."""
    lines = [
        f"Google Trends Rising Keywords Digest - {report.run_date}",
        "=" * 56,
        f"Timeframe: {report.timeframe} ({report.resolved_timeframe})",
        f"Region:    {report.geo_display}",
        f"Keywords:  {report.succeeded_keywords}/{report.total_keywords} succeeded ({report.failed_keywords} failed)",
        f"Signals:   {len(report.new_rising)} New, {len(report.recurring_rising)} Recurring (threshold >= +{report.rising_threshold}%)",
        "",
    ]

    lines.append(f"NEW RISING QUERIES ({len(report.new_rising)})")
    lines.append("-" * 40)
    if report.new_rising:
        for item in report.new_rising:
            lines.append(f"  [{item.keyword}] {item.related_query}  -->  {format_growth(item)}")
    else:
        lines.append("  None in this run.")
    lines.append("")

    if report.recurring_rising:
        lines.append(f"RECURRING RISING QUERIES ({len(report.recurring_rising)})")
        lines.append("-" * 40)
        for item in report.recurring_rising:
            lines.append(
                f"  [{item.keyword}] {item.related_query}  -->  {format_growth(item)} (seen {item.seen_count}x)"
            )
        lines.append("")

    if report.failures:
        lines.append(f"FAILED KEYWORDS ({len(report.failures)})")
        lines.append("-" * 40)
        for fail in report.failures:
            lines.append(f"  - {fail.keyword} [{fail.error_type}]: {fail.error_message[:140]}")
        lines.append("")

    lines.append(
        "Note: Rising % is a relative Google Trends signal, not absolute search volume. "
        "'New' means first seen by this monitor within the dedup window."
    )
    return "\n".join(lines)


def _render_html_signal_rows(items: list[RisingSignal], geo: str, *, show_history: bool) -> str:
    rows: list[str] = []
    for item in items:
        kw = html.escape(item.keyword)
        q = html.escape(item.related_query)
        url = html.escape(trends_explore_url(item.related_query, geo))
        badge = (
            '<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
            'background:#fee2e2;color:#991b1b;font-size:11px;font-weight:600;">BREAKOUT</span> '
            if item.is_breakout
            else ""
        )
        growth = f"{badge}<strong>+{item.value:,}%</strong>"
        if show_history:
            prev_max = f"+{item.previous_max_value:,}%" if item.previous_max_value is not None else "-"
            rows.append(
                f"<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;'>{kw}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;'>"
                f"<a href='{url}' style='color:#1d4ed8;text-decoration:none;'>{q}</a></td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#15803d;'>{growth}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#6b7280;'>"
                f"{item.seen_count}x (max {prev_max})</td>"
                f"</tr>"
            )
        else:
            rows.append(
                f"<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;font-weight:600;'>{kw}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;'>"
                f"<a href='{url}' style='color:#1d4ed8;text-decoration:none;font-weight:600;'>{q}</a></td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#15803d;'>{growth}</td>"
                f"</tr>"
            )
    return "\n".join(rows)


def render_html(report: RunReport) -> str:
    """Render a single self-contained, mobile-friendly HTML digest email."""
    new_section = (
        f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;margin-top:8px;">
          <thead>
            <tr style="background:#f3f4f6;text-align:left;color:#374151;">
              <th style="padding:8px 10px;border-bottom:2px solid #d1d5db;">Seed Keyword</th>
              <th style="padding:8px 10px;border-bottom:2px solid #d1d5db;">Related Query</th>
              <th style="padding:8px 10px;border-bottom:2px solid #d1d5db;text-align:right;">Growth</th>
            </tr>
          </thead>
          <tbody>
            {_render_html_signal_rows(report.new_rising, report.geo, show_history=False)}
          </tbody>
        </table>
        """
        if report.new_rising
        else '<p style="color:#6b7280;font-size:14px;">No newly discovered rising queries exceeded the threshold in this run.</p>'
    )

    recurring_section = ""
    if report.recurring_rising:
        recurring_section = f"""
        <h2 style="font-size:16px;color:#111827;margin:24px 0 8px;">📈 Recurring Rising Queries ({len(report.recurring_rising)})</h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
          <thead>
            <tr style="background:#f9fafb;text-align:left;color:#4b5563;">
              <th style="padding:8px 10px;border-bottom:2px solid #e5e7eb;">Seed Keyword</th>
              <th style="padding:8px 10px;border-bottom:2px solid #e5e7eb;">Related Query</th>
              <th style="padding:8px 10px;border-bottom:2px solid #e5e7eb;text-align:right;">Growth</th>
              <th style="padding:8px 10px;border-bottom:2px solid #e5e7eb;text-align:right;">History</th>
            </tr>
          </thead>
          <tbody>
            {_render_html_signal_rows(report.recurring_rising, report.geo, show_history=True)}
          </tbody>
        </table>
        """

    failure_section = ""
    if report.failures:
        fail_rows = "\n".join(
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #fecaca;'>{html.escape(f.keyword)}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #fecaca;'><code>{html.escape(f.error_type)}</code></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #fecaca;color:#7f1d1d;'>{html.escape(f.error_message[:180])}</td>"
            f"</tr>"
            for f in report.failures
        )
        failure_section = f"""
        <h2 style="font-size:16px;color:#991b1b;margin:24px 0 8px;">⚠️ Failed Keywords ({len(report.failures)})</h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;background:#fef2f2;">
          <thead>
            <tr style="text-align:left;color:#991b1b;">
              <th style="padding:6px 10px;border-bottom:1px solid #fca5a5;">Keyword</th>
              <th style="padding:6px 10px;border-bottom:1px solid #fca5a5;">Error Type</th>
              <th style="padding:6px 10px;border-bottom:1px solid #fca5a5;">Details</th>
            </tr>
          </thead>
          <tbody>{fail_rows}</tbody>
        </table>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(build_subject(report))}</title>
</head>
<body style="margin:0;padding:16px;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">
  <div style="max-width:720px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb;">
    <div style="background:#111827;color:#ffffff;padding:20px 24px;">
      <div style="font-size:12px;letter-spacing:0.06em;text-transform:uppercase;color:#9ca3af;">Google Trends Monitor</div>
      <h1 style="margin:6px 0 0;font-size:20px;font-weight:700;">Rising Related Keywords Digest — {html.escape(report.run_date)}</h1>
      <div style="margin-top:8px;font-size:13px;color:#d1d5db;">
        Timeframe: <strong>{html.escape(report.timeframe)}</strong> ({html.escape(report.resolved_timeframe)}) &nbsp;•&nbsp;
        Region: <strong>{html.escape(report.geo_display)}</strong> &nbsp;•&nbsp;
        Threshold: <strong>&ge; +{report.rising_threshold}%</strong>
      </div>
    </div>

    <div style="padding:20px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;margin:0 -8px 16px;">
        <tr>
          <td style="background:#eff6ff;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#1d4ed8;">{len(report.new_rising)}</div>
            <div style="font-size:12px;color:#1e40af;">New Rising</div>
          </td>
          <td style="background:#f0fdf4;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#15803d;">{len(report.recurring_rising)}</div>
            <div style="font-size:12px;color:#166534;">Recurring Rising</div>
          </td>
          <td style="background:#f9fafb;border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#111827;">{report.succeeded_keywords}/{report.total_keywords}</div>
            <div style="font-size:12px;color:#4b5563;">Succeeded</div>
          </td>
          <td style="background:{'#fef2f2' if report.failed_keywords else '#f9fafb'};border-radius:8px;padding:12px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:{'#b91c1c' if report.failed_keywords else '#6b7280'};">{report.failed_keywords}</div>
            <div style="font-size:12px;color:{'#991b1b' if report.failed_keywords else '#6b7280'};">Failed</div>
          </td>
        </tr>
      </table>

      <h2 style="font-size:16px;color:#111827;margin:16px 0 8px;">✨ New Rising Queries ({len(report.new_rising)})</h2>
      {new_section}
      {recurring_section}
      {failure_section}

      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 12px;" />
      <p style="font-size:12px;color:#6b7280;line-height:1.5;margin:0;">
        Run ID: <code>{html.escape(report.run_id)}</code>. Rising percentages are relative Google Trends signals within the selected window, not absolute search volume.
        "New" indicates the query was first recorded by this monitor (or resurfaced after the configured deduplication window).
      </p>
    </div>
  </div>
</body>
</html>
"""
