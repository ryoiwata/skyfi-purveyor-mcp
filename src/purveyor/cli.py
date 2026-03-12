"""CLI entry point for Purveyor."""

from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Purveyor — remote MCP server for SkyFi satellite imagery."""


@main.command()
@click.option("--local", is_flag=True, default=False, help="Run with SQLite (no external deps)")
@click.option("--reload", is_flag=True, default=False, help="Enable hot reload (dev)")
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind address")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["streamable-http", "stdio"]),
    show_default=True,
    help="Transport: streamable-http (default) or stdio",
)
def serve(local: bool, reload: bool, host: str, port: int, transport: str) -> None:
    """Run the Purveyor MCP server."""
    import os

    if local:
        os.environ.setdefault("LOCAL_MODE", "true")
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///purveyor.db")

    click.echo(
        f"Starting Purveyor (transport={transport}, local={local}, host={host}, port={port})"
    )

    if transport == "stdio":
        import asyncio

        from purveyor.server import mcp

        asyncio.run(mcp.run_stdio_async())
    else:
        import uvicorn

        from purveyor.app import create_app

        app = create_app()
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )


@main.command()
@click.option("--provider", default="anthropic", help="LLM provider (default: anthropic)")
@click.option(
    "--workflow",
    type=click.Choice(["research", "monitor", "order"]),
    default=None,
    help="Run a pre-built workflow",
)
@click.option("--query", default=None, help="Query for workflow mode")
def demo(provider: str, workflow: str | None, query: str | None) -> None:
    """Run the interactive demo agent (stdio MCP transport)."""
    from purveyor.demo.agent import run_demo

    run_demo(workflow=workflow, query=query)


@main.command("generate-key")
def generate_key() -> None:
    """Generate a new Fernet key for CONFIRMATION_SECRET_KEY."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    click.echo(key.decode())
