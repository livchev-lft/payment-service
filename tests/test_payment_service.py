from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import PaymentCreateRequest
from app.api.v1.services import PaymentService
from app.domain.enums import Currency, OutboxStatus, PaymentStatus
from app.domain.exceptions import IdempotencyConflictError
from app.infrastructure.db.models import OutboxEvent, Payment


def _req(**overrides) -> PaymentCreateRequest:
    base = dict(
        amount=Decimal("250.00"),
        currency=Currency.USD,
        description="service test",
        metadata={"k": "v"},
        webhook_url="https://example.com/cb",
    )
    base.update(overrides)
    return PaymentCreateRequest(**base)


async def test_create_writes_payment_and_outbox_in_same_tx(db_session: AsyncSession):
    service = PaymentService(db_session)
    payment, created = await service.create(_req(), idempotency_key="svc-1")

    assert created is True
    assert payment.status == PaymentStatus.PENDING

    row = await db_session.get(Payment, payment.id)
    assert row is not None

    stmt = select(OutboxEvent).where(OutboxEvent.aggregate_id == payment.id)
    events = (await db_session.execute(stmt)).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "payment.created"
    assert events[0].status == OutboxStatus.PENDING


async def test_create_is_idempotent_on_duplicate_call(db_session: AsyncSession):
    service = PaymentService(db_session)
    req = _req()

    first, created1 = await service.create(req, idempotency_key="svc-dup")
    second, created2 = await service.create(req, idempotency_key="svc-dup")

    assert created1 is True
    assert created2 is False
    assert first.id == second.id

    stmt = select(Payment).where(Payment.idempotency_key == "svc-dup")
    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1


async def test_create_raises_conflict_on_different_body_same_key(
    db_session: AsyncSession,
):
    service = PaymentService(db_session)

    await service.create(_req(amount=Decimal("1.00")), idempotency_key="svc-conf")
    with pytest.raises(IdempotencyConflictError):
        await service.create(
            _req(amount=Decimal("2.00")), idempotency_key="svc-conf"
        )


async def test_get_returns_none_for_missing_id(db_session: AsyncSession):
    service = PaymentService(db_session)
    assert await service.get(uuid.uuid4()) is None
