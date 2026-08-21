from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database import Base


ID_TYPE = BigInteger().with_variant(Integer, "sqlite")
VECTOR_TYPE = Vector(get_settings().embedding_dimension).with_variant(JSON(), "sqlite")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sitemap_url: Mapped[str] = mapped_column(String(2048))
    site_type: Mapped[str] = mapped_column(String(32), default="baseline", server_default="baseline", index=True)
    include_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_query_params: Mapped[list[str]] = mapped_column(JSON, default=list)
    crawler_max_pages: Mapped[int | None] = mapped_column(Integer)
    request_delay_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    min_crawl_coverage: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    pages: Mapped[list["Page"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    jobs: Mapped[list["BackgroundJob"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    crawl_runs: Mapped[list["CrawlRun"]] = relationship(back_populates="site", cascade="all, delete-orphan")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", server_default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    site: Mapped[Site] = relationship(back_populates="jobs")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running", index=True)
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    previous_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retained_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stale_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prune_blocked: Mapped[bool] = mapped_column(default=False, server_default="0")
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    site: Mapped[Site] = relationship(back_populates="crawl_runs")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("site_id", "url", name="uq_pages_site_url"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(500))
    meta_description: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="pages")
    blocks: Mapped[list["ContentBlock"]] = relationship(back_populates="page", cascade="all, delete-orphan")


class ContentBlock(Base):
    __tablename__ = "content_blocks"
    __table_args__ = (Index("uq_content_blocks_site_hash", "site_id", "content_hash", unique=True),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ID_TYPE, ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    page_title: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2048))
    content_type: Mapped[str] = mapped_column(String(32))
    original_content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR_TYPE)
    embedding_version: Mapped[str] = mapped_column(String(255), default="unknown", server_default="unknown", index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    page: Mapped[Page] = relationship(back_populates="blocks")
    site: Mapped[Site] = relationship()


class SimilarityCheck(Base):
    __tablename__ = "similarity_checks"

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    input_content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    top_score: Mapped[float | None] = mapped_column(Float)
    results: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
