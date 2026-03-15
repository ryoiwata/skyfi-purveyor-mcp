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

from purveyor.core.webhook_store import order_webhook_events

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
    """FastAPI lifespan: init DB, rate limiter, Sentry, MCP session manager, and expose state."""
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

    # Run MCP StreamableHTTP session manager lifecycle.
    # The session manager creates an anyio task group that handles concurrent
    # MCP sessions. It must be started here because the mounted sub-app's own
    # lifespan is not triggered by FastAPI — only the root app's lifespan runs.
    mcp_session_manager = app.state.mcp_session_manager
    async with mcp_session_manager.run():
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
        redirect_slashes=False,
    )

    # Initialize MCP session manager eagerly so _lifespan can call .run() on it.
    # streamable_http_app() lazily creates the session manager on first call.
    from purveyor.server import mcp as mcp_server

    mcp_sub_app = mcp_server.streamable_http_app()
    app.state.mcp_session_manager = mcp_server.session_manager

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
        """Render the order confirmation page for a given base32-encoded token.

        The URL token is base32-encoded (A-Z2-7) to survive LLM URL normalization
        and Markdown rendering without corruption.  Decodes to the original Fernet
        token before DB lookup and decryption.
        """
        from purveyor.core.confirmation import (
            compute_token_hash,
            decrypt_confirmation_token,
            get_confirmation_by_token,
            url_token_to_fernet,
        )
        from purveyor.core.errors import ToolError

        cur_settings: Any = request.app.state.settings
        session_factory = request.app.state.session_factory

        # Decode base32 URL token → original Fernet token
        try:
            token = url_token_to_fernet(token)
        except Exception:
            log.warning("confirm_page_invalid_url_token")
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {"state": "expired", "error_message": "This order link is invalid or has expired."},
                status_code=410,
            )

        import hashlib

        token_hash = compute_token_hash(token)
        fernet_key_fingerprint = hashlib.sha256(cur_settings.fernet_key).hexdigest()[:8]
        log.info(
            "confirm_page_lookup",
            token_len=len(token),
            token_prefix=token[:12],
            token_hash_prefix=token_hash[:16],
            fernet_key_fingerprint=fernet_key_fingerprint,
        )

        async with session_factory() as session:
            record = await get_confirmation_by_token(session, token)

        # Token not in DB at all
        if record is None:
            log.warning(
                "confirm_page_record_not_found",
                token_hash_prefix=token_hash[:16],
            )
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

        # Status is "pending" — load order details for rendering.
        # New tokens store order params in DB (order_payload_json) to keep the URL
        # token short.  Old tokens (pre-migration b1c2d3e4f5a6) carry a full payload
        # in the Fernet token and need decryption for rendering.
        import json as _json

        order_params: dict[str, Any] = {}
        webhook_url: str | None = None

        if record.order_payload_json:
            # New path: order params in DB — no decryption needed for display
            stored = _json.loads(record.order_payload_json)
            order_params = stored.get("order_params", {})
            webhook_url = stored.get("webhook_url")
        else:
            # Old path: full payload in Fernet token — decrypt to render
            try:
                payload = decrypt_confirmation_token(token, cur_settings.fernet_key)
            except ToolError:
                log.warning(
                    "confirm_page_decrypt_failed",
                    token_hash_prefix=token_hash[:16],
                    record_status=record.status if record else None,
                )
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
            order_params = payload.get("order_params", {})
            webhook_url = payload.get("webhook_url")

        order_type: str = record.order_type
        estimated_cost_cents: int = record.estimated_cost_cents or 0

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
                "webhook_url": webhook_url,
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
        The URL token is base32-encoded; decoded to Fernet token before use.
        """
        from purveyor.core.confirmation import (
            cancel_confirmation,
            confirm_order,
            url_token_to_fernet,
        )
        from purveyor.core.errors import ErrorCode, ToolError

        cur_settings: Any = request.app.state.settings
        session_factory = request.app.state.session_factory
        use_skip_locked: bool = request.app.state.use_skip_locked

        # Decode base32 URL token → original Fernet token
        try:
            token = url_token_to_fernet(token)
        except Exception:
            log.warning("confirm_post_invalid_url_token")
            return templates.TemplateResponse(
                request,
                "confirm.html",
                {"state": "expired"},
                status_code=410,
            )

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

    # ------------------------------------------------------------------
    # Demo webhook receiver routes
    # ------------------------------------------------------------------

    @app.post("/webhooks/orders")
    async def receive_order_webhook(request: Request) -> JSONResponse:
        """Receive order status webhooks from SkyFi for demo/testing purposes.

        Stores up to 100 recent events in memory (not persisted across restarts).
        Returns 200 immediately — SkyFi has a 2-second webhook timeout.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        order_webhook_events.appendleft(
            {
                "received_at": datetime.datetime.now(datetime.UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "payload": body,
            }
        )
        log.info(
            "demo_webhook_received",
            total_stored=len(order_webhook_events),
            status=body.get("event", {}).get("status") if isinstance(body, dict) else None,
        )
        return JSONResponse(content={"status": "ok"})

    @app.get("/webhooks/orders")
    async def list_order_webhooks(limit: int = 20) -> JSONResponse:
        """List recently received order webhook events (demo endpoint).

        Args:
            limit: Maximum number of events to return (1-100).
        """
        limit = max(1, min(limit, 100))
        events = list(order_webhook_events)[:limit]
        return JSONResponse(
            content={
                "total_stored": len(order_webhook_events),
                "showing": len(events),
                "events": events,
            }
        )

    @app.get("/webhooks/orders/ui", response_class=HTMLResponse)
    async def webhook_events_ui() -> HTMLResponse:
        """Live-polling HTML viewer for demo order webhook events."""
        purveyor_url = ""
        # Try to get the configured base URL for display
        try:
            settings_obj: Any = app.state.settings
            purveyor_url = (
                settings_obj.confirmation_base_url
                or "http://localhost:8000"
            ).rstrip("/")
        except AttributeError:
            purveyor_url = "http://localhost:8000"

        webhook_url_display = f"{purveyor_url}/webhooks/orders"

        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Purveyor — Order Webhook Events</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: system-ui, sans-serif; max-width: 900px;
            margin: 40px auto; padding: 0 20px;
            background: #0d1117; color: #c9d1d9;
        }}
        h1 {{ color: #58a6ff; margin-bottom: 4px; }}
        .header-row {{
            display: flex; align-items: center; gap: 12px;
            flex-wrap: wrap; margin-bottom: 4px;
        }}
        .status-dot {{
            width: 10px; height: 10px; border-radius: 50%;
            background: #3fb950; flex-shrink: 0;
            box-shadow: 0 0 6px #3fb95088;
            transition: background 0.3s;
        }}
        .status-dot.disconnected {{ background: #f85149; box-shadow: 0 0 6px #f8514988; }}
        .meta {{ color: #8b949e; font-size: 13px; margin: 0 0 4px; }}
        .event-count {{ color: #58a6ff; font-weight: bold; }}
        .sound-toggle {{
            background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
            border-radius: 6px; padding: 3px 10px; font-size: 12px;
            cursor: pointer; user-select: none;
        }}
        .sound-toggle:hover {{ background: #30363d; }}
        .event {{
            background: #161b22; border: 1px solid #30363d;
            border-radius: 8px; padding: 16px; margin: 12px 0;
        }}
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(-16px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}
        .event-new {{ animation: slideIn 0.35s ease-out; }}
        .event-header {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
        .status {{ font-weight: bold; padding: 2px 8px; border-radius: 4px; }}
        .status-CREATED {{ background: #1f6feb33; color: #58a6ff; }}
        .status-STARTED {{ background: #d2992233; color: #d29922; }}
        .status-PROCESSING_COMPLETE {{ background: #23883333; color: #3fb950; }}
        .status-DELIVERY_COMPLETED {{ background: #23883333; color: #3fb950; }}
        .status-FAILED {{ background: #f8514933; color: #f85149; }}
        pre {{
            background: #0d1117; padding: 12px;
            border-radius: 4px; overflow-x: auto; font-size: 13px;
        }}
        .timestamp {{ color: #8b949e; font-size: 13px; }}
        .empty {{ text-align: center; padding: 60px; color: #8b949e; }}
        .order-link {{ color: #58a6ff; text-decoration: none; }}
        .order-link:hover {{ text-decoration: underline; }}
        code {{ background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
        #new-events-toast {{
            display: none; position: fixed; top: 16px; left: 50%;
            transform: translateX(-50%);
            background: #1f6feb; color: #fff;
            padding: 8px 20px; border-radius: 20px;
            font-size: 14px; font-weight: bold;
            cursor: pointer; z-index: 100;
            box-shadow: 0 4px 12px #0006;
            transition: opacity 0.2s;
        }}
        #new-events-toast:hover {{ background: #388bfd; }}
    </style>
</head>
<body>
    <h1>&#x1F6F0;&#xFE0F; Order Webhook Events</h1>
    <div class="header-row">
        <span class="status-dot" id="dot"></span>
        <span class="meta" id="updated">Connecting&hellip;</span>
        <span class="meta">&bull; <span class="event-count" id="count">0</span> events</span>
        <button class="sound-toggle" id="sound-btn" title="Toggle notification sound">&#x1F515; Sound off</button>
    </div>
    <p class="meta">Webhook URL: <code>{webhook_url_display}</code></p>
    <div id="events"></div>
    <div id="new-events-toast">New events &#x2191;</div>

    <script>
        // ── state ──────────────────────────────────────────────────────────
        let lastCount = 0;
        let lastTimestamp = null;
        let secondsSince = 0;
        let soundOn = false;
        let audioCtx = null;

        // ── sound ──────────────────────────────────────────────────────────
        document.getElementById('sound-btn').addEventListener('click', () => {{
            soundOn = !soundOn;
            document.getElementById('sound-btn').textContent =
                soundOn ? '\\uD83D\\uDD14 Sound on' : '\\uD83D\\uDD15 Sound off';
        }});

        function playPing() {{
            if (!soundOn) return;
            try {{
                if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, audioCtx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.15);
                gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.25);
                osc.start(audioCtx.currentTime);
                osc.stop(audioCtx.currentTime + 0.25);
            }} catch (e) {{}}
        }}

        // ── toast ──────────────────────────────────────────────────────────
        const toast = document.getElementById('new-events-toast');
        toast.addEventListener('click', () => {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
            toast.style.display = 'none';
        }});

        function isScrolledDown() {{
            return window.scrollY > 120;
        }}

        // ── event rendering ────────────────────────────────────────────────
        function buildEventEl(e, isNew) {{
            const p = e.payload || {{}};
            const status = (p.event && p.event.status) ? p.event.status : 'UNKNOWN';
            const orderInfo = p.order_info || p.orderInfo || {{}};
            const orderId = orderInfo.id || orderInfo.order_id || 'unknown';
            const orderType = orderInfo.order_type || orderInfo.orderType || '';
            const message = (p.event && p.event.message) ? p.event.message : '';
            const orderUrl = 'https://app.skyfi.com/orders/' + orderId;

            const div = document.createElement('div');
            div.className = 'event' + (isNew ? ' event-new' : '');
            div.dataset.ts = e.received_at || '';
            div.innerHTML =
                '<div class="event-header">'
                + '<span class="status status-' + status + '">' + status + '</span>'
                + '<span class="timestamp">' + (e.received_at || '') + '</span>'
                + '</div>'
                + '<div>Order: <a href="' + orderUrl + '" target="_blank" class="order-link">' + orderId + '</a>'
                + (orderType ? ' (' + orderType + ')' : '') + '</div>'
                + (message ? '<div>' + message + '</div>' : '')
                + '<details><summary>Full payload</summary><pre>'
                + JSON.stringify(p, null, 2).replace(/</g, '&lt;').replace(/>/g, '&gt;')
                + '</pre></details>';
            return div;
        }}

        function updateEventList(events, newCount) {{
            const container = document.getElementById('events');

            if (events.length === 0) {{
                container.innerHTML = '<div class="empty">No webhook events yet.<br>Place an order with webhook_url pointed here to see events.</div>';
                return;
            }}

            // Determine which events are new by comparing timestamps already in DOM
            const existing = new Set();
            container.querySelectorAll('.event[data-ts]').forEach(el => existing.add(el.dataset.ts));

            // Prepend new events (events are newest-first from the API)
            let addedCount = 0;
            for (let i = newCount - 1; i >= 0; i--) {{
                const e = events[i];
                const ts = e.received_at || '';
                if (!existing.has(ts)) {{
                    const el = buildEventEl(e, true);
                    container.insertBefore(el, container.firstChild);
                    addedCount++;
                }}
            }}

            // Remove the empty placeholder if present
            const empty = container.querySelector('.empty');
            if (empty) empty.remove();

            if (addedCount > 0) {{
                playPing();
                if (isScrolledDown()) {{
                    toast.style.display = 'block';
                }}
            }}
        }}

        // ── status / counter ───────────────────────────────────────────────
        const dot = document.getElementById('dot');
        const updatedEl = document.getElementById('updated');
        const countEl = document.getElementById('count');

        function setConnected(ok) {{
            dot.className = 'status-dot' + (ok ? '' : ' disconnected');
        }}

        function tick() {{
            secondsSince++;
            updatedEl.textContent = secondsSince === 0
                ? 'Just updated'
                : 'Last updated ' + secondsSince + 's ago';
        }}
        setInterval(tick, 1000);

        // ── poll ───────────────────────────────────────────────────────────
        async function poll() {{
            try {{
                const resp = await fetch('/webhooks/orders?limit=50');
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const data = await resp.json();
                setConnected(true);
                countEl.textContent = data.total_stored;

                const newCount = data.total_stored - lastCount;
                if (data.total_stored !== lastCount) {{
                    updateEventList(data.events, newCount > 0 ? newCount : data.events.length);
                    lastCount = data.total_stored;
                    secondsSince = 0;
                    updatedEl.textContent = 'Just updated';
                }} else if (lastCount === 0) {{
                    // Ensure empty state renders on first load
                    updateEventList([], 0);
                    secondsSince = 0;
                    updatedEl.textContent = 'Just updated';
                }}
            }} catch (e) {{
                setConnected(false);
                updatedEl.textContent = 'Connection error — retrying\u2026';
            }}
            setTimeout(poll, 3000);
        }}

        // Hide toast when user scrolls back to top
        window.addEventListener('scroll', () => {{
            if (!isScrolledDown()) toast.style.display = 'none';
        }});

        poll();
    </script>
</body>
</html>"""
        )

    # Mount MCP server at root so the sub-app receives the full /mcp path.
    # streamable_http_app() creates a Starlette app with an internal route at
    # /mcp — mounting at /mcp would strip that prefix, causing 404. Mounting at
    # / (after all other routes) lets specific routes match first, then falls
    # through to the MCP app for /mcp requests.
    app.mount("/", mcp_sub_app)

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
