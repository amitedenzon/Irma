"""Pure unit tests for irma_api.agents.persona.

No database, no async — functions are Profile-in / str-out.
"""

from __future__ import annotations

from datetime import UTC, datetime

from irma_api.agents.persona import (
    build_owner_context,
    build_routine_prefix,
    render_chat_system_prompt,
    render_routine_system_prompt,
)
from irma_api.models.profile import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(**kwargs: object) -> Profile:
    """Construct a Profile with a required updated_at, overriding any field."""
    defaults: dict[str, object] = {"updated_at": datetime(2026, 6, 2, tzinfo=UTC)}
    defaults.update(kwargs)
    return Profile(**defaults)  # type: ignore[arg-type]


def _neutral() -> Profile:
    """Profile with all factory defaults — owner_name='there', role='', etc."""
    return _profile()


def _full() -> Profile:
    """Fully-populated Profile."""
    return _profile(
        owner_name="Alex",
        owner_role="machine learning engineer specialising in distributed training",
        owner_email="alex@example.com",
        persona_blurb="Alex prefers bullet lists over prose.",
        timezone="America/New_York",
        brief_hour=7,
    )


# ---------------------------------------------------------------------------
# build_owner_context
# ---------------------------------------------------------------------------

class TestBuildOwnerContext:
    def test_neutral_defaults_no_name_injected(self) -> None:
        ctx = build_owner_context(_neutral())
        # The neutral greeting uses "there"
        assert "there" in ctx
        # No dangling role sentence
        assert "is" not in ctx or ctx.strip().split("\n")[0] == "You are assisting there."

    def test_neutral_no_empty_role_sentence(self) -> None:
        ctx = build_owner_context(_neutral())
        # owner_role is empty — the role sentence must be absent
        lines = [ln.strip() for ln in ctx.splitlines() if ln.strip()]
        # Only the "You are assisting there." line should be present
        assert len(lines) == 1
        assert lines[0] == "You are assisting there."

    def test_neutral_no_persona_blurb(self) -> None:
        ctx = build_owner_context(_neutral())
        # No empty blurb artifacts
        assert ctx.strip() != ""
        assert "\n\n\n" not in ctx

    def test_full_name_injected(self) -> None:
        ctx = build_owner_context(_full())
        assert "Alex" in ctx

    def test_full_role_injected(self) -> None:
        ctx = build_owner_context(_full())
        assert "machine learning engineer" in ctx

    def test_full_persona_blurb_appended(self) -> None:
        ctx = build_owner_context(_full())
        assert "bullet lists" in ctx

    def test_role_absent_when_empty(self) -> None:
        p = _profile(owner_name="Sam", owner_role="")
        ctx = build_owner_context(p)
        assert "Sam" in ctx
        # No "Sam is …" line when role is empty
        assert "Sam is" not in ctx

    def test_blurb_absent_when_empty(self) -> None:
        p = _profile(owner_name="Sam", persona_blurb="")
        ctx = build_owner_context(p)
        lines = [ln for ln in ctx.splitlines() if ln.strip()]
        # Only the "You are assisting Sam." line (role also empty)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# render_chat_system_prompt
# ---------------------------------------------------------------------------

class TestRenderChatSystemPrompt:
    def test_base_identity_present(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), [])
        # The fixed identity text must appear verbatim in the rendered prompt
        assert "macOS Dock" in prompt

    def test_neutral_no_amit(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), [])
        assert "Amit" not in prompt

    def test_neutral_no_hardcoded_email(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), [])
        assert "amit.edenzon@gmail.com" not in prompt

    def test_neutral_no_dangling_role(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), [])
        # With a neutral profile (no owner_role), a role-description sentence
        # like "there is an AI researcher" must never appear.
        assert "there is" not in prompt.lower()

    def test_today_date_present(self) -> None:
        from datetime import date
        today = date.today().isoformat()
        prompt = render_chat_system_prompt(_neutral(), [])
        assert today in prompt

    def test_tool_list_injected(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), ["list_tasks", "read_calendar"])
        assert "list_tasks" in prompt
        assert "read_calendar" in prompt

    def test_no_tools_no_tool_list_suffix(self) -> None:
        prompt = render_chat_system_prompt(_neutral(), [])
        assert "tools available" not in prompt

    def test_full_profile_injects_name(self) -> None:
        prompt = render_chat_system_prompt(_full(), [])
        assert "Alex" in prompt

    def test_full_profile_injects_role(self) -> None:
        prompt = render_chat_system_prompt(_full(), [])
        assert "machine learning engineer" in prompt

    def test_full_profile_injects_blurb(self) -> None:
        prompt = render_chat_system_prompt(_full(), [])
        assert "bullet lists" in prompt


# ---------------------------------------------------------------------------
# build_routine_prefix
# ---------------------------------------------------------------------------

class TestBuildRoutinePrefix:
    def test_neutral_placeholder_email(self) -> None:
        prefix = build_routine_prefix(_neutral())
        # No configured email → fallback placeholder
        assert "<owner_email_not_configured>" in prefix

    def test_injects_owner_email(self) -> None:
        prefix = build_routine_prefix(_full())
        assert "alex@example.com" in prefix

    def test_no_hardcoded_amit_email(self) -> None:
        prefix = build_routine_prefix(_neutral())
        assert "amit.edenzon@gmail.com" not in prefix

    def test_brief_time_phrasing_default(self) -> None:
        # Default: brief_hour=8, timezone='UTC'
        prefix = build_routine_prefix(_neutral())
        assert "08:00 in UTC" in prefix

    def test_brief_time_phrasing_custom(self) -> None:
        prefix = build_routine_prefix(_full())
        assert "07:00 in America/New_York" in prefix

    def test_no_israel_phrasing(self) -> None:
        prefix = build_routine_prefix(_neutral())
        assert "Israel" not in prefix

    def test_irma_subject_prefix_preserved(self) -> None:
        # [Irma] brand prefix must be in the subject format instructions
        prefix = build_routine_prefix(_neutral())
        assert "[Irma]" in prefix

    def test_no_amit_in_prefix(self) -> None:
        prefix = build_routine_prefix(_neutral())
        assert "Amit" not in prefix


# ---------------------------------------------------------------------------
# render_routine_system_prompt
# ---------------------------------------------------------------------------

class TestRenderRoutineSystemPrompt:
    def test_irma_subject_prefix_kept(self) -> None:
        # [Irma] is brand identity — must survive
        # (It's in the subject line built in run_routine, not in the system
        #  prompt itself, but the system prompt must reference the owner name.)
        system = render_routine_system_prompt(_neutral(), "Monday, 02 June 2026")
        assert "Irma" in system

    def test_neutral_no_amit(self) -> None:
        system = render_routine_system_prompt(_neutral(), "Monday, 02 June 2026")
        assert "Amit" not in system

    def test_full_injects_name(self) -> None:
        system = render_routine_system_prompt(_full(), "Monday, 02 June 2026")
        assert "Alex" in system

    def test_day_str_injected(self) -> None:
        day = "Wednesday, 10 June 2026"
        system = render_routine_system_prompt(_neutral(), day)
        assert day in system

    def test_no_israel_phrasing(self) -> None:
        system = render_routine_system_prompt(_neutral(), "Monday, 02 June 2026")
        assert "Israel" not in system

    def test_neutral_possessive_reads_naturally(self) -> None:
        # Neutral profile must not produce the ungrammatical "there's".
        system = render_routine_system_prompt(_neutral(), "Monday, 02 June 2026")
        assert "there's" not in system
        assert "your" in system

    def test_named_possessive_renders_correctly(self) -> None:
        # A real owner name must produce "<Name>'s".
        system = render_routine_system_prompt(_full(), "Monday, 02 June 2026")
        assert "Alex's" in system
        assert "your" not in system
