"""Payment processing logic.

Writes the payment outcome and the webhook.send outbox event in a single
transaction so the webhook event is never lost if this worker crashes after
committing the payment status.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid

from app.core.config import Settings
from app.domain.enums import PaymentStatus
from app.infrastructure.db.repositories import OutboxRepository, PaymentRepository
from app.infrastructure.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


class PaymentProcessor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def process(self, event: dict) -> None:
        payment_id = uuid.UUID(event["payment_id"])
        idempotency_key = event.get("idempotency_key", "")
        webhook_url = event["webhook_url"]
        logger.info("Processing payment", extra={"payment_id": str(payment_id)})

        await asyncio.sleep(
            random.uniform(
                self._settings.processing_min_seconds,
                self._settings.processing_max_seconds,
            )
        )
        gateway_ok = random.random() >= self._settings.processing_failure_rate
        new_status = PaymentStatus.SUCCEEDED if gateway_ok else PaymentStatus.FAILED
        failure_reason = None if gateway_ok else "gateway declined (emulated)"

        webhook_body = {
            "payment_id": str(payment_id),
            "status": new_status.value,
            "failure_reason": failure_reason,
            "amount": event.get("amount"),
            "currency": event.get("currency"),
        }

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            payments = PaymentRepository(session)
            outbox = OutboxRepository(session)
            await payments.mark_processed(payment_id, new_status, failure_reason)
            await outbox.add(
                aggregate_id=payment_id,
                event_type="webhook.send",
                payload={
                    "payment_id": str(payment_id),
                    "idempotency_key": idempotency_key,
                    "webhook_url": webhook_url,
                    "payload": webhook_body,
                },
            )
            await session.commit()

        logger.info(
            "Payment processed, webhook.send queued",
            extra={"payment_id": str(payment_id), "status": new_status.value},
        )
