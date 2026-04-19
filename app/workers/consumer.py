"""Consumer process: FastStream app that processes payments and runs the outbox relay.

Failure routing uses ack-on-success + manual republish rather than nack/requeue
so we can carry the retry counter across attempts via the x-retry-count header.
Outbox relay runs as a background task inside this process for now — it will
move to its own deployment later.
"""
from __future__ import annotations

import asyncio
import logging

from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.broker.setup import (
    declare_topology,
    get_broker,
    main_exchange,
    main_queue,
)
from app.infrastructure.broker.topology import (
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
)
from app.infrastructure.webhook.client import WebhookClient
from app.workers.outbox_relay import OutboxRelay
from app.workers.processor import PaymentProcessor

logger = logging.getLogger(__name__)

broker = get_broker()
app = FastStream(broker)

_settings = get_settings()
_publisher = Publisher(broker)
_processor = PaymentProcessor(
    settings=_settings,
    webhook_client=WebhookClient(max_attempts=3),
)
_relay = OutboxRelay(_settings, _publisher)
_relay_task: asyncio.Task[None] | None = None


@broker.subscriber(main_queue, main_exchange)
async def handle_payment(body: dict, message: RabbitMessage) -> None:
    headers = message.headers or {}
    retry_count = int(headers.get(HEADER_RETRY_COUNT, 0) or 0)
    idempotency_key = str(headers.get(HEADER_IDEMPOTENCY_KEY, "") or "")

    try:
        await _processor.process(body)
    except Exception as e:
        logger.exception("Processing failed, routing to retry/DLQ")
        next_attempt = retry_count + 1
        if next_attempt > _settings.max_retry_attempts:
            await _publisher.publish_dlq(
                payload=body,
                idempotency_key=idempotency_key,
                reason=f"{type(e).__name__}: {e}",
            )
        else:
            await _publisher.publish_retry(
                payload=body,
                idempotency_key=idempotency_key,
                attempt=next_attempt,
            )


@app.on_startup
async def _configure() -> None:
    configure_logging()


@app.after_startup
async def _start_relay() -> None:
    await declare_topology(broker)
    global _relay_task
    _relay_task = asyncio.create_task(_relay.run(), name="outbox-relay")
    logger.info("Consumer started")


@app.on_shutdown
async def _stop_relay() -> None:
    _relay.stop()
    if _relay_task is not None:
        try:
            await asyncio.wait_for(_relay_task, timeout=5)
        except asyncio.TimeoutError:
            _relay_task.cancel()
    logger.info("Consumer stopped")


if __name__ == "__main__":
    asyncio.run(app.run())
