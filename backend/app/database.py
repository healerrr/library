from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def initialize_database() -> None:
    """Create the lightweight local database without bypassing Alembic in PostgreSQL."""
    if engine.dialect.name != "sqlite":
        return

    database_path = make_url(settings.database_url).database
    if database_path and database_path != ":memory:":
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    # Importing models registers all mapped tables on Base.metadata.
    from app import models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # Older local databases predate site-wide deduplication. Clean them
        # before adding the invariant so existing installations self-repair.
        await connection.execute(
            text(
                "DELETE FROM content_blocks "
                "WHERE id NOT IN ("
                "SELECT MIN(id) FROM content_blocks GROUP BY site_id, content_hash"
                ")"
            )
        )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_content_blocks_site_hash "
                "ON content_blocks (site_id, content_hash)"
            )
        )


async def close_database() -> None:
    await engine.dispose()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
