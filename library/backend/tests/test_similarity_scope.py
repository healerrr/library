import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.models import ContentBlock, Page, Site
from app.services.embeddings import EmbeddingService
from app.services.similarity import SimilarityService
from app.services.reindex import ReindexService
from app.services.text import content_hash, normalize_text


@pytest.mark.asyncio
async def test_similarity_uses_baseline_sites_and_excludes_candidate_self_matches() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    settings = Settings(embedding_provider="hashing")
    embeddings = EmbeddingService(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        baseline = Site(name="历史站", domain="baseline.example", sitemap_url="", site_type="baseline")
        candidate = Site(name="待上线站", domain="candidate.example", sitemap_url="", site_type="candidate")
        session.add_all([baseline, candidate])
        await session.flush()
        baseline_page = Page(site_id=baseline.id, url="https://baseline.example/")
        candidate_page = Page(site_id=candidate.id, url="https://candidate.example/")
        session.add_all([baseline_page, candidate_page])
        await session.flush()

        async def add_block(site: Site, page: Page, text: str) -> ContentBlock:
            vector = (await embeddings.embed([text]))[0]
            block = ContentBlock(
                site_id=site.id,
                page_id=page.id,
                page_title=text,
                url=page.url,
                content_type="title",
                original_content=text,
                normalized_content=normalize_text(text),
                content_hash=content_hash(text),
                embedding=vector,
                embedding_version=embeddings.signature,
            )
            session.add(block)
            return block

        baseline_text = "Completely unrelated baseline sentence about ocean weather"
        baseline_block = await add_block(baseline, baseline_page, baseline_text)
        await add_block(candidate, candidate_page, "待上线网站独有宣传文案")
        await session.commit()

        service = SimilarityService(settings, embeddings)
        self_only = await service.check(
            session,
            "待上线网站独有宣传文案",
            exclude_site_id=candidate.id,
            persist=False,
        )
        assert self_only["results"] == []

        baseline_match = await service.check(session, baseline_text, persist=False)
        assert baseline_match["results"][0]["site_id"] == baseline.id

        baseline_block.embedding_version = "legacy-model"
        await session.commit()
        exact_with_old_vector = await service.check(session, baseline_text, persist=False)
        assert exact_with_old_vector["results"][0]["exact_match"] is True

        result = await ReindexService(embeddings).reindex_site(session, baseline)
        assert result["blocks_reindexed"] == 1
        assert baseline_block.embedding_version == embeddings.signature

    await engine.dispose()
