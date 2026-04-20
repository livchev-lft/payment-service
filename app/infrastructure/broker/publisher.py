"""Publisher wrapper over FastStream RabbitBroker."""
from __future__ import annotations

import logging

from faststream.rabbit import RabbitBroker

from app.infrastructure.broker.topology import (
    DLX_EXCHANGE,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
    MAIN_EXCHANGE,
    RK_DLQ,
    RK_NEW,
    WEBHOOKS_DLQ_RK,
    WEBHOOKS_DLX_EXCHANGE,
    WEBHOOKS_EXCHANGE,
    WEBHOOKS_NEW_RK,
    WEBHOOKS_RETRY_RK,
    retry_routing_key,
)

logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish_new_payment(self, payload: dict, idempotency_key: str) -> None:
        await self._broker.publish(
            payload,
            exchange=MAIN_EXCHANGE,
            routing_key=RK_NEW,
            headers={
                HEADER_RETRY_COUNT: 0,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
            persist=True,
        )

    async def publish_retry(
        self, payload: dict, idempotency_key: str, attempt: int
    ) -> None:
        await self._broker.publish(
            payload,
            exchange=DLX_EXCHANGE,
            routing_key=retry_routing_key(attempt),
            headers={
                HEADER_RETRY_COUNT: attempt,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
            persist=True,
        )
        logger.info(
            "Payment retry scheduled",
            extra={"attempt": attempt, "key": idempotency_key},
        )

    async def publish_dlq(
        self, payload: dict, idempotency_key: str, reason: str
    ) -> None:
        await self._broker.publish(
            {**payload, "_dlq_reason": reason},
            exchange=DLX_EXCHANGE,
            routing_key=RK_DLQ,
            headers={HEADER_IDEMPOTENCY_KEY: idempotency_key},
            persist=True,
        )
        logger.warning(
            "Payment sent to DLQ",
            extra={"reason": reason, "key": idempotency_key},
        )

    async def publish_webhook(self, payload: dict, idempotency_key: str) -> None:
        await self._broker.publish(
            payload,
            exchange=WEBHOOKS_EXCHANGE,
            routing_key=WEBHOOKS_NEW_RK,
            headers={
                HEADER_RETRY_COUNT: 0,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
            persist=True,
        )

    async def publish_webhook_retry(
        self, payload: dict, idempotency_key: str, attempt: int
    ) -> None:
        await self._broker.publish(
            payload,
            exchange=WEBHOOKS_DLX_EXCHANGE,
            routing_key=WEBHOOKS_RETRY_RK[attempt],
            headers={
                HEADER_RETRY_COUNT: attempt,
                HEADER_IDEMPOTENCY_KEY: idempotency_key,
            },
            persist=True,
        )
        logger.info(
            "Webhook retry scheduled",
            extra={"attempt": attempt, "key": idempotency_key},
        )

    async def publish_webhook_dlq(
        self, payload: dict, idempotency_key: str, reason: str
    ) -> None:
        await self._broker.publish(
            {**payload, "_dlq_reason": reason},
            exchange=WEBHOOKS_DLX_EXCHANGE,
            routing_key=WEBHOOKS_DLQ_RK,
            headers={HEADER_IDEMPOTENCY_KEY: idempotency_key},
            persist=True,
        )
        logger.warning(
            "Webhook sent to DLQ",
            extra={"reason": reason, "key": idempotency_key},
        )
