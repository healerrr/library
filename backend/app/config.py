from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "站群文案相似度检测系统"
    # SQLite keeps local development self-contained. Docker Compose overrides
    # this with PostgreSQL/pgvector for production-style deployments.
    database_url: str = "sqlite+aiosqlite:///./.data/copyguard-local.db"

    embedding_provider: str = "hashing"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimension: int = 512
    fastembed_cache_path: str = ".data/fastembed"

    similarity_lexical_weight: float = Field(default=0.45, ge=0, le=1)
    similarity_semantic_weight: float = Field(default=0.55, ge=0, le=1)
    similarity_chemical_discount: float = Field(default=0.70, ge=0, le=1)
    similarity_min_score: float = Field(default=0.60, ge=0, le=1)
    similarity_candidate_limit: int = Field(default=200, ge=10, le=2000)

    crawler_max_pages: int = Field(default=100, ge=1, le=5000)
    crawler_timeout_seconds: float = Field(default=15.0, ge=1, le=60)
    crawler_user_agent: str = "CopyGuardBot/1.0"
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_weights(self):
        total = self.similarity_lexical_weight + self.similarity_semantic_weight
        if abs(total - 1.0) > 0.001:
            raise ValueError("SIMILARITY_LEXICAL_WEIGHT 与 SIMILARITY_SEMANTIC_WEIGHT 之和必须为 1")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
