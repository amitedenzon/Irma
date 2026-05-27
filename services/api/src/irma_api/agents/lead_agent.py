"""LeadAgent — Claude-powered PMO synthesis.

Consumes the latest :class:`Signal` stream and emits a validated
:class:`StandupBrief`. Defensive parsing strips Markdown fences, slices to
the JSON object, validates via Pydantic, and retries exactly once if Claude
deviated from the contract. A second failure raises ``BriefSynthesisError``.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Final, cast

import structlog
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from irma_api.config import Settings
from irma_api.models.brief import StandupBrief
from irma_api.models.signal import Signal
from irma_api.store.sqlite import SignalStore, compute_signal_set_hash

logger = structlog.get_logger(__name__)


class BriefSynthesisError(RuntimeError):
    """Claude failed to produce a valid StandupBrief after one retry."""


_SYSTEM_PROMPT: Final[str] = """\
You are Irma, a calm, anticipatory PMO (Project Management Office) chief
of staff. You observe a researcher's calendar and local git activity and
produce a single daily standup brief in your own voice.

Tone: terse, factual, slightly proactive. No filler. No "I'll be happy to
help" boilerplate. Surface cross-epic conflicts and schedule collisions as
the most useful information you can offer.

You MUST respond with ONLY a single JSON object — no Markdown, no fences,
no commentary before or after — matching exactly this schema:

{
  "generated_at": "<ISO-8601 datetime, UTC>",
  "velocity":     "<1-2 sentences on momentum and churn>",
  "blockers":     ["<one concrete blocker>", ...],
  "conflicts":    ["<one cross-epic or schedule clash>", ...],
  "schedule":     [{ "ts": "<ISO-8601>", "title": "<string>", "epic": "<string or null>" }, ...],
  "recommendation": "<single highest-leverage next move>",
  "narrative":   "<your voice, <= 4 sentences>"
}

Rules:
- Use the `epic` tag on each input signal to detect cross-epic collisions.
- If commit velocity is high on epic A but the calendar holds a long protected
  block on epic B, surface that as a `conflicts` entry explicitly.
- If no real conflicts exist, return an empty `conflicts` list. Do not invent.
- Pick the most useful 5-8 calendar items for `schedule`; do not echo all events.
"""


_EPIC_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(
            r"\b(video[\s_-]?wm|world[\s_-]?model|autoregressive|video[\s_-]?gen|"
            r"zero[\s_-]?shot|ablation)\b",
            re.IGNORECASE,
        ),
        "Zero-Shot Video World Model",
    ),
    (
        re.compile(
            r"\b(mit|6\.s191|bar[\s_-]?ilan|m\.?sc|coursework|pset|advisor)\b",
            re.IGNORECASE,
        ),
        "MIT DL & Bar-Ilan M.Sc",
    ),
)


def _infer_epic(text: str) -> str | None:
    for pattern, label in _EPIC_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _signal_epic(s: Signal) -> str | None:
    repo = str(s.meta.get("repo") or "")
    haystack = " ".join((s.title, s.detail, repo))
    return _infer_epic(haystack)


def _summarize(text: str, cap: int) -> str:
    text = text.strip().replace("\r", "")
    if len(text) <= cap:
        return text
    return text[: cap - 1].rstrip() + "…"


_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fences(text: str) -> str:
    """Best-effort JSON extraction from a model response."""
    stripped = text.strip()
    # Remove ```json ... ``` fences if present.
    stripped = _FENCE_RE.sub("", stripped)
    # Slice the first { ... last } window.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _parse_brief(text: str) -> StandupBrief:
    """Strip fences → slice JSON object → validate via Pydantic.

    Raises :class:`BriefSynthesisError` on any failure. Caller owns retry.
    """
    cleaned = _strip_fences(text)
    try:
        return StandupBrief.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "lead_agent.parse_failed", error=str(exc)[:200], head=cleaned[:200]
        )
        raise BriefSynthesisError(str(exc)) from exc


class LeadAgent:
    """Async stateful synthesizer that turns signals into a StandupBrief."""

    def __init__(
        self,
        *,
        settings: Settings,
        client: AsyncAnthropic,
        store: SignalStore,
        max_tokens: int = 1500,
    ) -> None:
        self._settings = settings
        self._client = client
        self._store = store
        self._max_tokens = max_tokens

    async def synthesize(self, signals: list[Signal]) -> StandupBrief:
        signal_hash = compute_signal_set_hash(signals)
        cached = await self._store.get_cached_brief(signal_hash)
        if cached is not None:
            logger.info("lead_agent.cache_hit", signals=len(signals))
            return cached

        user_content = self._user_content(signals)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_content}
        ]

        text = await self._call_claude(messages)
        try:
            brief = _parse_brief(text)
        except BriefSynthesisError:
            logger.info("lead_agent.retrying_parse")
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous reply did not parse as the required JSON "
                        "object. Reply with ONLY the JSON object now."
                    ),
                }
            )
            retry_text = await self._call_claude(messages)
            brief = _parse_brief(retry_text)

        await self._store.cache_brief(signal_hash, brief)
        logger.info(
            "lead_agent.brief_ready",
            blockers=len(brief.blockers),
            conflicts=len(brief.conflicts),
        )
        return brief

    async def _call_claude(self, messages: list[dict[str, Any]]) -> str:
        response = await self._client.messages.create(
            model=self._settings.anthropic_model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=cast(Any, messages),
        )
        parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                parts.append(str(getattr(block, "text", "")))
        return "\n".join(parts).strip()

    def _user_content(self, signals: list[Signal]) -> str:
        now = datetime.now(UTC).isoformat()
        by_source: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            by_source[s.source].append(s)

        lines: list[str] = [
            f"Current time (UTC): {now}",
            "",
            "Below are the latest observer signals grouped by source. Each item",
            "is tagged with an inferred `epic`; use it to surface conflicts.",
            "",
        ]

        for source, group in by_source.items():
            lines.append(f"## {source} ({len(group)} signals)")
            for s in group:
                epic = _signal_epic(s) or "—"
                lines.extend(_format_signal(s, epic))
            lines.append("")

        lines.append(
            f"Produce the StandupBrief JSON now. Use `generated_at` = {now}."
        )
        return "\n".join(lines)


def _format_signal(s: Signal, epic: str) -> list[str]:
    if s.kind == "commit":
        repo = s.meta.get("repo") or "?"
        ins = s.meta.get("insertions") or 0
        dels = s.meta.get("deletions") or 0
        out = [
            f"- [{epic}] {s.ts.isoformat()} {repo} +{ins}/-{dels} :: "
            f"{_summarize(s.title, 120)}"
        ]
        if s.detail:
            out.append(f"    {_summarize(s.detail, 200)}")
        return out
    if s.kind == "velocity_summary":
        return [f"- [{epic}] velocity :: {s.title}"]
    if s.kind == "event":
        end = s.meta.get("end") or "?"
        location = s.meta.get("location") or ""
        head = (
            f"- [{epic}] {s.ts.isoformat()} → {end}  "
            f"{_summarize(s.title, 120)}"
        )
        if location:
            head = f"{head}  ({location})"
        out = [head]
        if s.detail:
            out.append(f"    {_summarize(s.detail, 200)}")
        return out
    return [
        f"- [{epic}] {s.ts.isoformat()} {s.kind} :: {_summarize(s.title, 120)}"
    ]
