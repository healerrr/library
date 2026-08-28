from datetime import datetime
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


VALID_SITE_STATUSES = {"active", "paused", "error"}
VALID_SITE_TYPES = {"baseline", "candidate"}


def normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if not parsed.hostname:
        raise ValueError("请输入有效域名")
    domain = parsed.hostname.encode("idna").decode("ascii").rstrip(".")
    # 保留非标准端口（http 非 80，https 非 443）
    if parsed.port:
        if parsed.scheme == "http" and parsed.port != 80:
            domain = f"{domain}:{parsed.port}"
        elif parsed.scheme == "https" and parsed.port != 443:
            domain = f"{domain}:{parsed.port}"
        elif parsed.scheme not in ("http", "https"):
            domain = f"{domain}:{parsed.port}"
    return domain


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)
    sitemap_url: str = Field(default="", max_length=2048)
    site_scheme: str = Field(default="https", pattern="^(http|https)$")
    status: str = "active"
    site_type: str = "baseline"
    include_patterns: list[str] = Field(default_factory=list, max_length=50)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=50)
    allowed_query_params: list[str] = Field(default_factory=list, max_length=30)
    crawler_max_pages: int | None = Field(default=None, ge=1, le=5000)
    request_delay_ms: int = Field(default=0, ge=0, le=5000)
    min_crawl_coverage: float = Field(default=0.7, ge=0.1, le=1.0)

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
        if not value:
            return value
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

    @field_validator("site_type")
    @classmethod
    def valid_site_type(cls, value: str) -> str:
        if value not in VALID_SITE_TYPES:
            raise ValueError("无效的网站类型")
        return value

    @field_validator("include_patterns", "exclude_patterns")
    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def valid_route_patterns(cls, values: list[str] | str) -> list[str]:
        """支持列表或换行分隔的字符串，自动解析并验证正则规则。"""
        # 如果是字符串，按换行分割
        if isinstance(values, str):
            values = [v.strip() for v in values.split('\n') if v.strip()]
        
        cleaned: list[str] = []
        for value in values:
            pattern = value.strip()
            if not pattern:
                continue
            if len(pattern) > 300:
                raise ValueError(f"单条路由规则不能超过 300 个字符：{pattern[:50]}...")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"无效的路由正则 '{pattern}': {exc}")
            if pattern not in cleaned:
                cleaned.append(pattern)
        return cleaned

    @field_validator("allowed_query_params")
    @classmethod
    def valid_query_params(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            name = value.strip()
            if name and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
                raise ValueError(f"无效的查询参数名：{name}")
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sitemap_url: str | None = Field(default=None, min_length=10, max_length=2048)
    status: str | None = None
    site_type: str | None = None
    include_patterns: list[str] | None = Field(default=None, max_length=50)
    exclude_patterns: list[str] | None = Field(default=None, max_length=50)
    allowed_query_params: list[str] | None = Field(default=None, max_length=30)
    crawler_max_pages: int | None = Field(default=None, ge=1, le=5000)
    request_delay_ms: int | None = Field(default=None, ge=0, le=5000)
    min_crawl_coverage: float | None = Field(default=None, ge=0.1, le=1.0)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_SITE_STATUSES:
            raise ValueError("无效的网站状态")
        return value

    @field_validator("site_type")
    @classmethod
    def valid_site_type(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_SITE_TYPES:
            raise ValueError("无效的网站类型")
        return value

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def valid_route_patterns(cls, values: list[str] | str | None) -> list[str] | None:
        if values is None:
            return None
        # 如果是字符串，按换行分割
        if isinstance(values, str):
            values = [v.strip() for v in values.split('
') if v.strip()]
        return SiteCreate.valid_route_patterns(values)

    @field_validator("allowed_query_params")
    @classmethod
    def valid_query_params(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return SiteCreate.valid_query_params(values)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str
    sitemap_url: str
    site_scheme: str
    site_type: str
    include_patterns: list[str]
    exclude_patterns: list[str]
    allowed_query_params: list[str]
    crawler_max_pages: int | None
    request_delay_ms: int
    min_crawl_coverage: float
    status: str
    last_crawled_at: datetime | None
    created_at: datetime
    page_count: int = 0
    block_count: int = 0
    outdated_block_count: int = 0


class CrawlSummary(BaseModel):
    site_id: int
    pages_discovered: int
    pages_crawled: int
    pages_skipped: int = 0
    blocks_saved: int
    errors: list[str]
    previous_pages: int = 0
    retained_pages: int = 0
    stale_pages: int = 0
    prune_blocked: bool = False
    coverage: float = 1.0


class CrawlPreview(BaseModel):
    site_id: int
    pages_discovered: int
    pages_to_crawl: int
    urls_to_crawl: list[str]
    skipped: list[dict]
    errors: list[str]


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    status: str
    pages_discovered: int
    pages_crawled: int
    pages_skipped: int
    previous_pages: int
    retained_pages: int
    stale_pages: int
    prune_blocked: bool
    errors: list[str]
    started_at: datetime
    finished_at: datetime | None


class BackgroundJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    job_type: str
    status: str
    progress: int
    result: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


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
