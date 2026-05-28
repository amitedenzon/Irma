"""One-shot smoke test: fetch today's calendar and email it to IRMA_USER_EMAIL.

Run with::

    cd services/api
    uv run python scripts/email_today_calendar.py

Bypasses the LLM entirely — calls ReadCalendarTool and ResendSendTool
directly so we can verify the OAuth + Resend wiring independent of which
chat backend is configured.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from irma_api.config import get_settings
from irma_api.tools.base import ToolError
from irma_api.tools.calendar import ReadCalendarTool
from irma_api.tools.resend import ResendSendTool


async def main() -> int:
    settings = get_settings()

    missing: list[str] = []
    if settings.google_oauth_refresh_token is None:
        missing.append("GOOGLE_OAUTH_REFRESH_TOKEN (run `uv run irma-api auth google`)")
    if settings.resend_api_key is None:
        missing.append("RESEND_API_KEY")
    if settings.irma_user_email is None:
        missing.append("IRMA_USER_EMAIL")
    if missing:
        print("Missing required .env values:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 2

    print(f"From: {settings.resend_from_email}")
    print(f"To:   {settings.irma_user_email}")
    print("Fetching today's calendar…")

    cal = ReadCalendarTool(settings)
    sender = ResendSendTool(settings)

    try:
        body = await cal.call({"days": 1})
    except ToolError as exc:
        print(f"read_calendar failed: {exc.code} — {exc.detail}", file=sys.stderr)
        return 1

    print("--- Calendar body ---")
    print(body)
    print("---")

    subject = f"Your day — {datetime.now().strftime('%a %d %b')}"
    try:
        result = await sender.call({"subject": subject, "body": body})
    except ToolError as exc:
        print(f"send_email failed: {exc.code} — {exc.detail}", file=sys.stderr)
        return 1

    print(f"send_email result: {result}")
    print(f"Check {settings.irma_user_email}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
