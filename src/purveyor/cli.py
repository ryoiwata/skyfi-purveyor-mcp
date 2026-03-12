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
)
def serve(local: bool, reload: bool, host: str, port: int, transport: str) -> None:
    """Run the Purveyor MCP server."""
    click.echo(f"Starting Purveyor (transport={transport}, local={local})")
    # Stub — full implementation in Phase 2


@main.command()
@click.option("--provider", default="anthropic", help="LLM provider")
@click.option("--workflow", type=click.Choice(["research", "monitor", "order"]), default=None)
@click.option("--query", default=None, help="Workflow query")
def demo(provider: str, workflow: str | None, query: str | None) -> None:
    """Run the interactive demo agent (stdio MCP transport)."""
    click.echo("Starting Purveyor demo agent...")
    # Stub — full implementation in Phase 5


@main.command("generate-key")
def generate_key() -> None:
    """Generate a new Fernet key for CONFIRMATION_SECRET_KEY."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    click.echo(key.decode())
