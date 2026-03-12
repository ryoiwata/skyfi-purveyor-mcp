"""FastAPI application — health endpoint, webhooks, confirmation pages."""

from __future__ import annotations

import datetime
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

log = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiting middleware.

    Applies tiered limits per SPEC §6.1:
    - /webhooks/*: 100/min per source IP
    - POST /confirm/*: 5/hour per API key
    - All other: 60/min per API key (reads dominate MCP traffic)

    Adds X-RateLimit-* headers to every response.
    Returns 429 with Retry-After when a limit is exceeded.
    """

    def __init__(self, app: ASGIApp, rate_limiter: Any) -> None:
        super().__init__(app)
        self._rl = rate_limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        from purveyor.core.rate_limiter import resolve_rate_limit_key

        key, limit, window = resolve_rate_limit_key(request)
        result = await self._rl.check_rate_limit(key, limit, window)

        if not result.allowed:
            log.info(
                "rate_limit_exceeded",
                path=request.url.path,
                key_prefix=key[:20],
            )
            return JSONResponse(
                content={
                    "error": "rate_limited",
                    "message": "Too many requests. Please slow down.",
                    "retry_after": result.retry_after,
                },
                status_code=429,
                headers={
                    "Retry-After": str(int(result.retry_after or 1)),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(result.reset_at)),
                },
            )

        inner: Response = await call_next(request)
        inner.headers["X-RateLimit-Limit"] = str(limit)
        inner.headers["X-RateLimit-Remaining"] = str(result.remaining)
        inner.headers["X-RateLimit-Reset"] = str(int(result.reset_at))
        return inner


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: init DB, rate limiter, Sentry, and expose state."""
    log.info("fastapi_startup")

    # Access settings stored on app.state by create_app
    settings: Any = app.state.settings

    # --- Sentry integration (Task 4.2) ---
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            # Exclude rate-limit responses and business errors from Sentry
            before_send=_sentry_before_send,  # type: ignore[arg-type]
        )
        log.info("sentry_initialized")

    from purveyor.models.database import create_engine, create_session_factory, init_db

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)
    app.state.session_factory = session_factory
    # Flag: use SKIP LOCKED only for Postgres
    app.state.use_skip_locked = "postgresql" in settings.database_url
    # Shared secret for webhook endpoint authentication
    app.state.webhook_secret = secrets.token_urlsafe(32)

    # Start rate limiter sweep (MemoryRateLimiter only)
    rate_limiter = app.state.rate_limiter
    if hasattr(rate_limiter, "start_sweep"):
        rate_limiter.start_sweep()

    # Signal that the server is fully ready
    app.state.ready = True
    log.info("fastapi_startup_complete")

    yield

    # Cleanup
    app.state.ready = False
    await rate_limiter.close()
    await engine.dispose()
    log.info("fastapi_shutdown")


def _sentry_before_send(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
    """Filter Sentry events to exclude expected business errors and 429s.

    Args:
        event: Sentry event dict.
        hint: Hint dict containing the original exception.

    Returns:
        The event to send, or None to discard it.
    """
    from purveyor.core.errors import ToolError

    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]
        if isinstance(exc, ToolError):
            # Business errors are expected — don't send to Sentry
            return None

    # Discard 429 responses
    status_code = event.get("extra", {}).get("status_code")
    if status_code == 429:
        return None

    return event


def create_app(settings: Any | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional Settings instance. Loads from environment if not provided.
    """
    from purveyor.core.config import load_settings
    from purveyor.core.logging import setup_logging
    from purveyor.core.rate_limiter import get_rate_limiter

    if settings is None:
        settings = load_settings()

    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    app = FastAPI(
        title="Purveyor MCP Server",
        description="Remote MCP server wrapping the SkyFi Platform API",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # Store settings and rate limiter on app.state so _lifespan can access them
    app.state.settings = settings
    app.state.ready = False
    rate_limiter = get_rate_limiter(settings)
    app.state.rate_limiter = rate_limiter

    # Rate limiting middleware (applied before CORS so headers are always present)
    app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)

    # CORS — default allow-all, configurable via ALLOWED_ORIGINS
    origins = settings.allowed_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount MCP server at /mcp
    from purveyor.server import mcp

    app.mount("/mcp", mcp.streamable_http_app())

    # Webhook routes (real implementation — Task 3.3)
    from purveyor.webhooks.receiver import router as webhook_router

    app.include_router(webhook_router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        """Health check: reports DB, SkyFi API, and Redis status."""
        start = time.monotonic()
        result: dict[str, Any] = {
            "status": "healthy",
            "database": "ok",
            "skyfi_api": "ok",
            "redis": "skipped",
        }
        status_code = 200

        # Database connectivity check
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is not None:
            try:
                from sqlalchemy import text

                async with session_factory() as session:
                    await session.execute(text("SELECT 1"))
            except Exception as exc:
                log.warning("health_database_unreachable", error=str(exc))
                result["database"] = f"error: {type(exc).__name__}"
                result["status"] = "degraded"
                status_code = 503
        else:
            # Session factory not yet initialized (before lifespan completes)
            result["database"] = "initializing"

        # Check SkyFi API reachability
        try:
            from purveyor.core.skyfi_client import SkyFiClient

            cfg = settings
            temp_client = SkyFiClient(api_key=cfg.skyfi_api_key or "")
            await temp_client.ping()
            await temp_client.close()
        except Exception as exc:
            log.warning("health_skyfi_unreachable", error=str(exc))
            result["skyfi_api"] = f"error: {type(exc).__name__}"
            if result["status"] == "healthy":
                result["status"] = "degraded"
            status_code = 503

        # Redis check (degraded but not 503 — caching is optional)
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(settings.redis_url)
                await r.ping()  # type: ignore[misc]
                await r.aclose()
                result["redis"] = "ok"
            except Exception as exc:
                log.warning("health_redis_unreachable", error=str(exc))
                result["redis"] = f"error: {type(exc).__name__}"
                # Redis being down is degraded but not fatal (caching optional)
                if result["status"] == "healthy":
                    result["status"] = "degraded"

        result["duration_ms"] = round((time.monotonic() - start) * 1000)
        result["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()

        return JSONResponse(content=result, status_code=status_code)

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Kubernetes readiness probe — returns 200 only after full startup."""
        is_ready: bool = getattr(request.app.state, "ready", False)
        if is_ready:
            return JSONResponse(content={"status": "ready"})
        return JSONResponse(content={"status": "starting"}, status_code=503)

    # ------------------------------------------------------------------
    # Confirmation page routes
    # ------------------------------------------------------------------

    @app.get("/confirm/{token}", response_class=HTMLResponse)
    async def get_confirmation_page(request: Request, token: str) -> HTMLResponse:
        """Render the order confirmation page for a given Fernet token.

        Decrypts the token to extract order details, then looks up the
        confirmation record in the DB to determine the current state.
        """
        from purveyor.core.confirmation import (
            decrypt_confirmation_token,
            get_confirmation_by_token,
        )
        from purveyor.core.errors import ToolError

        cur_settings: Any = request.app.state.settings
        session_factory = request.app.state.session_factory

        async with session_factory() as session:
            record = await get_confirmation_by_token(session, token)

        # Token not in DB at all
        if record is None:
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {
                    "state": "expired",
                    "error_message": "This order link is invalid or has expired.",
                },
                status_code=410,
            )

        # Map DB status to template state
        if record.status == "placed":
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {
                    "state": "already_used",
                    "already_used_action": "confirmed and placed",
                    "skyfi_order_id": str(record.skyfi_order_id) if record.skyfi_order_id else None,
                },
                status_code=409,
            )
        if record.status == "cancelled":
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {
                    "state": "already_used",
                    "already_used_action": "cancelled",
                },
                status_code=409,
            )
        if record.status == "expired":
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {"state": "expired"},
                status_code=410,
            )

        # Status is "pending" — decrypt token to render order details
        try:
            payload = decrypt_confirmation_token(token, cur_settings.fernet_key)
        except ToolError:
            # Token is cryptographically expired or invalid
            async with session_factory() as session:
                rec = await get_confirmation_by_token(session, token)
                if rec is not None and rec.status == "pending":
                    rec.status = "expired"
                    await session.commit()
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {"state": "expired"},
                status_code=410,
            )

        order_type: str = payload.get("order_type", record.order_type)
        order_params: dict[str, Any] = payload.get("order_params", {})
        estimated_cost_cents: int = payload.get(
            "estimated_cost_cents", record.estimated_cost_cents or 0
        )

        estimated_cost_dollars = f"${estimated_cost_cents / 100:,.2f}"

        # Build cost breakdown and location description from order_params
        location_description = _extract_location_description(order_params)
        cost_breakdown = _build_cost_breakdown(order_params, estimated_cost_cents)

        product_type: str | None = order_params.get("productType") or order_params.get(
            "product_type"
        )
        resolution: str | None = order_params.get("resolution")

        expires_at_str = record.expires_at.strftime("%Y-%m-%d %H:%M UTC")

        return templates.TemplateResponse(
            request,
            "confirm.html",
            {
                "state": "pending",
                "order_type": order_type,
                "location_description": location_description,
                "product_type": product_type,
                "resolution": resolution,
                "estimated_cost_dollars": estimated_cost_dollars,
                "cost_breakdown": cost_breakdown,
                "expires_at_utc": f"This link expires at {expires_at_str}",
                "skyfi_order_id": None,
                "error_message": None,
            },
        )

    @app.post("/confirm/{token}", response_class=HTMLResponse)
    async def post_confirmation_action(
        request: Request,
        token: str,
        action: str = Form(...),
    ) -> HTMLResponse:
        """Handle confirm or cancel POST from the confirmation page form.

        The form sends `action=confirm` or `action=cancel`.
        """
        from purveyor.core.confirmation import cancel_confirmation, confirm_order
        from purveyor.core.errors import ErrorCode, ToolError

        cur_settings: Any = request.app.state.settings
        session_factory = request.app.state.session_factory
        use_skip_locked: bool = request.app.state.use_skip_locked

        if action == "cancel":
            from purveyor.core.confirmation import get_confirmation_by_token

            async with session_factory() as session:
                record = await get_confirmation_by_token(session, token)
                if record is None:
                    return templates.TemplateResponse(
                        request,
                        "confirm.html",
                        {"state": "expired"},
                        status_code=410,
                    )
                try:
                    await cancel_confirmation(session, record.id)
                except ToolError as exc:
                    if exc.code == ErrorCode.ORDER_ALREADY_PLACED:
                        return templates.TemplateResponse(
                            request,
                            "confirm.html",
                            {
                                "state": "already_used",
                                "already_used_action": "confirmed and placed",
                                "skyfi_order_id": str(record.skyfi_order_id)
                                if record.skyfi_order_id
                                else None,
                            },
                            status_code=409,
                        )
                    return templates.TemplateResponse(
                        request,
                        "confirm.html",
                        {"state": "error", "error_message": exc.message},
                        status_code=400,
                    )

            return templates.TemplateResponse(
                request,
                "confirm.html",
                {"state": "cancelled"},
            )

        # action == "confirm"
        async with session_factory() as session:
            try:
                record, order_response = await confirm_order(
                    session=session,
                    token=token,
                    fernet_key=cur_settings.fernet_key,
                    use_skip_locked=use_skip_locked,
                )
            except ToolError as exc:
                if exc.code in (ErrorCode.ORDER_EXPIRED,):
                    return templates.TemplateResponse(
                        request,
                        "confirm.html",
                        {"state": "expired"},
                        status_code=410,
                    )
                if exc.code == ErrorCode.ORDER_ALREADY_PLACED:
                    return templates.TemplateResponse(
                        request,
                        "confirm.html",
                        {
                            "state": "already_used",
                            "already_used_action": "confirmed and placed",
                        },
                        status_code=409,
                    )
                if exc.code == ErrorCode.ORDER_ALREADY_CANCELLED:
                    return templates.TemplateResponse(
                        request,
                        "confirm.html",
                        {
                            "state": "already_used",
                            "already_used_action": "cancelled",
                        },
                        status_code=409,
                    )
                return templates.TemplateResponse(
                    request,
                    "confirm.html",
                    {"state": "error", "error_message": exc.message},
                    status_code=502,
                )

        return templates.TemplateResponse(
            request,
            "confirm.html",
            {
                "state": "confirmed",
                "skyfi_order_id": str(order_response.id),
            },
        )

    return app


# ------------------------------------------------------------------
# Private helpers for template rendering
# ------------------------------------------------------------------


def _extract_location_description(order_params: dict[str, Any]) -> str:
    """Extract a human-readable location description from order parameters.

    Args:
        order_params: Decrypted order_params dict from the confirmation token.

    Returns:
        A short location description string for display.
    """
    # Try common field names used in tasking/archive orders
    for key in ("locationDescription", "location_description", "location", "aoi_description"):
        val: Any = order_params.get(key)
        if val and isinstance(val, str):
            return str(val)

    # Fall back to a truncated WKT if available
    aoi: Any = order_params.get("aoi") or order_params.get("geometry")
    if aoi and isinstance(aoi, str):
        aoi_str: str = str(aoi)
        return aoi_str[:80] + ("..." if len(aoi_str) > 80 else "")

    return "Custom AOI"


def _build_cost_breakdown(order_params: dict[str, Any], estimated_cost_cents: int) -> str:
    """Build a short cost breakdown string for the confirmation page.

    Args:
        order_params: Decrypted order_params dict from the confirmation token.
        estimated_cost_cents: Estimated cost in integer cents.

    Returns:
        A short cost breakdown string, e.g. "25 sq km x $17/sq km = $425.00".
    """
    area = order_params.get("aoi_area_sq_km") or order_params.get("area_sq_km")
    price_per_sq_km = order_params.get("price_per_sq_km")

    if area and price_per_sq_km:
        total = estimated_cost_cents / 100
        return f"{area:.1f} sq km x ${price_per_sq_km:.2f}/sq km = ${total:,.2f}"

    if estimated_cost_cents:
        return f"Estimated total: ${estimated_cost_cents / 100:,.2f}"

    return "Cost determined at order placement"
