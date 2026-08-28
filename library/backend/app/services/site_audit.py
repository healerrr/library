from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ContentBlock, Site
from app.services.embeddings import EmbeddingService
from app.services.similarity import SimilarityService, build_sqlite_reference_index


ProgressCallback = Callable[[int], Awaitable[None]]


class SiteAuditService:
    def __init__(self, settings: Settings, embedding_service: EmbeddingService):
        self.similarity = SimilarityService(settings, embedding_service)

    async def audit(
        self,
        session: AsyncSession,
        site: Site,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        blocks = list(
            (
                await session.scalars(
                    select(ContentBlock)
                    .where(ContentBlock.site_id == site.id)
                    .order_by(ContentBlock.id.asc())
                )
            ).all()
        )
        findings: list[dict] = []
        high = medium = low = 0
        total = len(blocks)
        sqlite_reference_index = None
        if session.get_bind().dialect.name == "sqlite":
            scope_rows = list(
                (
                    await session.execute(
                        select(ContentBlock, Site.name)
                        .join(Site, Site.id == ContentBlock.site_id)
                        .where(
                            Site.site_type == "baseline",
                            ContentBlock.site_id != site.id,
                        )
                    )
                ).all()
            )
            sqlite_reference_index = build_sqlite_reference_index(
                scope_rows,
                self.similarity.embedding_service.signature,
            )

        for index, block in enumerate(blocks, start=1):
            comparison = await self.similarity.check(
                session,
                block.original_content,
                limit=3,
                exclude_site_id=site.id,
                persist=False,
                sqlite_reference_index=sqlite_reference_index,
            )
            matches = comparison["results"]
            if matches:
                top = matches[0]
                risk = top["risk_level"]
                if risk == "high":
                    high += 1
                elif risk == "medium":
                    medium += 1
                else:
                    low += 1
                findings.append(
                    {
                        "candidate_block_id": block.id,
                        "candidate_content": block.original_content,
                        "candidate_content_type": block.content_type,
                        "candidate_page_title": block.page_title,
                        "candidate_url": block.url,
                        "top_score": top["overall_similarity"],
                        "risk_level": risk,
                        "matches": matches,
                    }
                )
            if progress_callback and (index == total or index % 5 == 0):
                await progress_callback(round(index / total * 100) if total else 100)

        findings.sort(key=lambda item: item["top_score"], reverse=True)
        return {
            "site_id": site.id,
            "site_name": site.name,
            "total_blocks": total,
            "matched_blocks": len(findings),
            "high_risk_blocks": high,
            "medium_risk_blocks": medium,
            "low_risk_blocks": low,
            "max_similarity": findings[0]["top_score"] if findings else 0.0,
            "findings": findings[:100],
        }
