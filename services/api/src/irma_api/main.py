"""Console entrypoint: ``python -m irma_api`` and the ``irma-api`` script.

Default behavior boots uvicorn with the FastAPI app factory. Subcommands
implement one-shot operations (OAuth bootstrap, etc.) that exit cleanly
without entering the web server.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import structlog
import uvicorn

from irma_api.auth.google_oauth import OAuthCancelled, run_installed_app_flow
from irma_api.config import get_settings
from irma_api.logging import configure_logging

logger = structlog.get_logger(__name__)


def _serve() -> None:
    settings = get_settings()
    uvicorn.run(
        "irma_api.app:create_app",
        factory=True,
        host=settings.irma_api_host,
        port=settings.irma_api_port,
        log_config=None,
        access_log=False,
    )


def _write_refresh_token_to_env(
    env_path: Path, refresh_token: str, *, overwrite: bool
) -> None:
    """Update or append GOOGLE_OAUTH_REFRESH_TOKEN in the given .env file."""
    existing = env_path.read_text() if env_path.exists() else ""
    line_re = re.compile(
        r"^GOOGLE_OAUTH_REFRESH_TOKEN=.*$", flags=re.MULTILINE
    )
    if line_re.search(existing):
        if not overwrite:
            print(
                "Refusing to overwrite existing GOOGLE_OAUTH_REFRESH_TOKEN. "
                "Re-run with --force.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        new_content = line_re.sub(
            f"GOOGLE_OAUTH_REFRESH_TOKEN={refresh_token}", existing
        )
    else:
        sep = "" if existing.endswith("\n") or not existing else "\n"
        new_content = f"{existing}{sep}GOOGLE_OAUTH_REFRESH_TOKEN={refresh_token}\n"
    env_path.write_text(new_content)


def _cmd_auth_google(args: argparse.Namespace) -> None:
    settings = get_settings()
    if (
        settings.google_oauth_client_id is None
        or settings.google_oauth_client_secret is None
    ):
        print(
            "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are required "
            "in .env before running `auth google`. See .env.example.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    env_path = Path(".env")
    has_existing = (
        env_path.exists()
        and "GOOGLE_OAUTH_REFRESH_TOKEN=" in env_path.read_text()
    )
    overwrite = bool(args.force)
    if has_existing and not overwrite and sys.stdin.isatty():
        answer = input("Overwrite existing refresh token? [y/N] ").strip().lower()
        overwrite = answer == "y"

    try:
        result = asyncio.run(
            run_installed_app_flow(
                client_id=settings.google_oauth_client_id.get_secret_value(),
                client_secret=settings.google_oauth_client_secret.get_secret_value(),
            )
        )
    except OAuthCancelled as exc:
        print(f"OAuth cancelled: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _write_refresh_token_to_env(env_path, result.refresh_token, overwrite=overwrite)
    print("Refresh token saved to .env. Restart `irma-api` to pick it up.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irma-api")
    sub = parser.add_subparsers(dest="cmd")

    auth = sub.add_parser("auth", help="OAuth bootstrap commands")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_google = auth_sub.add_parser("google", help="Grant Google Calendar (read-only)")
    auth_google.add_argument(
        "--force", action="store_true", help="Overwrite existing refresh token"
    )
    auth_google.set_defaults(func=_cmd_auth_google)

    return parser


def run_cli(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        _serve()
        return
    args.func(args)


def main() -> None:
    run_cli(sys.argv[1:])


if __name__ == "__main__":
    main()
