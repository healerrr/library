import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urldefrag

import httpx
from bs4 import BeautifulSoup
from lxml import etree
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ContentBlock, Page, Site
from app.services.embeddings import EmbeddingService
from app.services.ssrf import UnsafeUrlError, validate_target_url
from app.services.text import clean_display_text, content_hash, embedding_text, normalize_text


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


@dataclass
class ExtractedPage:
    title: str | None
    meta_description: str | None
    blocks: list[tuple[str, str]]


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

    async def _sitemap_urls(
        self,
        client: httpx.AsyncClient,
        sitemap_url: str,
        domains: set[str],
        visited: set[str] | None = None,
    ) -> list[str]:
        visited = visited or set()
        if sitemap_url in visited or len(visited) >= 20:
            return []
        visited.add(sitemap_url)
        response = await self._fetch(client, sitemap_url, domains)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        root = etree.fromstring(response.content, parser=parser)
        root_name = etree.QName(root.tag).localname.lower()
        locations = [
            clean_display_text(str(node.text or ""))
            for node in root.xpath("//*[local-name()='loc']")
            if node.text
        ]
        if root_name == "sitemapindex":
            urls: list[str] = []
            for child_sitemap in locations:
                if len(urls) >= self.settings.crawler_max_pages:
                    break
                try:
                    urls.extend(await self._sitemap_urls(client, child_sitemap, domains, visited))
                except (httpx.HTTPError, etree.XMLSyntaxError, UnsafeUrlError, ValueError):
                    continue
            return urls[: self.settings.crawler_max_pages]
        if root_name != "urlset":
            raise ValueError("Sitemap 根节点必须是 urlset 或 sitemapindex")

        safe_urls: list[str] = []
        for location in locations:
            location = urldefrag(location).url
            try:
                await validate_target_url(location, domains)
            except UnsafeUrlError:
                continue
            if location not in safe_urls:
                safe_urls.append(location)
            if len(safe_urls) >= self.settings.crawler_max_pages:
                break
        return safe_urls

    async def crawl(self, session: AsyncSession, site: Site) -> dict:
        site_id = site.id
        sitemap_url = site.sitemap_url
        domains = {site.domain}
        errors: list[str] = []
        pages_crawled = 0
        blocks_saved = 0
        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        headers = {"User-Agent": self.settings.crawler_user_agent, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            page_urls = await self._sitemap_urls(client, sitemap_url, domains)
            for url in page_urls:
                try:
                    response = await self._fetch(client, url, domains)
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" not in content_type and not response.text.lstrip().lower().startswith("<!doctype html"):
                        errors.append(f"{url}: 不是 HTML 页面")
                        continue
                    extracted = extract_page(response.text)
                    page = await session.scalar(select(Page).where(Page.site_id == site_id, Page.url == url))
                    now = datetime.now(timezone.utc)
                    page_digest = hashlib.sha256(response.content).hexdigest()
                    if page is None:
                        page = Page(site_id=site_id, url=url)
                        session.add(page)
                    page.title = extracted.title
                    page.meta_description = extracted.meta_description
                    page.http_status = response.status_code
                    page.content_hash = page_digest
                    page.crawled_at = now
                    await session.flush()
                    await session.execute(delete(ContentBlock).where(ContentBlock.page_id == page.id))

                    embed_inputs = [embedding_text(text) for _, text in extracted.blocks]
                    vectors = await self.embedding_service.embed(embed_inputs)
                    for (block_type, text), vector in zip(extracted.blocks, vectors, strict=True):
                        session.add(
                            ContentBlock(
                                site_id=site_id,
                                page_id=page.id,
                                page_title=extracted.title,
                                url=url,
                                content_type=block_type,
                                original_content=text,
                                normalized_content=normalize_text(text),
                                content_hash=content_hash(text),
                                embedding=vector,
                                collected_at=now,
                            )
                        )
                    await session.commit()
                    pages_crawled += 1
                    blocks_saved += len(extracted.blocks)
                except Exception as exc:  # Keep one bad page from aborting the site crawl.
                    await session.rollback()
                    errors.append(f"{url}: {str(exc)[:180]}")

        managed_site = await session.get(Site, site_id)
        if managed_site is not None:
            managed_site.last_crawled_at = datetime.now(timezone.utc)
            managed_site.status = "active" if pages_crawled else "error"
        await session.commit()
        return {
            "site_id": site_id,
            "pages_discovered": len(page_urls),
            "pages_crawled": pages_crawled,
            "blocks_saved": blocks_saved,
            "errors": errors[:30],
        }
