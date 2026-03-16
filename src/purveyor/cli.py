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

    # Always write startup message to stderr — stdout is reserved for MCP JSON-RPC
    # in stdio transport mode and should never receive non-protocol output.
    click.echo(
        f"Starting Purveyor (transport={transport}, local={local}, host={host}, port={port})",
        err=True,
    )

    if transport == "stdio":
        import asyncio

        from purveyor.server import mcp

        asyncio.run(mcp.run_stdio_async())
    else:
        import uvicorn

        if reload:
            from pathlib import Path

            import purveyor as _purveyor_pkg

            # Watch the installed package directory so reload fires on source changes
            # regardless of which directory the CLI is invoked from.
            src_dir = str(Path(_purveyor_pkg.__file__).parent)

            # uvicorn requires an import string (not an object) to enable reload
            uvicorn.run(
                "purveyor.app:create_app",
                factory=True,
                host=host,
                port=port,
                reload=True,
                reload_dirs=[src_dir],
                log_level="info",
            )
        else:
            from purveyor.app import create_app

            uvicorn.run(
                create_app(),
                host=host,
                port=port,
                reload=False,
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
