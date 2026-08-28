#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL="$(python - <<'PY'
import os
from urllib.parse import quote

user = quote(os.environ["POSTGRES_USER"], safe="")
password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
host = os.environ.get("POSTGRES_HOST", "db")
port = os.environ.get("POSTGRES_PORT", "5432")
database = quote(os.environ["POSTGRES_DB"], safe="")
print(f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}")
PY
)"
  export DATABASE_URL
fi

alembic upgrade head

if [ "${PRELOAD_EMBEDDING_MODEL:-false}" = "true" ] && [ "${EMBEDDING_PROVIDER:-hashing}" = "fastembed" ]; then
  echo "Preloading semantic embedding model into the persistent cache..."
  python - <<'PY'
import asyncio

from app.services.embeddings import get_embedding_service

asyncio.run(get_embedding_service().embed(["模型预热"]))
PY
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
