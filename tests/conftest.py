from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.infrastructure.db import session as session_module


def _require_test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Export it before running pytest, "
            "e.g. TEST_DATABASE_URL="
            "postgresql+asyncpg://payments:payments@localhost:5432/payments"
        )
    return url


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    url = _require_test_db_url()
    engine = create_async_engine(url, pool_pre_ping=True)
    session_module._engine = engine
    session_module._sessionmaker = async_sessionmaker(
        engine, expire_on_commit=False, autoflush=False
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        session_module._engine = None
        session_module._sessionmaker = None


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(test_engine: AsyncEngine) -> None:
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE payments, outbox RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    Session = session_module.get_sessionmaker()
    async with Session() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def api_client(test_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def api_key_headers() -> dict[str, str]:
    return {"X-API-Key": get_settings().api_key}
