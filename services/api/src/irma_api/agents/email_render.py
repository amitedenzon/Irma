"""render_daily_email — plain-text + HTML versions of the morning brief.

Plain text is the fallback. HTML matches Irma's warm-beige / wax-seal-red
design system (mirrors styles.css). All layout styles are inline so Gmail
doesn't strip them; Google Fonts are loaded via <style> for clients that
support it (Apple Mail, Outlook Web, Fastmail) with graceful fallback.
"""

from __future__ import annotations

import html as _html
from datetime import date

from irma_api.models.daily_brief import DailyBrief

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ── Irma palette (mirrors apps/desktop/src/styles.css) ─────────────────────
_BG            = "#f5ece0"   # warm beige page background
_SURFACE       = "#fdfaf4"   # paper-white card
_SURFACE2      = "#efe5d4"   # slightly darker beige (callout bg)
_BORDER        = "#e0d0b3"   # tan divider / card border
_BORDER_STRONG = "#c2b08c"   # stronger tan
_INK           = "#2a1f17"   # dark brown — primary text
_INK_MUTE      = "#7a6a52"   # medium brown — secondary
_INK_FAINT     = "#a8967a"   # faint brown — tertiary / labels
_RED           = "#b8341c"   # wax-seal red — brand accent
_RED_LIGHT     = "rgba(184,52,28,0.10)"
_AMBER         = "#c98a1a"   # amber — due-soon
_AMBER_LIGHT   = "rgba(201,138,26,0.12)"

# Font stacks — Google Fonts requested in <style>; safe fallbacks in inline CSS
_SANS = "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
_MONO = "'Fira Code', 'Courier New', Courier, monospace"


# ── Shared helpers ──────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    """YYYY-MM-DD → dd/MM (Weekday)"""
    try:
        d = date.fromisoformat(iso)
        return f"{d.strftime('%d/%m')} ({_DAYS[d.weekday()]})"
    except (ValueError, AttributeError):
        return iso


def _e(text: str) -> str:
    return _html.escape(str(text))


# ── Plain text ──────────────────────────────────────────────────────────────

def render_daily_email(brief: DailyBrief, today: date) -> tuple[str, str]:
    subject = f"Irma · Daily Brief — {today.strftime('%a %d %b')}"
    lines: list[str] = []

    if brief.narrative:
        lines += [brief.narrative, ""]

    if brief.progress:
        if brief.has_baseline:
            lines.append("Progress since your last brief")
            for p in brief.progress:
                lines.append(
                    f"  • {p.project_name}: {p.completed_since} done, "
                    f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
                )
        else:
            lines.append("Project status (first brief — no prior baseline yet)")
            for p in brief.progress:
                lines.append(f"  • {p.project_name}: {p.open_now} open / {p.done_now} done")
        lines.append("")

    if brief.today_focus or brief.lookahead_tasks:
        lines.append("Focus & upcoming")
        for f in brief.today_focus:
            if f.due_date:
                d = date.fromisoformat(f.due_date) if f.due_date else None
                suffix = " (today)" if d == today else f" (due {_fmt_date(f.due_date)})"
            else:
                suffix = ""
            proj = f" [{f.project_name}]" if f.project_name else ""
            lines.append(f"  • {f.title}{proj}{suffix}")
        for it in brief.lookahead_tasks:
            proj = f" [{it.project_name}]" if it.project_name else ""
            lines.append(f"  • {it.title}{proj} (due {_fmt_date(it.when)})")
        lines.append("")

    if brief.calendar_text:
        lines.append(brief.calendar_text)
        lines.append("")

    if brief.conflicts:
        lines.append("Heads-up")
        for c in brief.conflicts:
            lines.append(f"  • {c}")
        lines.append("")

    if brief.recommendation:
        lines.append(brief.recommendation)

    return subject, "\n".join(lines).rstrip() + "\n"


# ── HTML ────────────────────────────────────────────────────────────────────

def render_daily_email_html(brief: DailyBrief, today: date) -> str:
    day_name  = today.strftime("%A")           # Monday
    date_part = today.strftime("%d %b %Y")     # 01 Jun 2026
    sections: list[str] = []

    # ── Narrative ──
    if brief.narrative:
        sections.append(
            f'<p style="margin:0;color:{_INK};font-size:15px;line-height:1.8;font-family:{_SANS};">'
            f'{_e(brief.narrative)}</p>'
        )

    # ── Progress ──
    if brief.progress:
        title = "Progress since your last brief" if brief.has_baseline else "Project status"
        rows: list[str] = []
        for p in brief.progress:
            if brief.has_baseline:
                delta = (
                    f'<span style="color:{_INK_MUTE};font-size:12px;font-family:{_MONO};">'
                    f'{p.completed_since} done &nbsp;·&nbsp; {p.added_since} added'
                    f'</span>'
                    f'&ensp;<span style="color:{_INK_MUTE};font-size:12px;font-family:{_MONO};">'
                    f'{p.open_now} open / {p.done_now} done</span>'
                )
            else:
                delta = (
                    f'<span style="color:{_INK_MUTE};font-size:12px;font-family:{_MONO};">'
                    f'{p.open_now} open / {p.done_now} done</span>'
                )
            rows.append(
                f'<tr>'
                f'<td style="padding:8px 0;border-bottom:1px solid {_BORDER};'
                f'color:{_INK};font-size:14px;font-weight:600;font-family:{_SANS};">'
                f'{_e(p.project_name)}</td>'
                f'<td style="padding:8px 0 8px 16px;border-bottom:1px solid {_BORDER};'
                f'text-align:right;white-space:nowrap;">{delta}</td>'
                f'</tr>'
            )
        inner = f'<table style="width:100%;border-collapse:collapse;">{"".join(rows)}</table>'
        sections.append(_section(title, inner))

    # ── Focus & upcoming (today's focus + lookahead merged) ──
    all_task_items: list[str] = []

    for f in brief.today_focus:
        badge = _due_badge(f.due_date, today) if f.due_date else ""
        proj = (
            f'<span style="color:{_INK_MUTE};font-size:12px;margin-left:6px;">'
            f'[{_e(f.project_name)}]</span>'
            if f.project_name else ""
        )
        all_task_items.append(_task_row(f.title + (proj or ""), badge))

    for it in brief.lookahead_tasks:
        badge = _due_badge(it.when, today)
        proj = (
            f'<span style="color:{_INK_MUTE};font-size:12px;margin-left:6px;">'
            f'[{_e(it.project_name)}]</span>'
            if it.project_name else ""
        )
        all_task_items.append(_task_row(it.title + (proj or ""), badge))

    if all_task_items:
        inner = f'<ul style="list-style:none;margin:0;padding:0;">{"".join(all_task_items)}</ul>'
        sections.append(_section("Focus & upcoming", inner))

    # ── Calendar ──
    if brief.calendar_text:
        sections.append(_render_calendar_section(brief.calendar_text))

    # ── Conflicts ──
    if brief.conflicts:
        items = []
        for c in brief.conflicts:
            items.append(
                f'<li style="display:flex;align-items:baseline;padding:6px 0;">'
                f'<span style="color:{_RED};margin-right:10px;flex-shrink:0;">·</span>'
                f'<span style="color:{_RED};font-size:14px;font-family:{_SANS};">{_e(c)}</span>'
                f'</li>'
            )
        inner = f'<ul style="list-style:none;margin:0;padding:0;">{"".join(items)}</ul>'
        sections.append(_section("Heads-up", inner))

    # ── Recommendation ──
    if brief.recommendation:
        sections.append(
            f'<div style="margin-top:8px;padding:14px 18px;background:{_SURFACE2};'
            f'border-left:3px solid {_RED};border-radius:0 6px 6px 0;'
            f'color:{_INK};font-size:14px;line-height:1.7;font-family:{_SANS};">'
            f'{_e(brief.recommendation)}</div>'
        )

    body_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Fira+Code:wght@400;500;600&display=swap');
    :root {{ color-scheme: light; }}
  </style>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:{_SANS};">
  <div style="max-width:600px;margin:0 auto;padding:32px 16px 24px;">

    <!-- Card -->
    <div style="background:{_SURFACE};border:1px solid {_BORDER};border-radius:12px;overflow:hidden;">

      <!-- Header: warm beige strip, dark ink text -->
      <div style="padding:24px 32px 20px;background:{_BG};border-bottom:1px solid {_BORDER};">
        <div style="font-family:{_MONO};font-size:11px;font-weight:600;
                    color:{_RED};letter-spacing:0.06em;margin-bottom:8px;">
          Irma
        </div>
        <div style="font-family:{_SANS};font-size:24px;font-weight:700;
                    color:{_INK};letter-spacing:-0.02em;line-height:1.1;">
          {day_name},&ensp;<span style="font-weight:400;color:{_INK_MUTE};">{date_part}</span>
        </div>
      </div>

      <!-- Body: lighter cream, dark ink -->
      <div style="padding:28px 32px;background:{_SURFACE};">
        {body_html}
      </div>

    </div>

    <!-- Footer -->
    <div style="text-align:center;padding:16px 0 0;
                font-family:{_MONO};font-size:10px;color:{_INK_MUTE};letter-spacing:0.05em;">
      Irma &mdash; your AI PMO
    </div>

  </div>
</body>
</html>"""


# ── Section building blocks ─────────────────────────────────────────────────

def _section(title: str, content: str) -> str:
    return (
        f'<div style="margin-top:28px;">'
        f'<div style="font-family:{_MONO};font-size:11px;font-weight:600;'
        f'color:{_INK_MUTE};letter-spacing:0.07em;'
        f'padding-bottom:10px;margin-bottom:4px;border-bottom:1px solid {_BORDER};">'
        f'{_e(title)}</div>'
        f'{content}'
        f'</div>'
    )


def _due_badge(iso: str, today: date) -> str:
    try:
        d = date.fromisoformat(iso)
    except (ValueError, AttributeError):
        return ""
    overdue     = d < today
    bg_color    = _RED_LIGHT   if overdue else _AMBER_LIGHT
    text_color  = _RED         if overdue else _AMBER
    return (
        f'<span style="display:inline-block;margin-left:8px;padding:1px 7px;'
        f'background:{bg_color};color:{text_color};font-size:11px;font-weight:600;'
        f'border-radius:4px;font-family:{_MONO};">'
        f'{"today" if d == today else "due " + _fmt_date(iso)}</span>'
    )


def _task_row(label_html: str, badge: str) -> str:
    return (
        f'<li style="display:flex;align-items:baseline;padding:7px 0;'
        f'border-bottom:1px solid {_BORDER};">'
        f'<span style="color:{_BORDER_STRONG};margin-right:10px;flex-shrink:0;">·</span>'
        f'<span style="color:{_INK};font-size:14px;font-family:{_SANS};">'
        f'{label_html}{badge}</span>'
        f'</li>'
    )


def _render_calendar_section(calendar_text: str) -> str:
    lines = calendar_text.split("\n")
    if not lines:
        return ""

    section_title = lines[0].strip()
    inner: list[str] = []
    in_list = False

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            if in_list:
                inner.append("</ul>")
                in_list = False
            continue
        # Calendar group name: "CalName:" with no leading whitespace
        if stripped.endswith(":") and not line.startswith(" "):
            if in_list:
                inner.append("</ul>")
                in_list = False
            cal_name = stripped[:-1]
            inner.append(
                f'<div style="font-family:{_MONO};font-size:10px;font-weight:600;'
                f'color:{_INK_MUTE};letter-spacing:0.1em;'
                f'margin:14px 0 4px;text-transform:uppercase;">'
                f'{_e(cal_name)}</div>'
            )
        elif line.startswith("  •"):
            if not in_list:
                inner.append(f'<ul style="list-style:none;margin:0;padding:0;">')
                in_list = True
            event_text = line[3:].strip()
            inner.append(
                f'<li style="display:flex;align-items:baseline;padding:3px 0;">'
                f'<span style="color:{_BORDER_STRONG};margin-right:10px;flex-shrink:0;">·</span>'
                f'<span style="font-family:{_MONO};font-size:13px;color:{_INK};">'
                f'{_e(event_text)}</span>'
                f'</li>'
            )
        else:
            inner.append(
                f'<div style="color:{_INK_MUTE};font-size:13px;font-family:{_SANS};">'
                f'{_e(stripped)}</div>'
            )

    if in_list:
        inner.append("</ul>")

    return _section(section_title, "\n".join(inner))
