import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ContentBlock, SimilarityCheck, Site
from app.services.embeddings import EmbeddingService
from app.services.text import (
    content_hash,
    embedding_text,
    highlight_segments,
    lexical_similarity,
    normalize_text,
    strip_chemical_fields,
)


def risk_level(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.75:
        return "medium"
    return "low"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute cosine similarity for the SQLite fallback path."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot_product = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)


@dataclass
class SQLiteReferenceIndex:
    scope_rows: list[tuple[ContentBlock, str]]
    vector_rows: list[tuple[ContentBlock, str]]
    matrix: np.ndarray
    exact_rows: dict[str, list[tuple[ContentBlock, str]]]


def build_sqlite_reference_index(
    rows: list[tuple[ContentBlock, str]],
    embedding_version: str,
) -> SQLiteReferenceIndex:
    vector_rows = [row for row in rows if row[0].embedding_version == embedding_version]
    if vector_rows:
        matrix = np.asarray([row[0].embedding for row in vector_rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.where(norms == 0, 1.0, norms)
    else:
        matrix = np.empty((0, 0), dtype=np.float32)
    exact_rows: dict[str, list[tuple[ContentBlock, str]]] = defaultdict(list)
    for row in rows:
        exact_rows[row[0].content_hash].append(row)
    return SQLiteReferenceIndex(rows, vector_rows, matrix, dict(exact_rows))


def sqlite_top_vector_rows(
    index: SQLiteReferenceIndex,
    query_vector: list[float],
    limit: int,
) -> list[tuple[ContentBlock, str, float]]:
    if not index.vector_rows or index.matrix.size == 0:
        return []
    query = np.asarray(query_vector, dtype=np.float32)
    norm = float(np.linalg.norm(query))
    if not norm or query.shape[0] != index.matrix.shape[1]:
        return []
    scores = index.matrix @ (query / norm)
    count = min(limit, scores.shape[0])
    if count == scores.shape[0]:
        indices = np.argsort(scores)[::-1]
    else:
        candidate_indices = np.argpartition(scores, -count)[-count:]
        indices = candidate_indices[np.argsort(scores[candidate_indices])[::-1]]
    return [
        (*index.vector_rows[int(row_index)], float(scores[int(row_index)]))
        for row_index in indices
    ]


class SimilarityService:
    def __init__(self, settings: Settings, embedding_service: EmbeddingService):
        self.settings = settings
        self.embedding_service = embedding_service

    async def check(
        self,
        session: AsyncSession,
        content: str,
        limit: int = 10,
        *,
        exclude_site_id: int | None = None,
        persist: bool = True,
        sqlite_reference_index: SQLiteReferenceIndex | None = None,
    ) -> dict:
        normalized = normalize_text(content)
        digest = content_hash(content)
        query_core, query_chemical_ratio = strip_chemical_fields(content)
        query_vector = (await self.embedding_service.embed([embedding_text(content)]))[0]

        scope_filters = [Site.site_type == "baseline"]
        if exclude_site_id is not None:
            scope_filters.append(ContentBlock.site_id != exclude_site_id)
        reference_filters = [
            *scope_filters,
            ContentBlock.embedding_version == self.embedding_service.signature,
        ]

        if session.get_bind().dialect.name == "sqlite":
            if sqlite_reference_index is None:
                statement = select(ContentBlock, Site.name.label("site_name")).join(
                    Site, Site.id == ContentBlock.site_id
                ).where(*scope_filters)
                scope_rows = list((await session.execute(statement)).all())
                sqlite_reference_index = build_sqlite_reference_index(
                    scope_rows,
                    self.embedding_service.signature,
                )
            rows = sqlite_top_vector_rows(
                sqlite_reference_index,
                query_vector,
                self.settings.similarity_candidate_limit,
            )
        else:
            distance = ContentBlock.embedding.cosine_distance(query_vector)
            statement = (
                select(ContentBlock, Site.name.label("site_name"), (1 - distance).label("semantic_score"))
                .join(Site, Site.id == ContentBlock.site_id)
                .where(*reference_filters)
                .order_by(distance)
                .limit(self.settings.similarity_candidate_limit)
            )
            rows = list((await session.execute(statement)).all())
            if len(normalized) >= 3:
                lexical_rank = func.similarity(ContentBlock.normalized_content, normalized)
                lexical_statement = (
                    select(
                        ContentBlock,
                        Site.name.label("site_name"),
                        (1 - distance).label("semantic_score"),
                    )
                    .join(Site, Site.id == ContentBlock.site_id)
                    .where(
                        *reference_filters,
                        ContentBlock.normalized_content.op("%")(
                            normalized
                        ),
                    )
                    .order_by(lexical_rank.desc())
                    .limit(self.settings.similarity_candidate_limit)
                )
                lexical_rows = list((await session.execute(lexical_statement)).all())
                semantic_ids = {block.id for block, _, _ in rows}
                rows.extend(row for row in lexical_rows if row[0].id not in semantic_ids)

        if session.get_bind().dialect.name == "sqlite" and sqlite_reference_index is not None:
            exact_rows = sqlite_reference_index.exact_rows.get(digest, [])[:50]
        else:
            exact_statement = (
                select(ContentBlock, Site.name.label("site_name"))
                .join(Site, Site.id == ContentBlock.site_id)
                .where(*scope_filters)
                .where(ContentBlock.content_hash == digest)
                .limit(50)
            )
            exact_rows = list((await session.execute(exact_statement)).all())
        candidates: dict[int, tuple[ContentBlock, str, float]] = {
            block.id: (block, site_name, float(semantic_score or 0.0))
            for block, site_name, semantic_score in rows
        }
        for block, site_name in exact_rows:
            candidates.setdefault(block.id, (block, site_name, 1.0))

        results: list[dict] = []
        for block, site_name, semantic_score in candidates.values():
            lexical_score, chemical_overlap = lexical_similarity(
                content,
                block.original_content,
                self.settings.similarity_chemical_discount,
            )
            semantic_score = max(0.0, min(1.0, semantic_score))
            exact = block.content_hash == digest
            meaningful_exact = exact and len(query_core) >= 8
            if meaningful_exact:
                overall = 1.0
                lexical_score = 1.0
            else:
                overall = (
                    self.settings.similarity_lexical_weight * lexical_score
                    + self.settings.similarity_semantic_weight * semantic_score
                )
                if exact and query_chemical_ratio > 0.5:
                    overall *= 1 - self.settings.similarity_chemical_discount * query_chemical_ratio
            overall = max(0.0, min(1.0, overall))
            if overall + 1e-9 < self.settings.similarity_min_score:
                continue

            results.append(
                {
                    "content_block_id": block.id,
                    "overall_similarity": round(overall, 4),
                    "risk_level": risk_level(overall),
                    "original_content": block.original_content,
                    "highlight_segments": highlight_segments(content, block.original_content),
                    "site_id": block.site_id,
                    "site_name": site_name,
                    "page_title": block.page_title,
                    "url": block.url,
                    "content_type": block.content_type,
                    "lexical_similarity": round(lexical_score, 4),
                    "semantic_similarity": round(semantic_score, 4),
                    "exact_match": exact,
                    "chemical_ratio": round(chemical_overlap, 4),
                }
            )

        results.sort(key=lambda item: item["overall_similarity"], reverse=True)
        results = results[:limit]
        check_id = 0
        if persist:
            check = SimilarityCheck(
                input_content=content,
                normalized_content=normalized,
                content_hash=digest,
                result_count=len(results),
                top_score=results[0]["overall_similarity"] if results else None,
                results=results,
            )
            session.add(check)
            await session.commit()
            await session.refresh(check)
            check_id = check.id
        return {
            "check_id": check_id,
            "result_count": len(results),
            "threshold": self.settings.similarity_min_score,
            "results": results,
        }
