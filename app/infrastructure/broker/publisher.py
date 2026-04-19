"""Thin publisher wrapper around aio-pika.

Used by both the outbox relay (to publish `payments.new` events) and the
consumer's failure path (to publish into retry queues / DLQ).

We intentionally use aio-pika directly rather than FastStream's publisher
because we need fine control over headers (x-retry-count) and routing keys.
"""
from __future__ import annotations

import logging

import aio_pika
import orjson

from app.infrastructure.broker.topology import (
    DLX_EXCHANGE,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
    MAIN_EXCHANGE,
    RK_DLQ,
    RK_NEW,
    retry_routing_key,
)

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, amqp_url: str) -> None:
        self._amqp_url = amqp_url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None

    async def connect(self) -> None:
        if self._connection is None or self._connection.is_closed:
            self._connection = await aio_pika.connect_robust(self._amqp_url)
            self._channel = await self._connection.channel(publisher_confirms=True)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    async def _channel_ready(self) -> aio_pika.abc.AbstractRobustChannel:
        await self.connect()
        assert self._channel is not None
        return self._channel

    async def publish_new_payment(
        self, payload: dict, idempotency_key: str
    ) -> None:
        """Publish a new payment event to the main work queue."""
        channel = await self._channel_ready()
        exchange = await channel.get_exchange(MAIN_EXCHANGE)
        message = aio_pika.Message(
            body=orjson.dumps(payload),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers={
                HEADER_RETRY_COUNT: 0,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
        )
        await exchange.publish(message, routing_key=RK_NEW)

    async def publish_retry(
        self,
        payload: dict,
        idempotency_key: str,
        attempt: int,
    ) -> None:
        """Publish to the retry queue for the given attempt number."""
        channel = await self._channel_ready()
        exchange = await channel.get_exchange(DLX_EXCHANGE)
        message = aio_pika.Message(
            body=orjson.dumps(payload),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers={
                HEADER_RETRY_COUNT: attempt,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
        )
        await exchange.publish(message, routing_key=retry_routing_key(attempt))
        logger.info(
            "Message sent to retry queue", extra={"attempt": attempt, "key": idempotency_key}
        )

    async def publish_dlq(self, payload: dict, idempotency_key: str, reason: str) -> None:
        """Publish to the terminal DLQ."""
        channel = await self._channel_ready()
        exchange = await channel.get_exchange(DLX_EXCHANGE)
        message = aio_pika.Message(
            body=orjson.dumps({**payload, "_dlq_reason": reason}),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers={HEADER_IDEMPOTENCY_KEY: idempotency_key},
        )
        await exchange.publish(message, routing_key=RK_DLQ)
        logger.warning(
            "Message sent to DLQ", extra={"reason": reason, "key": idempotency_key}
        )
