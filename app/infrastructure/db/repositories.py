"""Data access layer.

PaymentRepository and OutboxRepository. Both operate on a session passed in
from the caller — this lets services compose multi-repo operations inside a
single transaction (which is the whole point of the outbox pattern).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OutboxStatus, PaymentStatus
from app.infrastructure.db.models import OutboxEvent, Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        stmt = select(Payment).where(Payment.idempotency_key == key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, payment: Payment) -> None:
        self._session.add(payment)

    async def mark_processed(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
        failure_reason: str | None = None,
    ) -> None:
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                status=status,
                failure_reason=failure_reason,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        aggregate_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(event)
        return event

    async def claim_batch(self, limit: int) -> list[OutboxEvent]:
        """Atomically claim a batch of pending events.

        Uses FOR UPDATE SKIP LOCKED so that multiple relay workers never
        pick the same row. The caller MUST commit or rollback the surrounding
        transaction — the row locks are held until then.
        """
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING)
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_sent(self, event_ids: list[uuid.UUID]) -> None:
        if not event_ids:
            return
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(event_ids))
            .values(status=OutboxStatus.SENT, sent_at=datetime.now(timezone.utc))
        )
        await self._session.execute(stmt)
