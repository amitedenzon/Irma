"""render_daily_email — turn a DailyBrief into a plain-text email (subject, body).

Pure function. Empty sections are omitted. The factual numbers come straight
from the computed DailyBrief fields; only the narrative/recommendation prose is
LLM-authored.
"""

from __future__ import annotations

from datetime import date

from irma_api.models.daily_brief import DailyBrief


def render_daily_email(brief: DailyBrief, today: date) -> tuple[str, str]:
    subject = f"Irma · Daily Brief — {today.strftime('%a %d %b')}"
    lines: list[str] = []

    if brief.narrative:
        lines += [brief.narrative, ""]

    if brief.progress:
        if brief.has_baseline:
            lines.append("PROGRESS SINCE YOUR LAST BRIEF")
            for p in brief.progress:
                lines.append(
                    f"  • {p.project_name}: {p.completed_since} done, "
                    f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
                )
        else:
            lines.append("PROJECT STATUS (first brief — no prior baseline yet)")
            for p in brief.progress:
                lines.append(
                    f"  • {p.project_name}: {p.open_now} open / {p.done_now} done"
                )
        lines.append("")

    if brief.today_focus:
        lines.append("TODAY'S FOCUS")
        for f in brief.today_focus:
            suffix = f" (due {f.due_date})" if f.due_date else ""
            lines.append(f"  • {f.title}{suffix}")
        lines.append("")

    if brief.lookahead_tasks or brief.calendar_text:
        lines.append("NEXT 3 DAYS")
        for it in brief.lookahead_tasks:
            proj = f" [{it.project_name}]" if it.project_name else ""
            lines.append(f"  • {it.when} — {it.title}{proj} ({it.kind})")
        if brief.calendar_text:
            lines.append("")
            lines.append(brief.calendar_text)
        lines.append("")

    if brief.conflicts:
        lines.append("HEADS-UP")
        for c in brief.conflicts:
            lines.append(f"  • {c}")
        lines.append("")

    if brief.recommendation:
        lines.append(brief.recommendation)

    body = "\n".join(lines).rstrip() + "\n"
    return subject, body
