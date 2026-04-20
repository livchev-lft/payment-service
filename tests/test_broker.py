from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest_asyncio
from faststream.rabbit import TestRabbitBroker

from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.broker.setup import get_broker
from app.infrastructure.broker.topology import (
    DLX_EXCHANGE,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
    MAIN_EXCHANGE,
    RK_DLQ,
    RK_NEW,
    retry_routing_key,
)
from app.workers import consumer as _consumer_module  # noqa: F401 — registers subscriber


def _find_publish_call(spy: AsyncMock, *, exchange: str, routing_key: str):
    for call in spy.await_args_list:
        kwargs = call.kwargs
        if kwargs.get("exchange") == exchange and kwargs.get("routing_key") == routing_key:
            return call
    raise AssertionError(
        f"no publish call to exchange={exchange!r} rk={routing_key!r}; "
        f"saw: {[(c.kwargs.get('exchange'), c.kwargs.get('routing_key')) for c in spy.await_args_list]}"
    )


@pytest_asyncio.fixture
async def test_broker():
    broker = get_broker()
    async with TestRabbitBroker(broker) as br:
        yield br


@pytest_asyncio.fixture
async def publish_spy(test_broker):
    with patch.object(
        test_broker._producer,
        "publish",
        new=AsyncMock(wraps=test_broker._producer.publish),
    ) as spy:
        yield spy


async def test_publisher_sends_new_payment_to_correct_queue(test_broker, publish_spy):
    publisher = Publisher(test_broker)
    await publisher.publish_new_payment(
        payload={"payment_id": "p1"}, idempotency_key="ik-1"
    )

    call = _find_publish_call(publish_spy, exchange=MAIN_EXCHANGE, routing_key=RK_NEW)
    headers = call.kwargs.get("headers") or {}
    assert headers.get(HEADER_RETRY_COUNT) == 0
    assert headers.get(HEADER_IDEMPOTENCY_KEY) == "ik-1"


async def test_publisher_sends_retry_with_incremented_header(test_broker, publish_spy):
    publisher = Publisher(test_broker)
    await publisher.publish_retry(
        payload={"payment_id": "p1"}, idempotency_key="ik-2", attempt=2
    )

    call = _find_publish_call(
        publish_spy, exchange=DLX_EXCHANGE, routing_key=retry_routing_key(2)
    )
    headers = call.kwargs.get("headers") or {}
    assert headers.get(HEADER_RETRY_COUNT) == 2
    assert headers.get(HEADER_IDEMPOTENCY_KEY) == "ik-2"


async def test_publisher_sends_to_dlq_with_reason_in_payload(
    test_broker, publish_spy
):
    publisher = Publisher(test_broker)
    await publisher.publish_dlq(
        payload={"payment_id": "p1"}, idempotency_key="ik-3", reason="boom"
    )

    call = _find_publish_call(publish_spy, exchange=DLX_EXCHANGE, routing_key=RK_DLQ)
    body = call.args[0] if call.args else call.kwargs.get("message")
    assert body["_dlq_reason"] == "boom"
    assert body["payment_id"] == "p1"


async def test_consumer_calls_processor_on_payment_message(test_broker):
    from app.workers import consumer

    with patch.object(consumer._processor, "process", new=AsyncMock()) as mock_process:
        await test_broker.publish(
            {"payment_id": "p-42", "webhook_url": "https://x"},
            exchange=MAIN_EXCHANGE,
            routing_key=RK_NEW,
            headers={HEADER_RETRY_COUNT: 0, HEADER_IDEMPOTENCY_KEY: "ik-consume"},
        )
        mock_process.assert_awaited_once()
        (payload,) = mock_process.await_args.args
        assert payload["payment_id"] == "p-42"


async def test_consumer_publishes_retry_on_exception(test_broker):
    from app.workers import consumer

    with (
        patch.object(
            consumer._processor,
            "process",
            new=AsyncMock(side_effect=RuntimeError("gateway timeout")),
        ),
        patch.object(consumer._publisher, "publish_retry", new=AsyncMock()) as retry,
        patch.object(consumer._publisher, "publish_dlq", new=AsyncMock()) as dlq,
    ):
        await test_broker.publish(
            {"payment_id": "p-err"},
            exchange=MAIN_EXCHANGE,
            routing_key=RK_NEW,
            headers={HEADER_RETRY_COUNT: 0, HEADER_IDEMPOTENCY_KEY: "ik-retry"},
        )
        retry.assert_awaited_once()
        assert retry.await_args.kwargs["attempt"] == 1
        assert retry.await_args.kwargs["idempotency_key"] == "ik-retry"
        dlq.assert_not_awaited()


async def test_consumer_publishes_dlq_after_max_attempts(test_broker):
    from app.workers import consumer

    max_attempts = consumer._settings.max_retry_attempts

    with (
        patch.object(
            consumer._processor,
            "process",
            new=AsyncMock(side_effect=RuntimeError("final failure")),
        ),
        patch.object(consumer._publisher, "publish_retry", new=AsyncMock()) as retry,
        patch.object(consumer._publisher, "publish_dlq", new=AsyncMock()) as dlq,
    ):
        await test_broker.publish(
            {"payment_id": "p-dlq"},
            exchange=MAIN_EXCHANGE,
            routing_key=RK_NEW,
            headers={
                HEADER_RETRY_COUNT: max_attempts,
                HEADER_IDEMPOTENCY_KEY: "ik-dlq",
            },
        )
        dlq.assert_awaited_once()
        assert dlq.await_args.kwargs["idempotency_key"] == "ik-dlq"
        assert "final failure" in dlq.await_args.kwargs["reason"]
        retry.assert_not_awaited()
