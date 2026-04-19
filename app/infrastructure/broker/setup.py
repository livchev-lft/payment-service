"""FastStream RabbitMQ broker singleton and topology declaration.

Bindings for retry queues and DLQ are declared explicitly here because those
queues have no subscriber — without manual bind() they would exist detached
from the DLX exchange and TTL-expired messages would go nowhere.
"""
from __future__ import annotations

import logging

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.core.config import get_settings
from app.infrastructure.broker.topology import (
    DLQ_QUEUE,
    DLX_EXCHANGE,
    MAIN_EXCHANGE,
    MAIN_QUEUE,
    RETRY_DELAYS_MS,
    RK_DLQ,
    RK_NEW,
    retry_queue_name,
    retry_routing_key,
)

logger = logging.getLogger(__name__)

_broker: RabbitBroker | None = None


def get_broker() -> RabbitBroker:
    global _broker
    if _broker is None:
        settings = get_settings()
        _broker = RabbitBroker(settings.rabbitmq_url)
    return _broker


main_exchange = RabbitExchange(MAIN_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
dlx_exchange = RabbitExchange(DLX_EXCHANGE, type=ExchangeType.DIRECT, durable=True)

main_queue = RabbitQueue(MAIN_QUEUE, durable=True, routing_key=RK_NEW)


async def declare_topology(broker: RabbitBroker) -> None:
    """Idempotent declaration — safe to call from both API and consumer startup."""
    main_ex = await broker.declare_exchange(main_exchange)
    dlx_ex = await broker.declare_exchange(dlx_exchange)

    main_q = await broker.declare_queue(main_queue)
    await main_q.bind(main_ex, routing_key=RK_NEW)

    for attempt, ttl_ms in RETRY_DELAYS_MS.items():
        retry_q = RabbitQueue(
            retry_queue_name(attempt),
            durable=True,
            arguments={
                "x-message-ttl": ttl_ms,
                "x-dead-letter-exchange": MAIN_EXCHANGE,
                "x-dead-letter-routing-key": RK_NEW,
            },
        )
        rq = await broker.declare_queue(retry_q)
        await rq.bind(dlx_ex, routing_key=retry_routing_key(attempt))

    dlq = await broker.declare_queue(RabbitQueue(DLQ_QUEUE, durable=True))
    await dlq.bind(dlx_ex, routing_key=RK_DLQ)

    logger.info("RabbitMQ topology declared")
