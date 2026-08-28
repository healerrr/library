import hashlib
import re
import asyncio
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urldefrag, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ContentBlock, CrawlRun, Page, Site
from app.services.embeddings import EmbeddingService
from app.services.ssrf import UnsafeUrlError, canonical_domain, validate_target_url
from app.services.text import CAS_RE, clean_display_text, content_hash, embedding_text, normalize_text


REMOVE_SELECTORS = [
    "nav",
    "footer",
    "header",
    "aside",
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "form",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    "[class*='footer']",
    "[class*='header']",
    "[class*='navbar']",
    "[class*='nav-']",
    "[class*='breadcrumb']",
    "[class*='cookie']",
    "[class*='sidebar']",
    "[class*='copyright']",
    "[id*='footer']",
    "[id*='header']",
    "[id*='nav']",
    "[id*='cookie']",
]
BOILERPLATE_RE = re.compile(
    r"(?:版权所有|copyright|all rights reserved|cookie policy|隐私政策|privacy policy|"
    r"网站地图|返回顶部|技术支持)",
    re.IGNORECASE,
)
PRODUCT_PATH_HINTS = {"pro", "prod", "product", "products", "goods", "item", "product-detail", "product_detail"}
PRODUCT_DATA_ROUTE_HINTS = {
    "catalog",
    "category",
    "goods",
    "inventory",
    "item",
    "pro",
    "prod",
    "product",
    "products",
    "structuresearch",
}
PRODUCT_DATA_PATTERNS = [
    re.compile(r"(?:catalog\s*(?:no\.?|number)|货号|产品编号|商品编号)\s*[:：]", re.IGNORECASE),
    re.compile(r"(?:molecular\s*formula|分子式)\s*[:：]", re.IGNORECASE),
    re.compile(r"(?:molecular\s*weight|mol\.?\s*wt\.?|分子量)\s*[:：]", re.IGNORECASE),
    re.compile(r"(?:purity|纯度)\s*[:：]", re.IGNORECASE),
]
CONTENT_PATH_HINTS = {
    "about",
    "article",
    "blog",
    "capabilities",
    "company",
    "contact",
    "custom",
    "news",
    "research",
    "service",
    "services",
    "solution",
    "solutions",
    "technology",
}
SKIP_PATH_HINTS = {
    "account",
    "cart",
    "checkout",
    "compare",
    "cdn-cgi",
    "download",
    "findpwd",
    "login",
    "logout",
    "register",
    "search",
    "sign_in",
    "sign_up",
    "signin",
    "signup",
    "points_mall",
}
SKIP_FILE_EXTENSIONS = {
    ".7z",
    ".avi",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".rar",
    ".svg",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


@dataclass
class ExtractedPage:
    title: str | None
    meta_description: str | None
    blocks: list[tuple[str, str]]


def is_dynamic_product_url(url: str) -> bool:
    path_segments = [segment.lower() for segment in unquote(urlsplit(url).path).split("/") if segment]
    if len(path_segments) < 2 or not any(segment in PRODUCT_PATH_HINTS for segment in path_segments[:-1]):
        return False
    return bool(CAS_RE.search(path_segments[-1]))


def is_product_data_url(url: str) -> bool:
    """Identify product search, catalog, category, and detail routes."""
    path_segments = [segment.lower() for segment in unquote(urlsplit(url).path).split("/") if segment]
    return bool(path_segments and path_segments[0] in PRODUCT_DATA_ROUTE_HINTS)


def is_dynamic_product_page(
    url: str,
    title: str | None,
    meta_description: str | None,
    blocks: list[tuple[str, str]] | None = None,
) -> bool:
    if is_dynamic_product_url(url):
        return True
    # Home and section pages often contain several product cards.  Treating the
    # aggregate page text as one product would discard the very pages from
    # which the crawler discovers useful editorial links.
    if urlsplit(url).path.rstrip("/") == "":
        return False
    text = " ".join(
        value
        for value in [title or "", meta_description or "", *(item[1] for item in blocks or [])]
        if value
    )
    marker_count = sum(bool(pattern.search(text)) for pattern in PRODUCT_DATA_PATTERNS)
    return bool(CAS_RE.search(text)) and marker_count >= 2


def normalize_internal_link(
    href: str,
    base_url: str,
    domains: set[str],
    allowed_query_params: set[str] | None = None,
) -> str | None:
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    candidate = urldefrag(urljoin(base_url, href)).url
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    allowed_hosts = {canonical_domain(domain) for domain in domains}
    if canonical_domain(parsed.hostname) not in allowed_hosts:
        return None
    path = unquote(parsed.path).lower()
    if any(path.endswith(extension) for extension in SKIP_FILE_EXTENSIONS):
        return None
    segments = {segment for segment in path.split("/") if segment}
    if segments & SKIP_PATH_HINTS:
        return None
    # Collapse harmless homepage variants so http/https and a missing trailing
    # slash cannot consume multiple crawl slots.
    scheme = urlsplit(base_url).scheme or parsed.scheme
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port and parsed.port not in {80, 443} else ""
    normalized_path = parsed.path or "/"
    allowed_query_params = allowed_query_params or set()
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key in allowed_query_params
        )
    )
    return urlunsplit((scheme, f"{host}{port}", normalized_path, query, ""))


def extract_internal_links(
    html: str,
    base_url: str,
    domains: set[str],
    allowed_query_params: set[str] | None = None,
) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = {
        normalized
        for element in soup.select("a[href]")
        if (
            normalized := normalize_internal_link(
                str(element.get("href", "")),
                base_url,
                domains,
                allowed_query_params,
            )
        )
    }
    return sorted(links, key=crawl_link_priority)


def crawl_link_priority(url: str) -> tuple[int, int, str]:
    segments = [segment.lower() for segment in unquote(urlsplit(url).path).split("/") if segment]
    content_priority = 0 if any(segment in CONTENT_PATH_HINTS for segment in segments) else 1
    return content_priority, len(segments), url


def route_rule_matches(rule: str, target_path: str) -> bool:
    """Match human-friendly route rules while retaining legacy regex support.

    `/about` matches only the route page (with or without its trailing slash),
    while `/about/` also matches every descendant such as `/about/team`.
    Existing rules beginning with `^`, and explicit `re:` rules, remain regex.
    """
    cleaned_rule = unquote(rule.strip())
    cleaned_target = unquote(target_path or "/")
    if cleaned_rule.startswith("re:"):
        return bool(re.search(cleaned_rule[3:], cleaned_target, re.IGNORECASE))
    if cleaned_rule.startswith("^"):
        return bool(re.search(cleaned_rule, cleaned_target, re.IGNORECASE))

    normalized_rule = f"/{cleaned_rule.lstrip('/')}"
    normalized_target = f"/{cleaned_target.lstrip('/')}"
    rule_key = normalized_rule.casefold()
    target_key = normalized_target.casefold()
    if rule_key != "/" and rule_key.endswith("/"):
        route_page = rule_key.rstrip("/")
        return target_key.rstrip("/") == route_page or target_key.startswith(rule_key)
    return target_key.rstrip("/") == rule_key.rstrip("/")


def crawl_policy_reason(url: str, site: Site, *, homepage: str | None = None) -> str | None:
    if homepage and url.rstrip("/") == homepage.rstrip("/"):
        return None
    if is_product_data_url(url):
        return "产品目录或动态数据路由"
    target = unquote(urlsplit(url).path)
    for pattern in site.exclude_patterns or []:
        if route_rule_matches(pattern, target):
            return f"命中排除路径：{pattern}"
    include_patterns = site.include_patterns or []
    if include_patterns and not any(
        route_rule_matches(pattern, target) for pattern in include_patterns
    ):
        return "不在包含路径内"
    return None


def should_block_page_pruning(
    *,
    stale_pages: int,
    coverage: float,
    minimum_coverage: float,
    errors: list[str],
) -> bool:
    """Keep old pages whenever a partial or unhealthy crawl could erase valid data."""
    return bool(stale_pages and (errors or coverage < minimum_coverage))


def extract_page(html: str) -> ExtractedPage:
    soup = BeautifulSoup(html, "lxml")
    title = clean_display_text(soup.title.get_text(" ", strip=True)) if soup.title else None
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_description = clean_display_text(str(meta_tag.get("content", ""))) if meta_tag else None

    for selector in REMOVE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    candidates: list[tuple[str, str]] = []
    if title:
        candidates.append(("title", title))
    if meta_description:
        candidates.append(("meta_description", meta_description))
    for element in soup.select("h1, h2, h3, p"):
        text = clean_display_text(element.get_text(" ", strip=True))
        content_type = "paragraph" if element.name == "p" else element.name
        minimum = 10 if content_type == "paragraph" else 2
        if len(normalize_text(text)) < minimum or BOILERPLATE_RE.search(text):
            continue
        candidates.append((content_type, text))

    seen: set[str] = set()
    blocks: list[tuple[str, str]] = []
    for content_type, text in candidates:
        normalized = normalize_text(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        blocks.append((content_type, text))
    return ExtractedPage(title=title, meta_description=meta_description, blocks=blocks)


class CrawlerService:
    def __init__(self, settings: Settings, embedding_service: EmbeddingService):
        self.settings = settings
        self.embedding_service = embedding_service
        self._skipped_dynamic_urls: set[str] = set()
        self._skipped_reasons: dict[str, str] = {}

    async def _fetch(self, client: httpx.AsyncClient, url: str, domains: set[str]) -> httpx.Response:
        current = url
        for _ in range(6):
            await validate_target_url(current, domains)
            response = await client.get(current, follow_redirects=False)
            if response.status_code not in {301, 302, 303, 307, 308}:
                response.raise_for_status()
                if len(response.content) > 5 * 1024 * 1024:
                    raise ValueError("响应内容超过 5MB 限制")
                return response
            location = response.headers.get("location")
            if not location:
                raise ValueError("重定向响应缺少 Location")
            current = urljoin(current, location)
        raise ValueError("重定向次数过多")

    def _skip(self, url: str, reason: str) -> None:
        self._skipped_dynamic_urls.add(url)
        self._skipped_reasons.setdefault(url, reason)

    async def _request_delay(self, site: Site) -> None:
        if site.request_delay_ms:
            await asyncio.sleep(site.request_delay_ms / 1000)

    async def preview(self, site: Site) -> dict:
        domains = {site.domain}
        homepage = f"https://{site.domain}/"
        maximum = site.crawler_max_pages or self.settings.crawler_max_pages
        allowed_query_params = set(site.allowed_query_params or [])
        queue: deque[str] = deque([homepage])
        queued = {homepage}
        visited: set[str] = set()
        discovered: set[str] = {homepage}
        urls_to_crawl: list[str] = []
        errors: list[str] = []
        self._skipped_dynamic_urls.clear()
        self._skipped_reasons.clear()
        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        headers = {
            "User-Agent": self.settings.crawler_user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            while queue and len(visited) < maximum:
                url = queue.popleft()
                queued.discard(url)
                if url in visited:
                    continue
                visited.add(url)
                try:
                    response = await self._fetch(client, url, domains)
                    await self._request_delay(site)
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" not in content_type and not response.text.lstrip().lower().startswith("<!doctype html"):
                        errors.append(f"{url}: 不是 HTML 页面")
                        continue
                    final_url = normalize_internal_link(
                        str(response.url),
                        url,
                        domains,
                        allowed_query_params,
                    ) or url
                    extracted = extract_page(response.text)
                    if is_dynamic_product_page(
                        final_url,
                        extracted.title,
                        extracted.meta_description,
                        extracted.blocks,
                    ):
                        self._skip(final_url, "页面内容属于产品动态数据")
                    elif final_url not in urls_to_crawl:
                        urls_to_crawl.append(final_url)
                    for link in extract_internal_links(
                        response.text,
                        final_url,
                        domains,
                        allowed_query_params,
                    ):
                        discovered.add(link)
                        reason = crawl_policy_reason(link, site, homepage=homepage)
                        if reason:
                            self._skip(link, reason)
                            continue
                        if link not in visited and link not in queued:
                            queue.append(link)
                            queued.add(link)
                except Exception as exc:
                    errors.append(f"{url}: {str(exc)[:180]}")

        return {
            "site_id": site.id,
            "pages_discovered": len(discovered),
            "pages_to_crawl": len(urls_to_crawl),
            "urls_to_crawl": urls_to_crawl[:500],
            "skipped": [
                {"url": url, "reason": reason}
                for url, reason in list(self._skipped_reasons.items())[:500]
            ],
            "errors": errors[:30],
        }

    async def crawl(self, session: AsyncSession, site: Site) -> dict:
        site_id = site.id
        minimum_coverage = float(site.min_crawl_coverage)
        domains = {site.domain}
        maximum = site.crawler_max_pages or self.settings.crawler_max_pages
        allowed_query_params = set(site.allowed_query_params or [])
        errors: list[str] = []
        pages_crawled = 0
        blocks_saved = 0
        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        headers = {"User-Agent": self.settings.crawler_user_agent, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}
        self._skipped_dynamic_urls.clear()
        self._skipped_reasons.clear()
        previous_pages = int(
            (await session.scalar(select(func.count(Page.id)).where(Page.site_id == site_id))) or 0
        )
        crawl_run = CrawlRun(site_id=site_id, previous_pages=previous_pages, status="running")
        session.add(crawl_run)
        await session.commit()
        await session.refresh(crawl_run)
        crawl_run_id = int(crawl_run.id)

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            # The homepage is the source of truth.  Following only same-domain
            # anchors avoids footer friend links, while a bounded BFS reaches
            # the site's real navigation without depending on sitemap.xml.
            homepage = f"https://{site.domain}/"
            queue: deque[str] = deque([homepage])
            queued = {homepage}
            visited: set[str] = set()
            discovered: set[str] = {homepage}
            retained_urls: set[str] = set()
            stored_rows = (
                await session.execute(
                    select(ContentBlock.page_id, ContentBlock.content_hash).where(ContentBlock.site_id == site_id)
                )
            ).all()
            stored_hash_counts = Counter(content_digest for _, content_digest in stored_rows)
            stored_hashes_by_page: dict[int, list[str]] = defaultdict(list)
            for page_id, content_digest in stored_rows:
                stored_hashes_by_page[page_id].append(content_digest)
            hashes_saved_this_crawl: set[str] = set()
            while queue and len(visited) < maximum:
                url = queue.popleft()
                queued.discard(url)
                if url in visited:
                    continue
                visited.add(url)
                try:
                    response = await self._fetch(client, url, domains)
                    await self._request_delay(site)
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" not in content_type and not response.text.lstrip().lower().startswith("<!doctype html"):
                        errors.append(f"{url}: 不是 HTML 页面")
                        continue
                    final_url = normalize_internal_link(
                        str(response.url),
                        url,
                        domains,
                        allowed_query_params,
                    ) or url
                    extracted_links = extract_internal_links(
                        response.text,
                        final_url,
                        domains,
                        allowed_query_params,
                    )
                    for link in extracted_links:
                        discovered.add(link)
                        reason = crawl_policy_reason(link, site, homepage=homepage)
                        if reason:
                            self._skip(link, reason)
                            continue
                        if link not in visited and link not in queued:
                            queue.append(link)
                            queued.add(link)
                    url = final_url
                    if url in retained_urls:
                        continue
                    page = await session.scalar(select(Page).where(Page.site_id == site_id, Page.url == url))
                    now = datetime.now(timezone.utc)
                    page_digest = hashlib.sha256(response.content).hexdigest()
                    extracted = extract_page(response.text)
                    if is_dynamic_product_page(url, extracted.title, extracted.meta_description, extracted.blocks):
                        self._skip(url, "页面内容属于产品动态数据")
                        continue
                    if page is not None and page.content_hash == page_digest:
                        page.http_status = response.status_code
                        page.crawled_at = now
                        await session.commit()
                        retained_urls.add(url)
                        pages_crawled += 1
                        continue
                    if page is None:
                        page = Page(site_id=site_id, url=url)
                        session.add(page)
                    page.title = extracted.title
                    page.meta_description = extracted.meta_description
                    page.http_status = response.status_code
                    page.content_hash = page_digest
                    page.crawled_at = now
                    await session.flush()

                    for old_digest in stored_hashes_by_page.pop(page.id, []):
                        stored_hash_counts[old_digest] -= 1
                        if stored_hash_counts[old_digest] <= 0:
                            del stored_hash_counts[old_digest]
                    await session.execute(delete(ContentBlock).where(ContentBlock.page_id == page.id))

                    unique_blocks: list[tuple[str, str, str]] = []
                    for block_type, text in extracted.blocks:
                        block_digest = content_hash(text)
                        if block_digest in stored_hash_counts or block_digest in hashes_saved_this_crawl:
                            continue
                        hashes_saved_this_crawl.add(block_digest)
                        unique_blocks.append((block_type, text, block_digest))

                    embed_inputs = [embedding_text(text) for _, text, _ in unique_blocks]
                    vectors = await self.embedding_service.embed(embed_inputs)
                    for (block_type, text, block_digest), vector in zip(unique_blocks, vectors, strict=True):
                        session.add(
                            ContentBlock(
                                site_id=site_id,
                                page_id=page.id,
                                page_title=extracted.title,
                                url=url,
                                content_type=block_type,
                                original_content=text,
                                normalized_content=normalize_text(text),
                                content_hash=block_digest,
                                embedding=vector,
                                embedding_version=self.embedding_service.signature,
                                collected_at=now,
                            )
                        )
                    await session.commit()
                    retained_urls.add(url)
                    pages_crawled += 1
                    blocks_saved += len(unique_blocks)
                except Exception as exc:  # Keep one bad page from aborting the site crawl.
                    error_message = str(exc)[:180]
                    await session.rollback()
                    # rollback() expires ORM attributes even when
                    # expire_on_commit=False. Explicit refresh prevents a
                    # later policy read from triggering forbidden implicit IO.
                    await session.refresh(site)
                    errors.append(f"{url}: {error_message}")

        stored_pages = list((await session.scalars(select(Page).where(Page.site_id == site_id))).all())
        policy_excluded_pages = [
            page
            for page in stored_pages
            if crawl_policy_reason(page.url, site, homepage=homepage)
        ]
        policy_eligible_pages = [
            page
            for page in stored_pages
            if not crawl_policy_reason(page.url, site, homepage=homepage)
        ]
        eligible_stale_pages = [
            page for page in policy_eligible_pages if page.url not in retained_urls
        ]
        stale_pages = len(policy_excluded_pages) + len(eligible_stale_pages)
        retained_existing = sum(page.url in retained_urls for page in policy_eligible_pages)
        coverage = (
            retained_existing / len(policy_eligible_pages)
            if policy_eligible_pages
            else 1.0
        )
        prune_blocked = should_block_page_pruning(
            stale_pages=len(eligible_stale_pages),
            coverage=coverage,
            minimum_coverage=minimum_coverage,
            errors=errors,
        )
        # Explicit route exclusions are intentional and must take effect even
        # when the safety guard preserves unexpectedly missing eligible pages.
        await remove_pages_by_ids(session, [page.id for page in policy_excluded_pages])
        if not prune_blocked:
            await remove_pages_by_ids(session, [page.id for page in eligible_stale_pages])
        await deduplicate_site_blocks(session, site_id)
        managed_site = await session.get(Site, site_id)
        if managed_site is not None:
            managed_site.last_crawled_at = datetime.now(timezone.utc)
            managed_site.status = "active" if pages_crawled or self._skipped_dynamic_urls else "error"
        crawl_run = await session.get(CrawlRun, crawl_run_id)
        if crawl_run is not None:
            crawl_run.status = "completed_with_warnings" if errors or prune_blocked else "completed"
            crawl_run.pages_discovered = len(discovered)
            crawl_run.pages_crawled = pages_crawled
            crawl_run.pages_skipped = len(self._skipped_dynamic_urls)
            crawl_run.retained_pages = len(retained_urls)
            crawl_run.stale_pages = stale_pages
            crawl_run.prune_blocked = prune_blocked
            crawl_run.errors = errors[:30]
            crawl_run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return {
            "site_id": site_id,
            "pages_discovered": len(discovered),
            "pages_crawled": pages_crawled,
            "pages_skipped": len(self._skipped_dynamic_urls),
            "blocks_saved": blocks_saved,
            "errors": errors[:30],
            "previous_pages": previous_pages,
            "retained_pages": len(retained_urls),
            "stale_pages": stale_pages,
            "prune_blocked": prune_blocked,
            "coverage": round(coverage, 4),
        }


async def deduplicate_site_blocks(session: AsyncSession, site_id: int) -> int:
    """Remove legacy duplicate fragments while keeping the oldest source record."""
    blocks = list(
        (
            await session.scalars(
                select(ContentBlock)
                .where(ContentBlock.site_id == site_id)
                .order_by(ContentBlock.id.asc())
            )
        ).all()
    )
    seen_hashes: set[str] = set()
    duplicate_ids: list[int] = []
    for block in blocks:
        if block.content_hash in seen_hashes:
            duplicate_ids.append(block.id)
        else:
            seen_hashes.add(block.content_hash)
    if duplicate_ids:
        await session.execute(delete(ContentBlock).where(ContentBlock.id.in_(duplicate_ids)))
    return len(duplicate_ids)


async def remove_dynamic_product_pages(session: AsyncSession, site_id: int) -> int:
    """Remove previously stored structured product pages from the copy corpus."""
    pages = list((await session.scalars(select(Page).where(Page.site_id == site_id))).all())
    product_page_ids = [
        page.id
        for page in pages
        if is_product_data_url(page.url)
        or is_dynamic_product_page(page.url, page.title, page.meta_description)
    ]
    if not product_page_ids:
        return 0
    await session.execute(delete(ContentBlock).where(ContentBlock.page_id.in_(product_page_ids)))
    await session.execute(delete(Page).where(Page.id.in_(product_page_ids)))
    return len(product_page_ids)


async def remove_pages_not_retained(session: AsyncSession, site_id: int, retained_urls: set[str]) -> int:
    """Drop stale pages left by older sitemap-based crawls."""
    pages = list((await session.scalars(select(Page).where(Page.site_id == site_id))).all())
    stale_page_ids = [page.id for page in pages if page.url not in retained_urls]
    return await remove_pages_by_ids(session, stale_page_ids)


async def remove_pages_by_ids(session: AsyncSession, page_ids: list[int]) -> int:
    """Delete selected pages and their copy blocks without lazy-loading relationships."""
    if not page_ids:
        return 0
    await session.execute(delete(ContentBlock).where(ContentBlock.page_id.in_(page_ids)))
    await session.execute(delete(Page).where(Page.id.in_(page_ids)))
    return len(page_ids)
