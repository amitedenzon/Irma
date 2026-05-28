"""Chat tool-call loop: dispatches calls, replays results, caps iterations."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.agents.llm import TextResult, ToolCall, ToolCallResult
from irma_api.routers.chat import MAX_TOOL_ITERATIONS
from irma_api.routers.chat import router as chat_router
from irma_api.runtime.state import StateBus
from irma_api.tools.base import Tool, ToolRegistry, ToolSpec


class _FakeLLM:
    backend = "fake"
    model = "fake"

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._results.pop(0)


class _EchoTool:
    spec = ToolSpec(
        name="echo",
        description="Echo input.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    async def call(self, args: dict[str, Any]) -> str:
        return f"echo:{args['text']}"


def _build_app(llm: Any, tools: list[Tool]) -> FastAPI:
    app = FastAPI()
    app.state.llm = llm
    app.state.bus = StateBus()
    app.state.tools = ToolRegistry(tools)
    app.include_router(chat_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_simple_text_reply_no_tools() -> None:
    llm = _FakeLLM(TextResult(text="hi"))
    app = _build_app(llm, [_EchoTool()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "hi"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_single_tool_call_then_text() -> None:
    llm = _FakeLLM(
        ToolCallResult(
            calls=[ToolCall(id="t1", name="echo", args={"text": "hi"})],
            preface="",
        ),
        TextResult(text="done"),
    )
    app = _build_app(llm, [_EchoTool()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "echo hi"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "done"
    assert len(llm.calls) == 2

    replay = llm.calls[1]["messages"]
    assert any(t.tool_calls for t in replay)
    assert any(t.tool_results for t in replay)
    tr_turn = next(t for t in replay if t.tool_results)
    assert tr_turn.tool_results[0].content == "echo:hi"


@pytest.mark.asyncio
async def test_unknown_tool_surfaces_polite_error() -> None:
    llm = _FakeLLM(
        ToolCallResult(
            calls=[ToolCall(id="t1", name="nope", args={})],
            preface="",
        ),
        TextResult(text="(fallback)"),
    )
    app = _build_app(llm, [_EchoTool()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
    assert resp.status_code == 200
    replay = llm.calls[1]["messages"]
    tr_turn = next(t for t in replay if t.tool_results)
    assert "tool_not_found" in tr_turn.tool_results[0].content


@pytest.mark.asyncio
async def test_loop_terminates_at_iteration_cap() -> None:
    forever_call = ToolCallResult(
        calls=[ToolCall(id="t", name="echo", args={"text": "x"})], preface=""
    )
    llm = _FakeLLM(*([forever_call] * (MAX_TOOL_ITERATIONS + 2)))
    app = _build_app(llm, [_EchoTool()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "loop"}]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "stuck" in body["reply"].lower() or "got stuck" in body["reply"].lower()
    assert len(llm.calls) == MAX_TOOL_ITERATIONS


@pytest.mark.asyncio
async def test_503_when_llm_missing() -> None:
    app = FastAPI()
    app.state.llm = None
    app.state.bus = StateBus()
    app.state.tools = ToolRegistry([])
    app.include_router(chat_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 503
