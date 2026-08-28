import math
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import SessionLocal, get_session
from app.models import BackgroundJob, ContentBlock, CrawlRun, EmailTemplate, Page, SimilarityCheck, Site
from app.schemas import (
    BackgroundJobOut,
    ContentBlockOut,
    ContentBlockPage,
    CrawlSummary,
    CrawlRunOut,
    EmailTemplateCreate,
    EmailTemplateOut,
    EmailTemplateUpdate,
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
from app.services.site_audit import SiteAuditService
from app.services.reindex import ReindexService
from app.services.ssrf import UnsafeUrlError, validate_url_format


router = APIRouter(prefix="/api")


def is_unique_violation(exc: IntegrityError) -> bool:
    original = exc.orig
    return getattr(original, "sqlstate", None) == "23505" or "unique constraint" in str(original).lower()


def site_dict(
    site: Site,
    page_count: int = 0,
    block_count: int = 0,
    outdated_block_count: int = 0,
    email_template_count: int = 0,
) -> dict:
    return {
        "id": site.id,
        "name": site.name,
        "domain": site.domain,
        "sitemap_url": site.sitemap_url,
        "site_scheme": site.site_scheme,
        "site_type": site.site_type,
        "product_routes": site.product_routes or [],
        "include_patterns": site.include_patterns or [],
        "exclude_patterns": site.exclude_patterns or [],
        "allowed_query_params": site.allowed_query_params or [],
        "crawler_max_pages": site.crawler_max_pages,
        "request_delay_ms": site.request_delay_ms,
        "min_crawl_coverage": site.min_crawl_coverage,
        "status": site.status,
        "last_crawled_at": site.last_crawled_at,
        "created_at": site.created_at,
        "page_count": page_count,
        "block_count": block_count,
        "outdated_block_count": outdated_block_count,
        "email_template_count": email_template_count,
    }


async def mark_job_failed(job_id: int, message: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(BackgroundJob, job_id)
        if job is not None:
            job.status = "error"
            job.error = message[:1000]
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()


async def mark_crawl_run_failed(site_id: int, message: str) -> None:
    async with SessionLocal() as session:
        crawl_run = await session.scalar(
            select(CrawlRun)
            .where(CrawlRun.site_id == site_id, CrawlRun.status == "running")
            .order_by(CrawlRun.id.desc())
            .limit(1)
        )
        if crawl_run is not None:
            crawl_run.status = "error"
            crawl_run.errors = [message[:300]]
            crawl_run.finished_at = datetime.now(timezone.utc)
            await session.commit()


async def run_crawl_job(job_id: int, site_id: int, settings: Settings) -> None:
    try:
        async with SessionLocal() as session:
            job = await session.get(BackgroundJob, job_id)
            site = await session.get(Site, site_id)
            if job is None or site is None:
                raise ValueError("任务或网站不存在")
            job.status = "running"
            job.progress = 5
            job.started_at = datetime.now(timezone.utc)
            await session.commit()
            result = await CrawlerService(settings, get_embedding_service()).crawl(session, site)
            job = await session.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "completed"
                job.progress = 100
                job.result = result
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as exc:
        await mark_job_failed(job_id, str(exc))
        await mark_crawl_run_failed(site_id, str(exc))


async def run_preview_job(job_id: int, site_id: int, settings: Settings) -> None:
    try:
        async with SessionLocal() as session:
            job = await session.get(BackgroundJob, job_id)
            site = await session.get(Site, site_id)
            if job is None or site is None:
                raise ValueError("任务或网站不存在")
            job.status = "running"
            job.progress = 5
            job.started_at = datetime.now(timezone.utc)
            await session.commit()
            result = await CrawlerService(settings, get_embedding_service()).preview(site)
            job = await session.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "completed"
                job.progress = 100
                job.result = result
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as exc:
        await mark_job_failed(job_id, str(exc))


async def run_audit_job(job_id: int, site_id: int, settings: Settings) -> None:
    try:
        async with SessionLocal() as session:
            job = await session.get(BackgroundJob, job_id)
            site = await session.get(Site, site_id)
            if job is None or site is None:
                raise ValueError("任务或网站不存在")
            job.status = "running"
            job.progress = 1
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            async def update_progress(value: int) -> None:
                managed_job = await session.get(BackgroundJob, job_id)
                if managed_job is not None:
                    managed_job.progress = value
                    await session.commit()

            result = await SiteAuditService(settings, get_embedding_service()).audit(
                session,
                site,
                update_progress,
            )
            job = await session.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "completed"
                job.progress = 100
                job.result = result
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as exc:
        await mark_job_failed(job_id, str(exc))


async def run_reindex_job(job_id: int, site_id: int) -> None:
    try:
        async with SessionLocal() as session:
            job = await session.get(BackgroundJob, job_id)
            site = await session.get(Site, site_id)
            if job is None or site is None:
                raise ValueError("任务或网站不存在")
            job.status = "running"
            job.progress = 1
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            async def update_progress(value: int) -> None:
                managed_job = await session.get(BackgroundJob, job_id)
                if managed_job is not None:
                    managed_job.progress = value
                    await session.commit()

            result = await ReindexService(get_embedding_service()).reindex_site(
                session,
                site,
                update_progress,
            )
            job = await session.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "completed"
                job.progress = 100
                job.result = result
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as exc:
        await mark_job_failed(job_id, str(exc))


async def create_background_job(
    session: AsyncSession,
    site_id: int,
    job_type: str,
) -> tuple[BackgroundJob, bool]:
    active = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.site_id == site_id,
            BackgroundJob.job_type == job_type,
            BackgroundJob.status.in_({"queued", "running"}),
        )
        .order_by(BackgroundJob.id.desc())
    )
    if active is not None:
        return active, False
    job = BackgroundJob(site_id=site_id, job_type=job_type, status="queued", progress=0)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job, True


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    await session.execute(select(1))
    return {
        "status": "ok",
        "embedding_provider": settings.embedding_provider,
        "embedding_version": get_embedding_service().signature,
        "vector_database": session.get_bind().dialect.name,
    }


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
    outdated_count = (
        select(func.count(ContentBlock.id))
        .where(
            ContentBlock.site_id == Site.id,
            ContentBlock.embedding_version != get_embedding_service().signature,
        )
        .correlate(Site)
        .scalar_subquery()
    )
    template_count = (
        select(func.count(EmailTemplate.id))
        .where(EmailTemplate.site_id == Site.id)
        .correlate(Site)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(Site, page_count, block_count, outdated_count, template_count)
            .order_by(Site.created_at.desc())
        )
    ).all()
    return [
        site_dict(site, int(pages), int(blocks), int(outdated), int(templates))
        for site, pages, blocks, outdated, templates in rows
    ]


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(payload: SiteCreate, session: AsyncSession = Depends(get_session)):
    if payload.sitemap_url:
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
    templates = int(
        (await session.scalar(select(func.count(EmailTemplate.id)).where(EmailTemplate.site_id == site.id))) or 0
    )
    return site_dict(site, pages, blocks, email_template_count=templates)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: int, session: AsyncSession = Depends(get_session)):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    await session.delete(site)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_email_template_or_404(
    session: AsyncSession,
    site_id: int,
    template_id: int,
) -> EmailTemplate:
    template = await session.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id,
            EmailTemplate.site_id == site_id,
        )
    )
    if template is None:
        raise HTTPException(status_code=404, detail="邮件模板不存在")
    return template


@router.get("/sites/{site_id}/email-templates", response_model=list[EmailTemplateOut])
async def list_email_templates(
    site_id: int,
    search: str | None = Query(default=None, max_length=100),
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Site, site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    statement = select(EmailTemplate).where(EmailTemplate.site_id == site_id)
    if search and (term := search.strip()):
        pattern = f"%{term}%"
        statement = statement.where(
            or_(EmailTemplate.title.ilike(pattern), EmailTemplate.content_html.ilike(pattern))
        )
    return (
        await session.scalars(
            statement.order_by(EmailTemplate.updated_at.desc(), EmailTemplate.id.desc())
        )
    ).all()


@router.get(
    "/sites/{site_id}/email-templates/{template_id}",
    response_model=EmailTemplateOut,
)
async def get_email_template(
    site_id: int,
    template_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await get_email_template_or_404(session, site_id, template_id)


@router.post(
    "/sites/{site_id}/email-templates",
    response_model=EmailTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_email_template(
    site_id: int,
    payload: EmailTemplateCreate,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Site, site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    template = EmailTemplate(site_id=site_id, **payload.model_dump())
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


@router.patch(
    "/sites/{site_id}/email-templates/{template_id}",
    response_model=EmailTemplateOut,
)
async def update_email_template(
    site_id: int,
    template_id: int,
    payload: EmailTemplateUpdate,
    session: AsyncSession = Depends(get_session),
):
    template = await get_email_template_or_404(session, site_id, template_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    template.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(template)
    return template


@router.delete(
    "/sites/{site_id}/email-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_email_template(
    site_id: int,
    template_id: int,
    session: AsyncSession = Depends(get_session),
):
    template = await get_email_template_or_404(session, site_id, template_id)
    await session.delete(template)
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


@router.post(
    "/sites/{site_id}/crawl-jobs",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_crawl_job(
    site_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    if site.status == "paused":
        raise HTTPException(status_code=409, detail="网站已暂停，请先启用")
    job, created = await create_background_job(session, site_id, "crawl")
    if created:
        background_tasks.add_task(run_crawl_job, job.id, site_id, settings)
    return job


@router.post(
    "/sites/{site_id}/preview-jobs",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_preview_job(
    site_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    job, created = await create_background_job(session, site_id, "preview")
    if created:
        background_tasks.add_task(run_preview_job, job.id, site_id, settings)
    return job


@router.post(
    "/sites/{site_id}/audit-jobs",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audit_job(
    site_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    if site.site_type != "candidate":
        raise HTTPException(status_code=409, detail="只有待上线站点可以执行整站检测")
    block_count = int(
        (await session.scalar(select(func.count(ContentBlock.id)).where(ContentBlock.site_id == site_id))) or 0
    )
    if not block_count:
        raise HTTPException(status_code=409, detail="该站点还没有文案，请先执行采集")
    job, created = await create_background_job(session, site_id, "audit")
    if created:
        background_tasks.add_task(run_audit_job, job.id, site_id, settings)
    return job


@router.get("/jobs/{job_id}", response_model=BackgroundJobOut)
async def get_background_job(job_id: int, session: AsyncSession = Depends(get_session)):
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/sites/{site_id}/crawl-runs", response_model=list[CrawlRunOut])
async def list_crawl_runs(
    site_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Site, site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    return list(
        (
            await session.scalars(
                select(CrawlRun)
                .where(CrawlRun.site_id == site_id)
                .order_by(CrawlRun.id.desc())
                .limit(limit)
            )
        ).all()
    )


@router.post(
    "/sites/{site_id}/reindex-jobs",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_reindex_job(
    site_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    block_count = int(
        (await session.scalar(select(func.count(ContentBlock.id)).where(ContentBlock.site_id == site_id))) or 0
    )
    if not block_count:
        raise HTTPException(status_code=409, detail="该站点还没有文案")
    job, created = await create_background_job(session, site_id, "reindex")
    if created:
        background_tasks.add_task(run_reindex_job, job.id, site_id)
    return job


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
