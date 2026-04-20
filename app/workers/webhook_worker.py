"""Webhook worker: delivers webhook.send messages, persists outcome in DB.

Retry is owned by the webhooks broker chain — on a single delivery failure
this worker republishes with an incremented x-retry-count, and after
max_retry_attempts republishes to webhooks.dlq and marks the payment's
webhook_delivery_status as failed so API clients can see it.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.broker.setup import (
    declare_topology,
    get_broker,
    webhooks_exchange,
    webhooks_queue,
)
from app.infrastructure.broker.topology import (
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
)
from app.infrastructure.db.repositories import PaymentRepository
from app.infrastructure.db.session import get_sessionmaker
from app.infrastructure.webhook.client import WebhookClient, WebhookDeliveryError

logger = logging.getLogger(__name__)

broker = get_broker()
app = FastStream(broker)

_settings = get_settings()
_publisher = Publisher(broker)
_client = WebhookClient()


async def _mark_delivered(payment_id: uuid.UUID) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = PaymentRepository(session)
        await repo.mark_webhook_delivered(payment_id)
        await session.commit()


async def _mark_failed(payment_id: uuid.UUID, reason: str) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = PaymentRepository(session)
        await repo.mark_webhook_failed(payment_id, reason=reason)
        await session.commit()


@broker.subscriber(webhooks_queue, webhooks_exchange)
async def handle_webhook(body: dict, message: RabbitMessage) -> None:
    headers = message.headers or {}
    retry_count = int(headers.get(HEADER_RETRY_COUNT, 0) or 0)
    idempotency_key = str(headers.get(HEADER_IDEMPOTENCY_KEY, "") or "")

    payment_id = uuid.UUID(body["payment_id"])
    url = body["webhook_url"]
    payload = body["payload"]

    try:
        await _client.deliver_once(url, payload)
    except WebhookDeliveryError as e:
        logger.warning(
            "Webhook delivery attempt failed",
            extra={
                "payment_id": str(payment_id),
                "attempt": retry_count,
                "error": str(e),
            },
        )
        next_attempt = retry_count + 1
        if next_attempt > _settings.max_retry_attempts:
            await _mark_failed(payment_id, reason=str(e))
            await _publisher.publish_webhook_dlq(
                payload=body, idempotency_key=idempotency_key, reason=str(e)
            )
        else:
            await _publisher.publish_webhook_retry(
                payload=body,
                idempotency_key=idempotency_key,
                attempt=next_attempt,
            )
        return

    await _mark_delivered(payment_id)
    logger.info("Webhook delivered", extra={"payment_id": str(payment_id)})


@app.on_startup
async def _configure() -> None:
    configure_logging()


@app.after_startup
async def _declare() -> None:
    await declare_topology(broker)
    logger.info("Webhook worker started")


if __name__ == "__main__":
    asyncio.run(app.run())
