FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
    fastapi==0.115.5 \
    "uvicorn[standard]==0.32.1" \
    pydantic==2.9.2 \
    pydantic-settings==2.6.1 \
    "sqlalchemy[asyncio]==2.0.36" \
    asyncpg==0.30.0 \
    alembic==1.14.0 \
    aio-pika==9.4.3 \
    httpx==0.27.2 \
    orjson==3.10.11 \
    tenacity==9.0.0

COPY app ./app
COPY alembic.ini ./
COPY scripts ./scripts
RUN chmod +x ./scripts/*.sh

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
