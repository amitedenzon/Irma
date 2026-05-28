"""LLMClient tool-use: types, AnthropicLLM round-trips."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from anthropic import AsyncAnthropic

from irma_api.agents.llm import (
    AnthropicLLM,
    ChatTurn,
    OllamaLLM,
    TextResult,
    ToolCallResult,
)
from irma_api.tools.base import ToolSpec

_ECHO_SPEC = ToolSpec(
    name="echo",
    description="Echo input.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


def _content_block(type_: str, **fields: Any) -> MagicMock:
    block = MagicMock()
    block.type = type_
    for k, v in fields.items():
        setattr(block, k, v)
    return block


@pytest.mark.asyncio
async def test_anthropic_returns_text_result_when_no_tool_use() -> None:
    fake_client = MagicMock(spec=AsyncAnthropic)
    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [_content_block("text", text="hello world")]
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    llm = AnthropicLLM(client=fake_client, model="claude-sonnet-4-6")
    result = await llm.complete(
        system="sys", messages=[ChatTurn(role="user", content="hi")]
    )
    assert isinstance(result, TextResult)
    assert result.text == "hello world"


@pytest.mark.asyncio
async def test_anthropic_returns_tool_call_result_when_tool_use() -> None:
    fake_client = MagicMock(spec=AsyncAnthropic)
    fake_response = MagicMock()
    fake_response.stop_reason = "tool_use"
    fake_response.content = [
        _content_block("text", text="Let me echo that."),
        _content_block(
            "tool_use",
            id="toolu_01",
            name="echo",
            input={"text": "hi"},
        ),
    ]
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    llm = AnthropicLLM(client=fake_client, model="claude-sonnet-4-6")
    result = await llm.complete(
        system="sys",
        messages=[ChatTurn(role="user", content="echo hi")],
        tools=[_ECHO_SPEC],
    )
    assert isinstance(result, ToolCallResult)
    assert len(result.calls) == 1
    assert result.calls[0].id == "toolu_01"
    assert result.calls[0].name == "echo"
    assert result.calls[0].args == {"text": "hi"}
    assert result.preface == "Let me echo that."


@pytest.mark.asyncio
async def test_anthropic_replays_tool_results_in_message_history() -> None:
    fake_client = MagicMock(spec=AsyncAnthropic)
    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [_content_block("text", text="done")]
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    llm = AnthropicLLM(client=fake_client, model="claude-sonnet-4-6")
    turns = [
        ChatTurn(role="user", content="echo hi"),
        ChatTurn(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "toolu_01", "name": "echo", "args": {"text": "hi"}}
            ],
        ),
        ChatTurn(
            role="user",
            content="",
            tool_results=[{"tool_use_id": "toolu_01", "content": "echo:hi"}],
        ),
    ]
    await llm.complete(system="sys", messages=turns, tools=[_ECHO_SPEC])

    sent = fake_client.messages.create.await_args.kwargs["messages"]
    assert sent[1]["role"] == "assistant"
    assert sent[1]["content"][0]["type"] == "tool_use"
    assert sent[1]["content"][0]["id"] == "toolu_01"
    assert sent[2]["role"] == "user"
    assert sent[2]["content"][0]["type"] == "tool_result"
    assert sent[2]["content"][0]["tool_use_id"] == "toolu_01"
    assert sent[2]["content"][0]["content"] == "echo:hi"


@pytest.mark.asyncio
async def test_ollama_returns_text_result_without_tool_calls() -> None:
    async with respx.mock(base_url="http://127.0.0.1:11434") as rmock:
        rmock.post("/api/chat").respond(
            200, json={"message": {"role": "assistant", "content": "ack"}}
        )
        llm = OllamaLLM(base_url="http://127.0.0.1:11434", model="qwen2.5:7b")
        try:
            result = await llm.complete(
                system="sys", messages=[ChatTurn(role="user", content="hi")]
            )
        finally:
            await llm.aclose()
    assert isinstance(result, TextResult)
    assert result.text == "ack"


@pytest.mark.asyncio
async def test_ollama_returns_tool_call_result_when_model_calls_tool() -> None:
    payload = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "echo",
                        "arguments": {"text": "hi"},
                    }
                }
            ],
        }
    }
    async with respx.mock(base_url="http://127.0.0.1:11434") as rmock:
        rmock.post("/api/chat").respond(200, json=payload)
        llm = OllamaLLM(base_url="http://127.0.0.1:11434", model="qwen2.5:7b")
        try:
            result = await llm.complete(
                system="sys",
                messages=[ChatTurn(role="user", content="echo hi")],
                tools=[_ECHO_SPEC],
            )
        finally:
            await llm.aclose()
    assert isinstance(result, ToolCallResult)
    assert len(result.calls) == 1
    assert result.calls[0].name == "echo"
    assert result.calls[0].args == {"text": "hi"}


@pytest.mark.asyncio
async def test_ollama_replays_tool_results_with_role_tool() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "done"}}
        )

    async with respx.mock(base_url="http://127.0.0.1:11434") as rmock:
        rmock.post("/api/chat").mock(side_effect=handler)
        llm = OllamaLLM(base_url="http://127.0.0.1:11434", model="qwen2.5:7b")
        try:
            await llm.complete(
                system="sys",
                messages=[
                    ChatTurn(role="user", content="echo hi"),
                    ChatTurn(
                        role="assistant",
                        content="",
                        tool_calls=[
                            {"id": "1", "name": "echo", "args": {"text": "hi"}}
                        ],
                    ),
                    ChatTurn(
                        role="user",
                        content="",
                        tool_results=[
                            {"tool_use_id": "1", "content": "echo:hi"}
                        ],
                    ),
                ],
                tools=[_ECHO_SPEC],
            )
        finally:
            await llm.aclose()

    msgs = captured["body"]["messages"]
    assert msgs[-1]["role"] == "tool"
    assert msgs[-1]["content"] == "echo:hi"
