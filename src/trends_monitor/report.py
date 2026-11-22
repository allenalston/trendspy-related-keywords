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


def format_momentum_tags(signal: RisingSignal) -> list[str]:
    """Return zero-API-cost momentum indicators computed from historical SQLite runs."""
    tags: list[str] = []
    if signal.is_streak:
        tags.append(f"🔥 {signal.consecutive_days}d streak")
    if signal.is_accelerating and signal.previous_value is not None:
        tags.append(f"🚀 +{signal.previous_value:,}%→+{signal.value:,}%")
    return tags


def trends_explore_url(query: str, geo: str = "") -> str:
    """Build a direct Google Trends Explore link for quick manual verification."""
    encoded = quote_plus(query)
    if geo:
        return f"https://trends.google.com/trends/explore?q={encoded}&geo={quote_plus(geo)}"
    return f"https://trends.google.com/trends/explore?q={encoded}"


def google_search_url(query: str) -> str:
    """Build a direct Google Search link to understand what the query is about."""
    return f"https://www.google.com/search?q={quote_plus(query)}"


def google_exact_url(query: str) -> str:
    """Build an exact-match Google Search link to gauge SERP competition."""
    quoted = f'"{query}"'
    return f"https://www.google.com/search?q={quote_plus(quoted)}"


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
    progress_text = f"**{report.succeeded_keywords} / {report.total_keywords}** succeeded ({report.failed_keywords} failed"
    if report.pending_keywords > 0:
        progress_text += f", {report.pending_keywords} pending"
    progress_text += ")"

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
        f"| Keywords Processed | {progress_text} |",
        f"| New Rising Signals | **{len(report.new_rising)}** |",
        f"| Recurring Rising Signals | **{len(report.recurring_rising)}** |",
    ]
    if report.filtered_count > 0:
        lines.append(f"| Noise Filtered Out | `{report.filtered_count}` |")
    lines.append("")

    lines.append(f"## ✨ New Rising Queries ({len(report.new_rising)})")
    lines.append("")
    if report.new_rising:
        lines.append("| Seed Keyword | Related Query | Growth | Quick Check |")
        lines.append("| --- | --- | ---: | --- |")
        for item in report.new_rising:
            geo = item.geo or report.geo
            t_url = trends_explore_url(item.related_query, geo)
            g_url = google_search_url(item.related_query)
            e_url = google_exact_url(item.related_query)
            lines.append(
                f"| {item.keyword} | **{item.related_query}** | {format_growth(item)} "
                f"| [Trends]({t_url}) · [Google]({g_url}) · [Exact]({e_url}) |"
            )
    else:
        lines.append("_No newly discovered rising queries exceeded the threshold in this run._")
    lines.append("")

    if report.recurring_rising:
        lines.append(f"## 📈 Recurring Rising Queries ({len(report.recurring_rising)})")
        lines.append("")
        lines.append("| Seed Keyword | Related Query | Growth | Momentum | Seen | Quick Check |")
        lines.append("| --- | --- | ---: | --- | ---: | --- |")
        for item in report.recurring_rising:
            geo = item.geo or report.geo
            tags = " / ".join(format_momentum_tags(item)) or "-"
            t_url = trends_explore_url(item.related_query, geo)
            g_url = google_search_url(item.related_query)
            e_url = google_exact_url(item.related_query)
            lines.append(
                f"| {item.keyword} | {item.related_query} | {format_growth(item)} "
                f"| {tags} | {item.seen_count}x | [Trends]({t_url}) · [Google]({g_url}) · [Exact]({e_url}) |"
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
            "> - **Streak / Accelerating** tags are computed purely from local SQLite history with zero extra API requests.",
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
        f"Keywords:  {report.succeeded_keywords}/{report.total_keywords} succeeded ({report.failed_keywords} failed, {report.pending_keywords} pending)",
        f"Signals:   {len(report.new_rising)} New, {len(report.recurring_rising)} Recurring (threshold >= +{report.rising_threshold}%)",
    ]
    if report.filtered_count > 0:
        lines.append(f"Filtered:  {report.filtered_count} noise queries excluded by filter rules")
    lines.append("")

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
            tags = format_momentum_tags(item)
            suffix = f" | {', '.join(tags)}" if tags else ""
            lines.append(
                f"  [{item.keyword}] {item.related_query}  -->  {format_growth(item)} (seen {item.seen_count}x{suffix})"
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


def _render_html_signal_rows(items: list[RisingSignal], default_geo: str, *, show_history: bool) -> str:
    rows: list[str] = []
    for item in items:
        kw = html.escape(item.keyword)
        q = html.escape(item.related_query)
        geo = item.geo or default_geo
        t_url = html.escape(trends_explore_url(item.related_query, geo))
        g_url = html.escape(google_search_url(item.related_query))
        e_url = html.escape(google_exact_url(item.related_query))

        quick_links = (
            f"<div style='margin-top:3px;font-size:11px;'>"
            f"<a href='{t_url}' style='color:#2563eb;text-decoration:none;'>Trends</a> &middot; "
            f"<a href='{g_url}' style='color:#4b5563;text-decoration:none;'>Google</a> &middot; "
            f"<a href='{e_url}' style='color:#4b5563;text-decoration:none;'>Exact</a>"
            f"</div>"
        )

        badges: list[str] = []
        if item.is_breakout:
            badges.append(
                '<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                'background:#fee2e2;color:#991b1b;font-size:11px;font-weight:600;">BREAKOUT</span>'
            )
        if item.is_streak:
            badges.append(
                f'<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                f'background:#fef3c7;color:#92400e;font-size:11px;font-weight:600;">🔥 {item.consecutive_days}d</span>'
            )
        if item.is_accelerating and item.previous_value is not None:
            badges.append(
                f'<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                f'background:#dcfce7;color:#166534;font-size:11px;font-weight:600;">'
                f'🚀 +{item.previous_value:,}%→+{item.value:,}%</span>'
            )
        badge_html = (" ".join(badges) + " ") if badges else ""
        growth = f"{badge_html}<strong>+{item.value:,}%</strong>"

        if show_history:
            prev_max = f"+{item.previous_max_value:,}%" if item.previous_max_value is not None else "-"
            rows.append(
                f"<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top;'>{kw}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top;'>"
                f"<div style='font-weight:500;color:#111827;'>{q}</div>{quick_links}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#15803d;vertical-align:top;'>{growth}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#6b7280;vertical-align:top;font-size:12px;'>"
                f"{item.seen_count}x<br/>max {prev_max}</td>"
                f"</tr>"
            )
        else:
            rows.append(
                f"<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;font-weight:600;vertical-align:top;'>{kw}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top;'>"
                f"<div style='font-weight:600;color:#111827;'>{q}</div>{quick_links}</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:right;color:#15803d;vertical-align:top;'>{growth}</td>"
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
              <th style="padding:8px 10px;border-bottom:2px solid #e5e7eb;text-align:right;">Growth &amp; Momentum</th>
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

    filter_note = (
        f" &nbsp;•&nbsp; Noise Filtered: <strong>{report.filtered_count}</strong>"
        if report.filtered_count > 0
        else ""
    )
    pending_note = (
        f" ({report.pending_keywords} pending)"
        if report.pending_keywords > 0
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(build_subject(report))}</title>
</head>
<body style="margin:0;padding:16px;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">
  <div style="max-width:740px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb;">
    <div style="background:#111827;color:#ffffff;padding:20px 24px;">
      <div style="font-size:12px;letter-spacing:0.06em;text-transform:uppercase;color:#9ca3af;">Google Trends Monitor</div>
      <h1 style="margin:6px 0 0;font-size:20px;font-weight:700;">Rising Related Keywords Digest — {html.escape(report.run_date)}</h1>
      <div style="margin-top:8px;font-size:13px;color:#d1d5db;">
        Timeframe: <strong>{html.escape(report.timeframe)}</strong> ({html.escape(report.resolved_timeframe)}) &nbsp;•&nbsp;
        Region: <strong>{html.escape(report.geo_display)}</strong> &nbsp;•&nbsp;
        Threshold: <strong>&ge; +{report.rising_threshold}%</strong>{filter_note}
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
            <div style="font-size:12px;color:#4b5563;">Succeeded{html.escape(pending_note)}</div>
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
        Streak &amp; accelerating badges are computed from local SQLite history with zero extra requests.
      </p>
    </div>
  </div>
</body>
</html>
"""
