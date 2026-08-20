import asyncio
import hashlib
import math
from functools import lru_cache

from app.config import Settings, get_settings


class EmbeddingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._model_lock = asyncio.Lock()

    async def _get_fastembed_model(self):
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = await asyncio.to_thread(
                    TextEmbedding,
                    model_name=self.settings.embedding_model,
                    cache_dir=self.settings.fastembed_cache_path,
                )
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.embedding_provider == "hashing":
            return [self._hashing_embedding(text) for text in texts]
        if self.settings.embedding_provider != "fastembed":
            raise RuntimeError(f"不支持的 EMBEDDING_PROVIDER: {self.settings.embedding_provider}")

        model = await self._get_fastembed_model()

        def run_embedding() -> list[list[float]]:
            return [vector.tolist() for vector in model.embed(texts)]

        vectors = await asyncio.to_thread(run_embedding)
        if vectors and len(vectors[0]) != self.settings.embedding_dimension:
            raise RuntimeError(
                f"向量模型输出 {len(vectors[0])} 维，但 EMBEDDING_DIMENSION="
                f"{self.settings.embedding_dimension}"
            )
        return vectors

    def _hashing_embedding(self, text: str) -> list[float]:
        """Deterministic offline provider for local development and unit tests."""
        dimension = self.settings.embedding_dimension
        vector = [0.0] * dimension
        tokens = [text[i : i + 2] for i in range(max(1, len(text) - 1))] or [text]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(get_settings())
