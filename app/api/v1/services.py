"""Application services.

The service layer orchestrates repositories inside transactions. It is the
only place allowed to commit DB transactions (repositories just stage work).
"""
from __future__ import annotations

import hashlib
import logging
import uuid

import orjson
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import PaymentCreateRequest
from app.domain.enums import PaymentStatus
from app.domain.exceptions import IdempotencyConflictError
from app.infrastructure.db.models import Payment
from app.infrastructure.db.repositories import OutboxRepository, PaymentRepository

logger = logging.getLogger(__name__)


def _hash_request(req: PaymentCreateRequest) -> str:
    """Stable hash of the request body for idempotency body-check."""
    canonical = {
        "amount": str(req.amount),
        "currency": req.currency.value,
        "description": req.description,
        "metadata": req.metadata,
        "webhook_url": str(req.webhook_url),
    }
    blob = orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(blob).hexdigest()


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._outbox = OutboxRepository(session)

    async def create(
        self,
        req: PaymentCreateRequest,
        idempotency_key: str,
    ) -> tuple[Payment, bool]:
        """Create a payment idempotently.

        Returns (payment, created). `created` is False when we returned an
        existing payment for the same idempotency key.

        Writes Payment + OutboxEvent in a single transaction — this is the
        transactional-outbox guarantee: if we commit, the event will
        eventually reach the broker via the relay.

        Raises IdempotencyConflictError if the same key is reused with a
        different body.
        """
        request_hash = _hash_request(req)

        # Fast path: key already used
        existing = await self._payments.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError(
                    "Idempotency-Key reused with a different request body"
                )
            return existing, False

        # Happy path: create payment + outbox event atomically
        payment = Payment(
            id=uuid.uuid4(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            amount=req.amount,
            currency=req.currency.value,
            description=req.description,
            payment_metadata=req.metadata,
            webhook_url=str(req.webhook_url),
            status=PaymentStatus.PENDING,
        )
        await self._payments.add(payment)

        await self._outbox.add(
            aggregate_id=payment.id,
            event_type="payment.created",
            payload={
                "payment_id": str(payment.id),
                "idempotency_key": idempotency_key,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "description": payment.description,
                "metadata": payment.payment_metadata,
                "webhook_url": payment.webhook_url,
            },
        )

        try:
            await self._session.commit()
        except IntegrityError:
            # Lost a race with a concurrent request using the same key.
            # Re-read and resolve the same way as the fast path.
            await self._session.rollback()
            existing = await self._payments.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise  # genuinely unexpected
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError(
                    "Idempotency-Key reused with a different request body"
                ) from None
            return existing, False

        logger.info("Payment created", extra={"payment_id": str(payment.id)})
        return payment, True

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._payments.get_by_id(payment_id)
