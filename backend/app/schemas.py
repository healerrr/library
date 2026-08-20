from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


VALID_SITE_STATUSES = {"active", "paused", "error"}


def normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if not parsed.hostname:
        raise ValueError("请输入有效域名")
    return parsed.hostname.encode("idna").decode("ascii").rstrip(".")


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)
    sitemap_url: str = Field(min_length=10, max_length=2048)
    status: str = "active"

    @field_validator("name", "sitemap_url", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("domain", mode="before")
    @classmethod
    def clean_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("sitemap_url")
    @classmethod
    def sitemap_must_be_http(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Sitemap 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password:
            raise ValueError("Sitemap 地址不能包含认证信息")
        return value

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in VALID_SITE_STATUSES:
            raise ValueError("无效的网站状态")
        return value


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sitemap_url: str | None = Field(default=None, min_length=10, max_length=2048)
    status: str | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_SITE_STATUSES:
            raise ValueError("无效的网站状态")
        return value


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str
    sitemap_url: str
    status: str
    last_crawled_at: datetime | None
    created_at: datetime
    page_count: int = 0
    block_count: int = 0


class CrawlSummary(BaseModel):
    site_id: int
    pages_discovered: int
    pages_crawled: int
    blocks_saved: int
    errors: list[str]


class ContentBlockOut(BaseModel):
    id: int
    site_id: int
    site_name: str
    page_id: int
    page_title: str | None
    url: str
    content_type: str
    original_content: str
    collected_at: datetime


class ContentBlockPage(BaseModel):
    items: list[ContentBlockOut]
    total: int
    page: int
    page_size: int
    pages: int


class HighlightSegment(BaseModel):
    text: str
    matched: bool


class SimilarityCheckRequest(BaseModel):
    content: str = Field(min_length=3, max_length=20000)
    limit: int = Field(default=10, ge=1, le=10)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class SimilarityResult(BaseModel):
    content_block_id: int
    overall_similarity: float
    risk_level: str
    original_content: str
    highlight_segments: list[HighlightSegment]
    site_id: int
    site_name: str
    page_title: str | None
    url: str
    content_type: str
    lexical_similarity: float
    semantic_similarity: float
    exact_match: bool
    chemical_ratio: float


class SimilarityCheckResponse(BaseModel):
    check_id: int
    result_count: int
    threshold: float
    results: list[SimilarityResult]


class StatsOut(BaseModel):
    sites: int
    pages: int
    content_blocks: int
    similarity_checks: int

