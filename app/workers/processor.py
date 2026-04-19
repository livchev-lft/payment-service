"""Payment processing logic, extracted so it can be unit-tested independently."""
from __future__ import annotations

import asyncio
import logging
import random
import uuid

from app.core.config import Settings
from app.domain.enums import PaymentStatus
from app.infrastructure.db.repositories import PaymentRepository
from app.infrastructure.db.session import get_sessionmaker
from app.infrastructure.webhook.client import WebhookClient, WebhookDeliveryError

logger = logging.getLogger(__name__)


class PaymentProcessor:
    def __init__(self, settings: Settings, webhook_client: WebhookClient) -> None:
        self._settings = settings
        self._webhook = webhook_client

    async def process(self, event: dict) -> None:
        """Process a single payment event.

        Raises on transient errors (DB / broker-worthy) so that the consumer
        can route the message into the retry chain. A failed payment (90/10
        emulation) is NOT raised — it's a valid business outcome and gets
        written to DB + delivered via webhook as `failed`.
        """
        payment_id = uuid.UUID(event["payment_id"])
        logger.info("Processing payment", extra={"payment_id": str(payment_id)})

        # Simulate gateway call
        await asyncio.sleep(
            random.uniform(
                self._settings.processing_min_seconds,
                self._settings.processing_max_seconds,
            )
        )
        gateway_ok = random.random() >= self._settings.processing_failure_rate
        new_status = PaymentStatus.SUCCEEDED if gateway_ok else PaymentStatus.FAILED
        failure_reason = None if gateway_ok else "gateway declined (emulated)"

        # Update DB — this MUST succeed. If it raises, we retry the whole message.
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repo = PaymentRepository(session)
            await repo.mark_processed(payment_id, new_status, failure_reason)
            await session.commit()

        # Deliver webhook. Webhook has its own retry. If it still fails, we
        # log and move on — the payment state is already final in DB, and
        # retrying the whole message would re-run the emulated processing
        # and flip the result randomly, which is worse.
        webhook_payload = {
            "payment_id": str(payment_id),
            "status": new_status.value,
            "failure_reason": failure_reason,
        }
        try:
            await self._webhook.deliver(event["webhook_url"], webhook_payload)
            logger.info("Webhook delivered", extra={"payment_id": str(payment_id)})
        except WebhookDeliveryError as e:
            logger.error(
                "Webhook delivery failed after retries",
                extra={"payment_id": str(payment_id), "error": str(e)},
            )
            # Not re-raised: payment outcome is final, see comment above.
