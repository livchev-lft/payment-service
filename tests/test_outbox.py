from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.enums import OutboxStatus
from app.infrastructure.db import session as session_module
from app.infrastructure.db.models import OutboxEvent
from app.infrastructure.db.repositories import OutboxRepository


async def _seed_events(session: AsyncSession, n: int) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(n):
        ev = OutboxEvent(
            aggregate_id=uuid.uuid4(),
            event_type="payment.created",
            payload={"i": i},
        )
        session.add(ev)
        await session.flush()
        ids.append(ev.id)
    await session.commit()
    return ids


async def test_outbox_claim_batch_skips_locked_rows(
    db_session: AsyncSession, test_engine: AsyncEngine
):
    await _seed_events(db_session, 10)

    sessionmaker = session_module.get_sessionmaker()
    first_entered = asyncio.Event()
    results: dict[str, list[uuid.UUID]] = {}

    async def first() -> None:
        async with sessionmaker() as s, s.begin():
            events = await OutboxRepository(s).claim_batch(3)
            results["first"] = [e.id for e in events]
            first_entered.set()
            await asyncio.sleep(0.3)

    async def second() -> None:
        await first_entered.wait()
        async with sessionmaker() as s, s.begin():
            events = await OutboxRepository(s).claim_batch(3)
            results["second"] = [e.id for e in events]

    await asyncio.gather(first(), second())

    assert len(results["first"]) == 3
    assert len(results["second"]) == 3
    assert set(results["first"]).isdisjoint(results["second"])


async def test_outbox_mark_sent_updates_status_and_sent_at(
    db_session: AsyncSession,
):
    ids = await _seed_events(db_session, 2)
    repo = OutboxRepository(db_session)

    await repo.mark_sent(ids)
    await db_session.commit()

    for event_id in ids:
        row = await db_session.get(OutboxEvent, event_id)
        assert row is not None
        assert row.status == OutboxStatus.SENT
        assert row.sent_at is not None


async def test_outbox_claim_batch_respects_limit(db_session: AsyncSession):
    await _seed_events(db_session, 5)

    sessionmaker = session_module.get_sessionmaker()
    async with sessionmaker() as s, s.begin():
        batch = await OutboxRepository(s).claim_batch(2)
        assert len(batch) == 2

    async with sessionmaker() as s, s.begin():
        batch = await OutboxRepository(s).claim_batch(100)
        assert len(batch) == 5
