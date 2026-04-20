"""RabbitMQ topology constants.

Two symmetric chains:
  payments : `payments.new` consumed by payment-consumer, retries via
             `payments.dlx` -> `payments.retry.{1,2,3}` with TTL backoff,
             terminal `payments.dlq`.
  webhooks : `webhooks.send` consumed by webhook-worker, retries via
             `webhooks.dlx` -> `webhooks.retry.{1,2,3}`, terminal `webhooks.dlq`.
"""
from __future__ import annotations

# Payments chain
MAIN_EXCHANGE = "payments"
DLX_EXCHANGE = "payments.dlx"

MAIN_QUEUE = "payments.new"
DLQ_QUEUE = "payments.dlq"

RK_NEW = "payments.new"
RK_DLQ = "dlq"

RETRY_QUEUE_PREFIX = "payments.retry"


def retry_queue_name(attempt: int) -> str:
    return f"{RETRY_QUEUE_PREFIX}.{attempt}"


def retry_routing_key(attempt: int) -> str:
    return f"retry.{attempt}"


# Webhooks chain
WEBHOOKS_EXCHANGE = "webhooks"
WEBHOOKS_DLX_EXCHANGE = "webhooks.dlx"

WEBHOOKS_QUEUE = "webhooks.send"
WEBHOOKS_DLQ = "webhooks.dlq"

WEBHOOKS_NEW_RK = "webhooks.send"
WEBHOOKS_DLQ_RK = "dlq"

WEBHOOKS_RETRY_QUEUES: dict[int, str] = {
    1: "webhooks.retry.1",
    2: "webhooks.retry.2",
    3: "webhooks.retry.3",
}
WEBHOOKS_RETRY_RK: dict[int, str] = {
    1: "retry.1",
    2: "retry.2",
    3: "retry.3",
}
WEBHOOKS_RETRY_DELAYS_MS: dict[int, int] = {1: 1000, 2: 2000, 3: 4000}


def get_retry_delays_ms(base: int) -> dict[int, int]:
    return {1: base, 2: base * 2, 3: base * 4}


HEADER_RETRY_COUNT = "x-retry-count"
HEADER_IDEMPOTENCY_KEY = "x-idempotency-key"
