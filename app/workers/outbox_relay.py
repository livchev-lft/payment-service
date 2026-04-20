"""Outbox relay: polls the `outbox` table and publishes pending events.

Routes by `event_type`:
- payment.created -> payments exchange (payments.new)
- webhook.send   -> webhooks exchange (webhooks.send)

Uses FOR UPDATE SKIP LOCKED, so running multiple relay instances is safe.
"""
from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.db.repositories import OutboxRepository
from app.infrastructure.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


class UnknownOutboxEventType(Exception):
    pass


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
            async with session.begin():
                events = await repo.claim_batch(self._settings.outbox_batch_size)
                if not events:
                    return 0

                published_ids = []
                for event in events:
                    idempotency_key = event.payload.get("idempotency_key", "")
                    try:
                        await self._dispatch(event.event_type, event.payload, idempotency_key)
                        published_ids.append(event.id)
                    except Exception:
                        logger.exception(
                            "Failed to publish outbox event",
                            extra={
                                "event_id": str(event.id),
                                "event_type": event.event_type,
                            },
                        )
                        raise

                await repo.mark_sent(published_ids)

            logger.info("Published %d outbox events", len(events))
            return len(events)

    async def _dispatch(self, event_type: str, payload: dict, idempotency_key: str) -> None:
        if event_type == "payment.created":
            await self._publisher.publish_new_payment(
                payload=payload, idempotency_key=idempotency_key
            )
        elif event_type == "webhook.send":
            await self._publisher.publish_webhook(
                payload=payload, idempotency_key=idempotency_key
            )
        else:
            raise UnknownOutboxEventType(event_type)
