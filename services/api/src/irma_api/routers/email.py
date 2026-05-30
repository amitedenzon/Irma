"""HTTP surface for operator-bound email via Resend.

The embedded Claude terminal can't actually send via its `mcp__claude_ai_Gmail`
server — that connector only exposes draft creation. This endpoint gives
Claude (and any other local caller) a thin REST path that goes straight
through Irma's existing `ResendSendTool`. Recipient is locked server-side
to `IRMA_USER_EMAIL`: the terminal runs with `--dangerously-skip-permissions`
so anything reachable from there is implicitly a privileged surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from irma_api.tools.base import ToolError
from irma_api.tools.resend import ResendSendTool

router = APIRouter(prefix="/email", tags=["email"])


class SendEmailRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


@router.post("/send")
async def send_email(request: Request, body: SendEmailRequest) -> JSONResponse:
    tool: ResendSendTool | None = getattr(request.app.state, "send_email_tool", None)
    if tool is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "send_email_unavailable",
                "detail": "Resend is not configured (RESEND_API_KEY, IRMA_USER_EMAIL).",
            },
        )
    try:
        result = await tool.call({"subject": body.subject, "body": body.body})
    except ToolError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": exc.code, "detail": exc.detail},
        )
    return JSONResponse(status_code=200, content={"status": "sent", "detail": result})
