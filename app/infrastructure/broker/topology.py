"""RabbitMQ topology constants.

Exchanges:
- `payments`        (direct) — main business exchange
- `payments.dlx`    (direct) — dead-letter exchange used for retry routing

Queues:
- `payments.new`    — main work queue, consumer reads from here
- `payments.retry.{1,2,3}` — retry holding queues with message-TTL 1s / 2s / 4s,
                             on TTL expiry DLX routes them back to `payments`
- `payments.dlq`    — terminal dead-letter queue for exceeded retries
"""
from __future__ import annotations

MAIN_EXCHANGE = "payments"
DLX_EXCHANGE = "payments.dlx"

MAIN_QUEUE = "payments.new"
DLQ_QUEUE = "payments.dlq"

RK_NEW = "payments.new"
RK_DLQ = "dlq"

RETRY_QUEUE_PREFIX = "payments.retry"

# attempt -> TTL ms. Exponential backoff: 1s / 2s / 4s.
RETRY_DELAYS_MS: dict[int, int] = {
    1: 1000,
    2: 2000,
    3: 4000,
}


def retry_queue_name(attempt: int) -> str:
    return f"{RETRY_QUEUE_PREFIX}.{attempt}"


def retry_routing_key(attempt: int) -> str:
    return f"retry.{attempt}"


HEADER_RETRY_COUNT = "x-retry-count"
HEADER_IDEMPOTENCY_KEY = "x-idempotency-key"
