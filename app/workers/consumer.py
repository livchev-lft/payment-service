"""Payment consumer: processes payments.new, routes failures to retry/DLQ.

Does not own the outbox relay anymore — that's a separate service now.
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
from app.workers.processor import PaymentProcessor

logger = logging.getLogger(__name__)

broker = get_broker()
app = FastStream(broker)

_settings = get_settings()
_publisher = Publisher(broker)
_processor = PaymentProcessor(settings=_settings)


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
async def _declare() -> None:
    await declare_topology(broker)
    logger.info("Payment consumer started")


if __name__ == "__main__":
    asyncio.run(app.run())
