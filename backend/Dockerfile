FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system --gid 10001 copyguard \
    && adduser --system --uid 10001 --ingroup copyguard copyguard \
    && mkdir -p /models \
    && chown copyguard:copyguard /models

COPY --chown=copyguard:copyguard alembic.ini ./
COPY --chown=copyguard:copyguard alembic ./alembic
COPY --chown=copyguard:copyguard app ./app
COPY --chown=copyguard:copyguard docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

USER copyguard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
