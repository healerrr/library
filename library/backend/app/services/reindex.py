from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentBlock, Site
from app.services.embeddings import EmbeddingService
from app.services.text import embedding_text


ProgressCallback = Callable[[int], Awaitable[None]]


class ReindexService:
    def __init__(self, embedding_service: EmbeddingService, batch_size: int = 64):
        self.embedding_service = embedding_service
        self.batch_size = batch_size

    async def reindex_site(
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
        total = len(blocks)
        for start in range(0, total, self.batch_size):
            batch = blocks[start : start + self.batch_size]
            vectors = await self.embedding_service.embed(
                [embedding_text(block.original_content) for block in batch]
            )
            for block, vector in zip(batch, vectors, strict=True):
                block.embedding = vector
                block.embedding_version = self.embedding_service.signature
            await session.commit()
            if progress_callback:
                await progress_callback(round(min(start + len(batch), total) / total * 100))
        return {
            "site_id": site.id,
            "site_name": site.name,
            "blocks_reindexed": total,
            "embedding_version": self.embedding_service.signature,
        }
