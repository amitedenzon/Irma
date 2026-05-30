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
from irma_api.config import get_settings, secret_value_or_none
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
from irma_api.tools.calendar import CreateCalendarEventTool, ReadCalendarTool
from irma_api.tools.projects import CreateProjectTool, ListProjectsTool
from irma_api.tools.resend import ResendSendTool
from irma_api.tools.tasks import CompleteTaskTool, CreateTaskTool, ListTasksTool

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
    resend_key = secret_value_or_none(settings.resend_api_key)
    send_email_tool: ResendSendTool | None = None
    if resend_key is not None and settings.irma_user_email:
        send_email_tool = ResendSendTool(settings)
        tools.append(send_email_tool)
    else:
        logger.info(
            "tools.send_email_disabled",
            missing=[
                key
                for key, val in (
                    ("RESEND_API_KEY", resend_key),
                    ("IRMA_USER_EMAIL", settings.irma_user_email),
                )
                if not val
            ],
        )
    calendar_keys = {
        "GOOGLE_OAUTH_CLIENT_ID": secret_value_or_none(settings.google_oauth_client_id),
        "GOOGLE_OAUTH_CLIENT_SECRET": secret_value_or_none(settings.google_oauth_client_secret),
        "GOOGLE_OAUTH_REFRESH_TOKEN": secret_value_or_none(settings.google_oauth_refresh_token),
    }
    calendar_missing = [k for k, v in calendar_keys.items() if v is None]
    read_calendar_tool: ReadCalendarTool | None = None
    if not calendar_missing:
        read_calendar_tool = ReadCalendarTool(settings)
        tools.append(read_calendar_tool)
        tools.append(CreateCalendarEventTool(settings))
    else:
        logger.info("tools.calendar_disabled", missing=calendar_missing)

    tools.append(ListProjectsTool(store))
    tools.append(CreateProjectTool(store))
    tools.append(ListTasksTool(store))
    tools.append(CreateTaskTool(store))
    tools.append(CompleteTaskTool(store))

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

    daily_brief_job = None
    if llm is not None and send_email_tool is not None:
        from irma_api.agents.daily_brief import DailyBriefService
        from irma_api.runtime.daily_job import DailyBriefJob

        daily_service = DailyBriefService(
            settings=settings,
            llm=llm,
            store=store,
            observers=observers,
            bus=bus,
            calendar=read_calendar_tool,
        )
        daily_brief_job = DailyBriefJob(
            service=daily_service, sender=send_email_tool, settings=settings
        )
    else:
        logger.info(
            "app.daily_brief_disabled",
            has_llm=llm is not None,
            has_email=send_email_tool is not None,
        )
    app.state.daily_brief_job = daily_brief_job

    async def tick() -> None:
        await run_refresh(store=store, observers=observers, bus=bus)

    scheduler = Scheduler(
        refresh_minutes=settings.irma_refresh_minutes,
        on_tick=tick,
    )
    scheduler.start()
    app.state.scheduler = scheduler

    if daily_brief_job is not None and settings.irma_daily_brief_enabled:
        async def daily_tick() -> None:
            await daily_brief_job.run_once()

        scheduler.add_daily_job(
            daily_tick,
            hour=settings.irma_brief_hour,
            timezone=settings.irma_brief_timezone,
        )
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
