"""Database engine and session management.

SQLite for the prototype: no server, no Docker, no configuration. Because
everything goes through SQLAlchemy, moving to PostgreSQL later is a change
to one connection string.
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.logging import get_logger
from app.database.models import Base

log = get_logger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _database_path(url: str) -> Path | None:
    """Filesystem path for a SQLite URL, so we can create the directory."""
    marker = "sqlite+aiosqlite:///"
    if not url.startswith(marker):
        return None
    return Path(url[len(marker) :]).resolve()


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url

        # SQLite will not create a missing directory for the database file.
        path = _database_path(url)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_async_engine(url, echo=False, future=True)
        log.info("database_engine_created", url=url.split("://")[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


def _run_migrations_sync() -> None:
    """Bring the database up to the newest migration.

    Run in a worker thread because Alembic's API is synchronous.
    """
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(config, "head")


async def init_database() -> None:
    """Apply any outstanding migrations at startup.

    Migrations rather than `create_all`. Adding the signal and groundedness
    columns previously meant deleting the database, which would destroy
    recorded analyses -- and those analyses are the archive the 8th-semester
    work depends on. Versioned migrations mean a schema change never costs
    data again.

    Running them at startup keeps the promise that START.bat is the only
    command anyone needs.
    """
    # Make sure the directory exists before Alembic tries to open the file.
    get_engine()

    try:
        await asyncio.to_thread(_run_migrations_sync)
        log.info("database_migrated")
    except Exception as exc:  # noqa: BLE001
        # A failed migration must be loud. Falling back to create_all would
        # silently produce a schema that does not match the migration
        # history, which is far worse than refusing to start.
        log.error("database_migration_failed", error=str(exc))
        raise

    log.info("database_ready")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def reset_engine() -> None:
    """Dispose of the engine. Used by tests between cases."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
