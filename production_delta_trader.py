#!/usr/bin/env python3
"""Delta Strangle Control Plane CLI.

This command-line entrypoint supersedes the legacy monolithic script. It
provides helpers to boot the FastAPI backend, verify configuration, and run
simple async smoke tests.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import typer

ROOT = Path(__file__).resolve().parent
backend_path = ROOT / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from backend.app.core.config import get_settings

try:
    import uvicorn
except ImportError as exc:  # pragma: no cover - surfaced during CLI usage
    raise SystemExit(
        "uvicorn is required. Install backend extras with: pip install -e backend[dev]"
    ) from exc

cli = typer.Typer(add_completion=False, help="Delta Strangle Control Plane CLI")
logger = logging.getLogger("delta-cli")


@cli.command()
def runserver(host: str = "0.0.0.0", port: int = 8001, reload: bool = True) -> None:
    """Launch the FastAPI backend."""

    settings = get_settings()
    logger.info("Starting API server on %s:%s (%s)", host, port, settings.app_name)
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload, factory=False)


@cli.command()
def check() -> None:
    """Smoke test configuration loading."""

    settings = get_settings()
    typer.echo(f"Active settings: {settings.app_name} -> DB {settings.database_url}")


@cli.command()
def async_task(name: Optional[str] = None) -> None:
    """Run a minimal async task to ensure event loop readiness."""

    async def task(label: str) -> None:
        await asyncio.sleep(0.1)
        typer.echo(f"Async task completed for {label}")

    asyncio.run(task(name or "delta-strangle"))


@cli.command()
def version() -> None:
    """Display application metadata."""

    settings = get_settings()
    typer.echo(f"App: {settings.app_name}")


if __name__ == "__main__":
    cli()