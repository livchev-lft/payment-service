"""FastStream RabbitMQ broker singleton and topology declaration.

Retry queues and DLQ have no subscribers, so bindings are set explicitly here
via the aio-pika queue/exchange objects that FastStream returns from
declare_queue / declare_exchange.
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
    RK_DLQ,
    RK_NEW,
    WEBHOOKS_DLQ,
    WEBHOOKS_DLQ_RK,
    WEBHOOKS_DLX_EXCHANGE,
    WEBHOOKS_EXCHANGE,
    WEBHOOKS_NEW_RK,
    WEBHOOKS_QUEUE,
    WEBHOOKS_RETRY_QUEUES,
    WEBHOOKS_RETRY_RK,
    get_retry_delays_ms,
    retry_queue_name,
    retry_routing_key,
)

logger = logging.getLogger(__name__)

_broker: RabbitBroker | None = None


def get_broker() -> RabbitBroker:
    global _broker
    if _broker is None:
        _broker = RabbitBroker(get_settings().rabbitmq_url)
    return _broker


main_exchange = RabbitExchange(MAIN_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
dlx_exchange = RabbitExchange(DLX_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
main_queue = RabbitQueue(MAIN_QUEUE, durable=True, routing_key=RK_NEW)

webhooks_exchange = RabbitExchange(
    WEBHOOKS_EXCHANGE, type=ExchangeType.DIRECT, durable=True
)
webhooks_dlx_exchange = RabbitExchange(
    WEBHOOKS_DLX_EXCHANGE, type=ExchangeType.DIRECT, durable=True
)
webhooks_queue = RabbitQueue(WEBHOOKS_QUEUE, durable=True, routing_key=WEBHOOKS_NEW_RK)


async def declare_topology(broker: RabbitBroker) -> None:
    settings = get_settings()
    retry_delays = get_retry_delays_ms(settings.retry_base_delay_ms)

    main_ex = await broker.declare_exchange(main_exchange)
    dlx_ex = await broker.declare_exchange(dlx_exchange)
    main_q = await broker.declare_queue(main_queue)
    await main_q.bind(main_ex, routing_key=RK_NEW)

    for attempt, ttl_ms in retry_delays.items():
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

    wh_ex = await broker.declare_exchange(webhooks_exchange)
    wh_dlx_ex = await broker.declare_exchange(webhooks_dlx_exchange)
    wh_q = await broker.declare_queue(webhooks_queue)
    await wh_q.bind(wh_ex, routing_key=WEBHOOKS_NEW_RK)

    for attempt, ttl_ms in retry_delays.items():
        wh_retry_q = RabbitQueue(
            WEBHOOKS_RETRY_QUEUES[attempt],
            durable=True,
            arguments={
                "x-message-ttl": ttl_ms,
                "x-dead-letter-exchange": WEBHOOKS_EXCHANGE,
                "x-dead-letter-routing-key": WEBHOOKS_NEW_RK,
            },
        )
        whrq = await broker.declare_queue(wh_retry_q)
        await whrq.bind(wh_dlx_ex, routing_key=WEBHOOKS_RETRY_RK[attempt])

    wh_dlq = await broker.declare_queue(RabbitQueue(WEBHOOKS_DLQ, durable=True))
    await wh_dlq.bind(wh_dlx_ex, routing_key=WEBHOOKS_DLQ_RK)

    logger.info("RabbitMQ topology declared")
