"""Console entrypoint: ``python -m nofari_api`` and the ``nofari-api`` script.

Boots uvicorn with the FastAPI app factory so the lifespan hooks own the
SQLite connection, observers, scheduler, and AgentState bus.
"""

from __future__ import annotations

import uvicorn

from nofari_api.config import get_settings
from nofari_api.logging import configure_logging


def main() -> None:
    configure_logging()
    settings = get_settings()
    uvicorn.run(
        "nofari_api.app:create_app",
        factory=True,
        host=settings.nofari_api_host,
        port=settings.nofari_api_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
