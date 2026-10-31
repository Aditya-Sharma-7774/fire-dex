"""Fire DEX backend entry point.

Builds the application, applies the security middleware, and mounts the
chain, market and analysis routers. Start it with START.bat, or directly:

    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from app.api.v1 import chains as chains_router
from app.api.v1 import analysis as analysis_router
from app.api.v1 import market as market_router
from app.config import AppMode, Settings, get_settings
from app.core.errors import FireDexError, firedex_error_handler
from app.core.logging import configure_logging, get_logger

settings: Settings = get_settings()
configure_logging(level=settings.log_level, json_output=settings.log_json)
log = get_logger(__name__)


# ---------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------
# Every endpoint gets an explicit response model. FastAPI uses these to
# generate the OpenAPI schema, which we later turn into TypeScript types
# for the frontend -- so the two halves cannot silently drift apart.


class HealthResponse(BaseModel):
    """Reported by GET /health."""

    status: str = Field(description="'ok' when the service is running")
    app: str = Field(description="Application name")
    version: str = Field(description="Application version")
    mode: AppMode = Field(description="Safety regime: development, testnet or production")
    timestamp: datetime = Field(description="Server time in UTC when the check ran")


class RootResponse(BaseModel):
    """Reported by GET /."""

    name: str
    version: str
    docs: str
    health: str


# ---------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    Applies any pending database migrations, then primes the price cache and
    keeps it primed, so a user request is a cache hit rather than a cold
    network call. Both background tasks are cancelled on shutdown.
    """
    log.info(
        "fire_dex_starting",
        version=settings.app_version,
        mode=settings.app_mode.value,
    )

    from app.database.session import init_database
    from app.market.service import get_market_service

    await init_database()

    # Prime the price cache and keep it primed, so a user request is
    # essentially always a cache hit rather than a cold network call.
    market = get_market_service()
    warm_task = asyncio.create_task(market.warm())
    refresh_task = asyncio.create_task(market.keep_warm())

    if settings.app_mode is AppMode.PRODUCTION:
        # Loud, because production mode means mainnet reads are permitted.
        log.warning("production_mode_enabled", note="mainnet data access is allowed")

    yield

    for task in (warm_task, refresh_task):
        task.cancel()

    from app.blockchain import jsonrpc

    await jsonrpc.aclose()

    log.info("fire_dex_shutdown")


class SecurityHeadersMiddleware:
    """Adds standard hardening headers to every response.

    Pure ASGI rather than Starlette's `@app.middleware("http")`, which wraps
    the response body and is known to misbehave with streaming responses --
    and agent progress is streamed to the browser over Server-Sent Events.
    This only touches the response start, never the body.
    """

    HEADERS = {
        b"x-content-type-options": b"nosniff",
        b"x-frame-options": b"DENY",
        b"referrer-policy": b"no-referrer",
        b"cache-control": b"no-store",
    }

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [(k, v) for k, v in self.HEADERS.items() if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Interactive API docs are a map of every endpoint, which is useful while
# developing and an unnecessary disclosure in production.
_docs_enabled = settings.app_mode is not AppMode.PRODUCTION

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Agentic AI-Powered Multi-Chain Smart Wallet & "
        "Decentralized Asset Intelligence Platform"
    ),
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# The frontend runs on a different port, so the browser treats it as a
# different origin. Only the listed origins may call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)
# Added last so it runs first: a request with a foreign Host header is
# refused before any route or other middleware sees it.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

# One handler turns every deliberate error into a consistent JSON shape,
# so no route needs its own try/except for expected failures.
app.add_exception_handler(FireDexError, firedex_error_handler)  # type: ignore[arg-type]

app.include_router(chains_router.router, prefix="/api/v1")
app.include_router(market_router.router, prefix="/api/v1")
app.include_router(analysis_router.router, prefix="/api/v1")


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@app.get("/", response_model=RootResponse, tags=["meta"])
async def root() -> RootResponse:
    """Point a curious visitor at the interesting URLs."""
    return RootResponse(
        name=settings.app_name,
        version=settings.app_version,
        docs="/docs",
        health="/health",
    )


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness check.

    The frontend polls this to know whether the backend is reachable, so it
    stays cheap and touches neither the database nor any provider.
    """
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        mode=settings.app_mode,
        timestamp=datetime.now(timezone.utc),
    )
