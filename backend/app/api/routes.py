import math
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.models import ContentBlock, Page, SimilarityCheck, Site
from app.schemas import (
    ContentBlockOut,
    ContentBlockPage,
    CrawlSummary,
    SimilarityCheckRequest,
    SimilarityCheckResponse,
    SiteCreate,
    SiteOut,
    SiteUpdate,
    StatsOut,
)
from app.services.crawler import CrawlerService
from app.services.embeddings import get_embedding_service
from app.services.similarity import SimilarityService
from app.services.ssrf import UnsafeUrlError, validate_url_format


router = APIRouter(prefix="/api")


def is_unique_violation(exc: IntegrityError) -> bool:
    original = exc.orig
    return getattr(original, "sqlstate", None) == "23505" or "unique constraint" in str(original).lower()


def site_dict(site: Site, page_count: int = 0, block_count: int = 0) -> dict:
    return {
        "id": site.id,
        "name": site.name,
        "domain": site.domain,
        "sitemap_url": site.sitemap_url,
        "status": site.status,
        "last_crawled_at": site.last_crawled_at,
        "created_at": site.created_at,
        "page_count": page_count,
        "block_count": block_count,
    }


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    await session.execute(select(1))
    return {"status": "ok", "embedding_provider": settings.embedding_provider}


@router.get("/stats", response_model=StatsOut)
async def stats(session: AsyncSession = Depends(get_session)):
    values = []
    for model in (Site, Page, ContentBlock, SimilarityCheck):
        values.append(int((await session.scalar(select(func.count()).select_from(model))) or 0))
    return StatsOut(sites=values[0], pages=values[1], content_blocks=values[2], similarity_checks=values[3])


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(session: AsyncSession = Depends(get_session)):
    page_count = select(func.count(Page.id)).where(Page.site_id == Site.id).correlate(Site).scalar_subquery()
    block_count = (
        select(func.count(ContentBlock.id)).where(ContentBlock.site_id == Site.id).correlate(Site).scalar_subquery()
    )
    rows = (await session.execute(select(Site, page_count, block_count).order_by(Site.created_at.desc()))).all()
    return [site_dict(site, int(pages), int(blocks)) for site, pages, blocks in rows]


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(payload: SiteCreate, session: AsyncSession = Depends(get_session)):
    try:
        validate_url_format(payload.sitemap_url, {payload.domain})
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    site = Site(**payload.model_dump())
    session.add(site)
    try:
        await session.commit()
        await session.refresh(site)
    except IntegrityError as exc:
        await session.rollback()
        if is_unique_violation(exc):
            raise HTTPException(status_code=409, detail="该域名已经添加") from exc
        raise
    return site_dict(site)


@router.patch("/sites/{site_id}", response_model=SiteOut)
async def update_site(site_id: int, payload: SiteUpdate, session: AsyncSession = Depends(get_session)):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("sitemap_url"):
        try:
            validate_url_format(changes["sitemap_url"], {site.domain})
        except UnsafeUrlError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in changes.items():
        setattr(site, key, value)
    await session.commit()
    await session.refresh(site)
    pages = int((await session.scalar(select(func.count(Page.id)).where(Page.site_id == site.id))) or 0)
    blocks = int((await session.scalar(select(func.count(ContentBlock.id)).where(ContentBlock.site_id == site.id))) or 0)
    return site_dict(site, pages, blocks)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: int, session: AsyncSession = Depends(get_session)):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    await session.delete(site)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sites/{site_id}/crawl", response_model=CrawlSummary)
async def crawl_site(
    site_id: int,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    if site.status == "paused":
        raise HTTPException(status_code=409, detail="网站已暂停，请先启用")
    service = CrawlerService(settings, get_embedding_service())
    try:
        return await service.crawl(session, site)
    except (UnsafeUrlError, httpx.HTTPError, ValueError) as exc:
        await session.rollback()
        managed_site = await session.get(Site, site_id)
        if managed_site is not None:
            managed_site.status = "error"
            await session.commit()
        raise HTTPException(status_code=400, detail=f"采集失败：{str(exc)[:300]}") from exc


@router.get("/content-blocks", response_model=ContentBlockPage)
async def list_content_blocks(
    site_id: int | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    filters = []
    if site_id is not None:
        filters.append(ContentBlock.site_id == site_id)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(ContentBlock.original_content.ilike(pattern), ContentBlock.page_title.ilike(pattern)))

    total_statement = select(func.count()).select_from(ContentBlock).where(*filters)
    total = int((await session.scalar(total_statement)) or 0)
    statement = (
        select(ContentBlock, Site.name)
        .join(Site, Site.id == ContentBlock.site_id)
        .where(*filters)
        .order_by(ContentBlock.collected_at.desc(), ContentBlock.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(statement)).all()
    items = [
        ContentBlockOut(
            id=block.id,
            site_id=block.site_id,
            site_name=site_name,
            page_id=block.page_id,
            page_title=block.page_title,
            url=block.url,
            content_type=block.content_type,
            original_content=block.original_content,
            collected_at=block.collected_at,
        )
        for block, site_name in rows
    ]
    return ContentBlockPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/content-blocks/{block_id}", response_model=ContentBlockOut)
async def get_content_block(block_id: int, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(ContentBlock, Site.name)
            .join(Site, Site.id == ContentBlock.site_id)
            .where(ContentBlock.id == block_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="文案不存在")
    block, site_name = row
    return ContentBlockOut(
        id=block.id,
        site_id=block.site_id,
        site_name=site_name,
        page_id=block.page_id,
        page_title=block.page_title,
        url=block.url,
        content_type=block.content_type,
        original_content=block.original_content,
        collected_at=block.collected_at,
    )


@router.post("/similarity/check", response_model=SimilarityCheckResponse)
async def check_similarity(
    payload: SimilarityCheckRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    service = SimilarityService(settings, get_embedding_service())
    return await service.check(session, payload.content, payload.limit)
