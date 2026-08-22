"""Fire DEX backend entry point.

Milestone 1 scope: the application boots, logs in a structured way, allows
the frontend through CORS, and answers a health check. Nothing else yet.

Run it with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import AppMode, Settings, get_settings
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
    """Startup and shutdown hooks.

    Database connections, provider clients and the LLM pool will be opened
    here in later milestones. Right now it just announces itself, which is
    genuinely useful: if you cannot see this line, the app never started.
    """
    log.info(
        "fire_dex_starting",
        version=settings.app_version,
        mode=settings.app_mode.value,
        debug=settings.debug,
    )

    if settings.app_mode is AppMode.PRODUCTION:
        # Loud, because production mode means mainnet reads are permitted.
        log.warning("production_mode_enabled", note="mainnet data access is allowed")

    yield

    log.info("fire_dex_shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Agentic AI-Powered Multi-Chain Smart Wallet & "
        "Decentralized Asset Intelligence Platform"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# The frontend runs on a different port during development, so the browser
# treats it as a different origin. Without this it cannot call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    The frontend polls this to show the backend status pill in the header,
    so it must stay cheap and dependency-free. When the database and
    external providers arrive they get their own /health/ready endpoint
    rather than being bolted onto this one.
    """
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        mode=settings.app_mode,
        timestamp=datetime.now(timezone.utc),
    )
