"""Declares the full RabbitMQ topology at startup using aio-pika.

FastStream auto-declares what its subscribers/publishers reference, but the
retry-queue chain is an implementation detail the business code shouldn't
know about. Declaring it explicitly here keeps topology in one place and
makes it reviewable.
"""
from __future__ import annotations

import logging

import aio_pika

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


async def declare_topology(amqp_url: str) -> None:
    """Idempotent — safe to call at every startup."""
    connection = await aio_pika.connect_robust(amqp_url)
    try:
        channel = await connection.channel()

        main_ex = await channel.declare_exchange(
            MAIN_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        dlx_ex = await channel.declare_exchange(
            DLX_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )

        # Main work queue. Nothing special — we publish to DLX manually from the
        # consumer on failure, because we need to inject retry metadata.
        main_q = await channel.declare_queue(
            MAIN_QUEUE,
            durable=True,
        )
        await main_q.bind(main_ex, routing_key=RK_NEW)

        # Retry queues: one per backoff delay. No consumer. When TTL expires,
        # the message is dead-lettered back to the main exchange.
        for attempt, ttl_ms in RETRY_DELAYS_MS.items():
            rq = await channel.declare_queue(
                retry_queue_name(attempt),
                durable=True,
                arguments={
                    "x-message-ttl": ttl_ms,
                    "x-dead-letter-exchange": MAIN_EXCHANGE,
                    "x-dead-letter-routing-key": RK_NEW,
                },
            )
            await rq.bind(dlx_ex, routing_key=retry_routing_key(attempt))

        # Terminal DLQ.
        dlq = await channel.declare_queue(DLQ_QUEUE, durable=True)
        await dlq.bind(dlx_ex, routing_key=RK_DLQ)

        logger.info("RabbitMQ topology declared")
    finally:
        await connection.close()
