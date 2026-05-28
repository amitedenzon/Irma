"""FastAPI app factory.

The lifespan hook owns the SQLite connection, observers, AgentState bus, and
the APScheduler — they all share the same event loop as the request handlers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from irma_api.agents.base import LeadAgentProtocol, Observer
from irma_api.agents.codebase_agent import CodebaseAgent
from irma_api.agents.llm import LLMClient, OllamaLLM, build_llm_registry
from irma_api.agents.time_agent import TimeAgent
from irma_api.config import get_settings
from irma_api.logging import configure_logging
from irma_api.routers.brief import router as brief_router
from irma_api.routers.chat import router as chat_router
from irma_api.routers.integrations import router as integrations_router
from irma_api.routers.projects import router as projects_router
from irma_api.routers.signals import router as signals_router
from irma_api.routers.signals import run_refresh
from irma_api.routers.state import router as state_router
from irma_api.routers.tasks import router as tasks_router
from irma_api.runtime.scheduler import Scheduler
from irma_api.runtime.state import StateBus
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import Tool, ToolRegistry

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    store = SignalStore(settings.irma_db_path)
    await store.connect()

    bus = StateBus()
    observers: list[Observer] = [TimeAgent(settings)]
    if settings.irma_codebase_agent_enabled:
        observers.append(CodebaseAgent(settings.irma_repos))

    llm_registry, default_backend = build_llm_registry(settings)
    llm: LLMClient | None = (
        llm_registry[default_backend] if default_backend is not None else None
    )

    tools: list[Tool] = []
    # Step 5 will register the ResendSendTool here once both env prereqs are set.
    registry = ToolRegistry(tools)

    lead_agent: LeadAgentProtocol | None = None
    if llm is not None:
        # Imported lazily so Phase 2 deployments without the LeadAgent module
        # still boot. Phase 3 provides irma_api.agents.lead_agent.
        try:
            lead_module = import_module("irma_api.agents.lead_agent")
            lead_agent = lead_module.LeadAgent(settings=settings, llm=llm, store=store)
        except ModuleNotFoundError:
            logger.info("app.lead_agent_unavailable", phase="2-only")

    app.state.settings = settings
    app.state.store = store
    app.state.bus = bus
    app.state.observers = observers
    app.state.llm = llm
    app.state.llm_registry = llm_registry
    app.state.default_backend = default_backend
    app.state.tools = registry
    app.state.lead_agent = lead_agent

    async def tick() -> None:
        await run_refresh(store=store, observers=observers, bus=bus)

    scheduler = Scheduler(
        refresh_minutes=settings.irma_refresh_minutes,
        on_tick=tick,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "app.ready",
        observers=[o.name for o in observers],
        lead_agent=lead_agent is not None,
        llm_backend=llm.backend if llm else None,
        llm_model=llm.model if llm else None,
        llm_registry=list(llm_registry.keys()),
        tools=registry.names(),
    )

    try:
        yield
    finally:
        scheduler.shutdown()
        for client in llm_registry.values():
            if isinstance(client, OllamaLLM):
                await client.aclose()
        await store.close()
        logger.info("app.shutdown")


def create_app() -> FastAPI:
    """Application factory consumed by `uvicorn.run(..., factory=True)`."""
    configure_logging()
    app = FastAPI(
        title="Irma API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(signals_router, prefix="/api/v1")
    app.include_router(state_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(brief_router, prefix="/api/v1")
    app.include_router(integrations_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"app": "irma-api", "version": "0.1.0"}

    return app
