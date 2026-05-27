# LLM.md — Pluggable LLM backend

Irma's synthesis and chat surfaces both go through a single, provider-agnostic interface so the backing model is a one-env-var decision. Switch between Claude and a local Ollama model without touching code.

## Why both

- **Claude (Anthropic)** — frontier capability. Best brief quality, fastest, no local resource cost. Requires an API key + network.
- **Ollama (local)** — runs entirely on the machine. Lower quality at the small sizes that fit a 16 GB Mac (7–9 B Q4), but free, private, and offline-capable. Good enough for Irma's scope: she's a lightweight personal assistant, not a heavy reasoning agent.

## The contract — `irma_api/agents/llm.py`

```python
class LLMClient(Protocol):
    backend: str
    model: str
    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        max_tokens: int = 1500,
    ) -> str: ...
```

One async call. System prompt is passed separately (Anthropic-style) and adapted to a `system`-role message when needed (Ollama). `ChatTurn` is a tiny Pydantic model: `{role: "user" | "assistant", content: str}`.

That's the entire surface area. `LeadAgent` and the `/chat` router both depend only on this protocol — they never see an SDK type.

## Adapters

### `AnthropicLLM`
Wraps `AsyncAnthropic`. `complete()` calls `messages.create(model, max_tokens, system, messages)` and concatenates the text blocks from `response.content`.

### `OllamaLLM`
- Long-lived `httpx.AsyncClient` against `base_url` (default `http://127.0.0.1:11434`).
- Generous read timeout (180 s) — a cold local 7 B model on an M2 Air can take 20+ seconds to first token.
- `complete()` POSTs to `/api/chat` with `{model, messages: [system + turns], stream: False, options: {num_predict: max_tokens}}` and returns `response.message.content`.
- `aclose()` cleans the client up on lifespan shutdown.

## The factory

```python
def build_llm_client(settings: Settings) -> LLMClient | None
```

Returns the adapter for `settings.irma_llm_backend`, or `None` if the chosen backend can't be configured (e.g. `anthropic` selected but no `ANTHROPIC_API_KEY`). The factory deliberately **does not raise** — the app boots in degraded mode and surfaces a 503 from `/standup` and `/chat`. Observers still collect, the dashboard still renders cached briefs.

`app.py` stores the result on `app.state.llm`. `LeadAgent` is built only if `llm is not None`. Router code reads from `request.app.state.llm`.

## Switching backends

Edit `services/api/.env`:

```bash
# Claude
IRMA_LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-…
ANTHROPIC_MODEL=claude-sonnet-4-6

# — or — local Ollama
IRMA_LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b
```

Restart the backend (`uv run irma-api`). The boot log includes the active backend:

```
app.ready  llm_backend=ollama  llm_model=qwen2.5:7b
```

The `/chat` response surfaces `{backend, model}` so the dashboard's chat panel can display which one served the reply.

## Running Ollama locally

```bash
brew install ollama
ollama serve &
ollama pull qwen2.5:7b
```

For a 16 GB M2 Mac the 7–9 B Q4 tier is the practical ceiling (`qwen2.5:7b`, `qwen2.5-coder:7b`, `llama3.1:8b`, `mistral:7b`). Anything larger swap-thrashes. See the project's memory notes for hardware-driven model-choice rationale.

## Persona prompts

Two separate system prompts live in the codebase:

- **Chat** — `irma_api/routers/chat.py::_SYSTEM_PROMPT`. Free-form personal-assistant voice. Establishes Irma as Amit's small dog beside the Dock — aware of it, comfortable, but instructed not to perform dog clichés. Voice: calm, terse, factual, loyal but not fawning.
- **Synthesis** — `irma_api/agents/lead_agent.py::_SYSTEM_PROMPT`. Same identity, but JSON-only output discipline. The schema lives in the prompt itself; defensive parsing (`_parse_brief`) strips fences, slices the first `{…}`, validates via Pydantic, and retries exactly once on failure.

Both prompts have to be updated together when Irma's identity changes (e.g. when we noticed the chat prompt didn't yet mention she was a dog).

## Adding a new backend

1. Implement a class satisfying the `LLMClient` protocol (set `backend` and `model` class/instance attrs, implement `async def complete`).
2. Extend `LLMBackend` in `config.py` to include your new literal.
3. Branch on it in `build_llm_client`.
4. Add the env keys to `.env.example`.

The rest of the codebase (`LeadAgent`, `/chat`, lifespan) is untouched — that's the point of the abstraction.
