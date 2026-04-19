"""Outbox relay: polls the `outbox` table and publishes pending events.

Runs as a background asyncio task alongside the consumer. Uses FOR UPDATE
SKIP LOCKED so this is safe to run in multiple processes.
"""
from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.db.repositories import OutboxRepository
from app.infrastructure.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self, settings: Settings, publisher: Publisher) -> None:
        self._settings = settings
        self._publisher = publisher
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("Outbox relay started")
        sessionmaker = get_sessionmaker()
        while not self._stopping.is_set():
            try:
                published = await self._tick(sessionmaker)
            except Exception:
                logger.exception("Outbox relay tick failed")
                published = 0

            # If we published a full batch, loop immediately — there might be more.
            if published < self._settings.outbox_batch_size:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(),
                        timeout=self._settings.outbox_poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        logger.info("Outbox relay stopped")

    async def _tick(self, sessionmaker) -> int:
        async with sessionmaker() as session:
            repo = OutboxRepository(session)
            # The SELECT ... FOR UPDATE SKIP LOCKED below holds row locks until
            # we commit or rollback. We commit only after successful publish,
            # so a crash mid-publish leaves the row PENDING for another worker.
            async with session.begin():
                events = await repo.claim_batch(self._settings.outbox_batch_size)
                if not events:
                    return 0

                published_ids = []
                for event in events:
                    try:
                        await self._publisher.publish_new_payment(
                            payload=event.payload,
                            idempotency_key=event.payload.get("idempotency_key", ""),
                        )
                        published_ids.append(event.id)
                    except Exception:
                        logger.exception(
                            "Failed to publish outbox event",
                            extra={"event_id": str(event.id)},
                        )
                        # Stop this batch; the row lock will be released on
                        # rollback (the `async with session.begin()` handles
                        # commit/rollback based on whether we raise).
                        raise

                await repo.mark_sent(published_ids)

            logger.info("Published %d outbox events", len(events))
            return len(events)
