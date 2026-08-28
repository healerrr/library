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
        site_columns = {
            row[1] for row in (await connection.execute(text("PRAGMA table_info(sites)"))).all()
        }
        if "site_type" not in site_columns:
            await connection.execute(
                text("ALTER TABLE sites ADD COLUMN site_type VARCHAR(32) NOT NULL DEFAULT 'baseline'")
            )
        if "site_scheme" not in site_columns:
            await connection.execute(
                text("ALTER TABLE sites ADD COLUMN site_scheme VARCHAR(8) NOT NULL DEFAULT 'https'")
            )
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_site_type ON sites (site_type)"))
        policy_columns = {
            "include_patterns": "JSON NOT NULL DEFAULT '[]'",
            "exclude_patterns": "JSON NOT NULL DEFAULT '[]'",
            "allowed_query_params": "JSON NOT NULL DEFAULT '[]'",
            "crawler_max_pages": "INTEGER",
            "request_delay_ms": "INTEGER NOT NULL DEFAULT 0",
            "min_crawl_coverage": "FLOAT NOT NULL DEFAULT 0.7",
        }
        for column_name, column_type in policy_columns.items():
            if column_name not in site_columns:
                await connection.execute(
                    text(f"ALTER TABLE sites ADD COLUMN {column_name} {column_type}")
                )
        block_columns = {
            row[1] for row in (await connection.execute(text("PRAGMA table_info(content_blocks)"))).all()
        }
        if "embedding_version" not in block_columns:
            await connection.execute(
                text(
                    "ALTER TABLE content_blocks ADD COLUMN embedding_version "
                    "VARCHAR(255) NOT NULL DEFAULT 'hashing:512'"
                )
            )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_content_blocks_embedding_version "
                "ON content_blocks (embedding_version)"
            )
        )
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


async def recover_interrupted_jobs() -> None:
    """Ensure a process restart cannot leave jobs permanently marked as running."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE background_jobs SET status = 'error', progress = 0, "
                "error = '服务重启，任务已中断，请重新执行', finished_at = CURRENT_TIMESTAMP "
                "WHERE status IN ('queued', 'running')"
            )
        )
        await connection.execute(
            text(
                "UPDATE crawl_runs SET status = 'error', finished_at = CURRENT_TIMESTAMP "
                "WHERE status = 'running'"
            )
        )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
