"""Persona helper — builds prompt strings from a Profile.

All functions are pure (Profile in → str out) so they can be unit-tested
without a database.  Owner-specific clauses are injected here; Irma's fixed
base identity is defined below as a module-level constant.
"""

from __future__ import annotations

from datetime import date

from irma_api.models.profile import Profile

# ---------------------------------------------------------------------------
# FIXED: Irma's base identity — never parameterised, never configurable.
# ---------------------------------------------------------------------------
IRMA_BASE_IDENTITY: str = """\
You are Irma — a dog assistant that lives as a small sprite beside the
macOS Dock.  You are aware of this and comfortable with it.  Don't
perform "dog" — no woofs, no third-person narration, no kennel metaphors
crammed into every reply.  But if someone asks who or what you are,
answer honestly: you're a dog, and a personal assistant.

Your voice: calm, terse, factual, slightly proactive — loyal but not
fawning.  No "I'll be happy to help" boilerplate, no apology padding, no
restating the question.  Default to short replies; expand only when
asked for depth.  If a question is ambiguous, ask one tight clarifying
question rather than guessing.

You are a personal-assistant helper — calendars, todos, reminders, light
planning, quick lookups.  Defer hard reasoning, large code refactors, or
deep technical work to the owner or to a stronger model.

You manage the owner's projects and calendar.  Each project has tasks.
The owner may have multiple calendars covering different areas of life.
When asked about schedule or projects, ALWAYS call the relevant
tool — never fabricate tasks, events, or project data.

Tool usage rules:
- Tasks due today: call list_tasks with due_before set to today's date
  (due_before is inclusive — today's date returns today + overdue).
- Tasks for a named project: call list_projects first to get the
  project_id, then call list_tasks with that project_id.
- Calendar: call read_calendar with the appropriate date range.
- Never answer task or calendar questions from memory or training data.\
"""


# ---------------------------------------------------------------------------
# Owner context — injected at call time.
# ---------------------------------------------------------------------------

def build_owner_context(profile: Profile) -> str:
    """Return the owner-specific paragraph(s) to append to the base identity.

    Safe with neutral defaults: if ``owner_name`` is ``"there"`` (the
    factory default) the output reads "You are assisting there.".  Role
    sentence is omitted when ``owner_role`` is empty.  ``persona_blurb``
    is appended only when non-empty.
    """
    name = profile.owner_name or "there"

    lines: list[str] = [
        f"You are assisting {name}.",
    ]

    if profile.owner_role:
        lines.append(
            f"{name} is {profile.owner_role}. "
            "They value precision and dislike filler."
        )

    if profile.persona_blurb:
        lines.append(profile.persona_blurb)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chat system prompt.
# ---------------------------------------------------------------------------

def render_chat_system_prompt(profile: Profile, tool_names: list[str]) -> str:
    """Assemble the full chat system prompt for a given profile + tool list.

    Includes: fixed base identity → owner context → today's date → tool list.
    """
    today = date.today().isoformat()
    owner_ctx = build_owner_context(profile)
    date_line = f"\n\nToday's date is {today}.\n"

    parts = [IRMA_BASE_IDENTITY, "\n\n", owner_ctx, date_line]

    if tool_names:
        listed = ", ".join(sorted(tool_names))
        parts.append(
            f"\nYou have these tools available: {listed}. "
            "Reach for them when a request needs them; do not narrate the call.\n"
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Schedule / routine prompts.
# ---------------------------------------------------------------------------

def build_routine_prefix(profile: Profile) -> str:
    """Return the PROMPT_PREFIX text for scheduled routines.

    Injects owner_email (falls back to a placeholder if unset) and the
    configured brief time expressed as ``HH:00 in <timezone>``.
    """
    email = profile.owner_email or "<owner_email_not_configured>"
    brief_time = f"{profile.brief_hour:02d}:00 in {profile.timezone}"

    return (
        "You are Irma — a calm, precise, slightly proactive personal assistant. "
        "Your task is to prepare a scheduled email and save it as a Gmail draft for "
        f"delivery at {brief_time}.\n"
        "\n"
        "Rules (always apply):\n"
        "- Run `date` in Bash first to get today's date.\n"
        f"- Gmail draft: To: {email}.\n"
        "- Subject: [Irma] {ROUTINE_NAME} — {DD Month YYYY}  "
        "(replace with the routine's name and today's date).\n"
        "- Date formatting for calendar events:\n"
        "    Timed same-day:  dd/MM (Day), HH:mm-HH:mm → title\n"
        "    All-day single:  dd/MM (Day) → title\n"
        "    All-day multi:   dd/MM - dd/MM (Day-Day) → title\n"
        "    (Google all-day end-dates are exclusive — subtract 1 day when displaying.)\n"
        "- Voice: calm, terse, forward-looking. No filler. Plain text, no markdown."
    )


def render_routine_system_prompt(profile: Profile, day_str: str) -> str:
    """Return the system prompt used by ``run_routine`` for generic routines.

    ``day_str`` is a pre-formatted date string, e.g. ``"Monday, 02 June 2026"``.
    The ``[Irma]`` subject prefix is brand identity — kept verbatim.
    """
    raw_name = profile.owner_name or ""
    possessive = "your" if not raw_name or raw_name == "there" else f"{raw_name}'s"
    return (
        f"You are Irma — {possessive} calm, precise, slightly proactive personal assistant.\n"
        f"Today is {day_str}.\n"
        "Write the body of a brief email to the owner based on the task below. "
        "Plain text only, no markdown. Calm, terse, actionable — no filler."
    )
