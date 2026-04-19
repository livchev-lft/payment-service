"""RabbitMQ topology.

Exchanges:
- `payments`        (direct) — main business exchange
- `payments.dlx`    (direct) — dead-letter exchange used for retry routing

Queues:
- `payments.new`    — main work queue. Consumer reads from here.
                      Dead-letters to `payments.dlx` with rk `payments.failed`.
- `payments.retry.{1,2,4}s` — retry holding queues with message-TTL.
                      On TTL expiry, messages go back to `payments` exchange
                      with rk `payments.new`.
- `payments.dlq`    — terminal dead-letter queue for messages that exceeded
                      MAX_RETRY_ATTEMPTS. No consumer — inspected manually.

Retry flow:
  consumer NACKs (raises)  →  publish to `payments.dlx` with rk `retry.{attempt}`
  retry queue TTL expires  →  DLX routes back to `payments` / `payments.new`
  attempt > MAX            →  publish to `payments.dlx` with rk `dlq`

We use plain TTL + DLX (no rabbitmq_delayed_message_exchange plugin needed).
"""
from __future__ import annotations

MAIN_EXCHANGE = "payments"
DLX_EXCHANGE = "payments.dlx"

MAIN_QUEUE = "payments.new"
DLQ_QUEUE = "payments.dlq"

# Routing keys
RK_NEW = "payments.new"
RK_DLQ = "dlq"

RETRY_QUEUE_PREFIX = "payments.retry"

# (attempt_number_after_failure, ttl_ms) — classic exponential backoff.
# attempt 1 → wait 1s, attempt 2 → 2s, attempt 3 → 4s
RETRY_DELAYS_MS: dict[int, int] = {
    1: 1000,
    2: 2000,
    3: 4000,
}


def retry_queue_name(attempt: int) -> str:
    return f"{RETRY_QUEUE_PREFIX}.{attempt}"


def retry_routing_key(attempt: int) -> str:
    return f"retry.{attempt}"


# Header names
HEADER_RETRY_COUNT = "x-retry-count"
HEADER_IDEMPOTENCY_KEY = "x-idempotency-key"
