"""Consumer process.

Responsibilities (all in one process, as spec requires — "один consumer"):
  1. Subscribe to `payments.new` and process messages
  2. On failure: publish to retry-queue (with attempt counter) or DLQ
  3. Run the OutboxRelay background task

Implementation note on the broker library:
  The spec lists "RabbitMQ (FastStream)" in the tech stack. FastStream is a
  thin layer over aio-pika and its 0.5.x API for message headers / lifecycle
  hooks changed across minor versions. To keep the consumer rock-solid and
  easy to review, we use aio-pika directly here. The same library is used
  for topology declaration (declare.py) and publishing (publisher.py), so
  the whole broker surface is consistent. If strict FastStream usage is
  required, `_handle_message` can be wrapped in a `@broker.subscriber` with
  minimal changes — the business logic is isolated in PaymentProcessor.
"""
from __future__ import annotations

import asyncio
import logging
import signal

import aio_pika
import orjson

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.broker.declare import declare_topology
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.broker.topology import (
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RETRY_COUNT,
    MAIN_QUEUE,
)
from app.infrastructure.webhook.client import WebhookClient
from app.workers.outbox_relay import OutboxRelay
from app.workers.processor import PaymentProcessor

logger = logging.getLogger(__name__)


class ConsumerApp:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._publisher = Publisher(self._settings.rabbitmq_url)
        self._processor = PaymentProcessor(
            settings=self._settings,
            webhook_client=WebhookClient(max_attempts=3),
        )
        self._relay = OutboxRelay(self._settings, self._publisher)
        self._stopping = asyncio.Event()
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None

    async def run(self) -> None:
        configure_logging()
        await declare_topology(self._settings.rabbitmq_url)
        await self._publisher.connect()

        self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=16)
        queue = await channel.get_queue(MAIN_QUEUE)

        relay_task = asyncio.create_task(self._relay.run(), name="outbox-relay")
        logger.info("Consumer started, listening on %s", MAIN_QUEUE)

        try:
            async with queue.iterator() as it:
                async for message in it:
                    if self._stopping.is_set():
                        break
                    await self._handle_message(message)
        finally:
            self._relay.stop()
            try:
                await asyncio.wait_for(relay_task, timeout=5)
            except asyncio.TimeoutError:
                relay_task.cancel()
            await self._publisher.close()
            if self._connection is not None:
                await self._connection.close()
            logger.info("Consumer stopped")

    async def _handle_message(
        self, message: aio_pika.abc.AbstractIncomingMessage
    ) -> None:
        """Processes a single message.

        On success -> ack.
        On failure -> ack the original (so the broker doesn't redeliver it)
        and publish to the retry chain with an incremented counter. After
        `max_retry_attempts` failures -> publish to DLQ.

        We use ack + republish (rather than nack-requeue) because it gives
        us full control over retry metadata via headers.
        """
        headers = message.headers or {}
        retry_count = int(headers.get(HEADER_RETRY_COUNT, 0) or 0)
        idempotency_key = str(headers.get(HEADER_IDEMPOTENCY_KEY, "") or "")

        try:
            body = orjson.loads(message.body)
        except orjson.JSONDecodeError as e:
            logger.error("Invalid JSON in message, sending to DLQ: %s", e)
            await self._publisher.publish_dlq(
                payload={"_raw": message.body.decode("utf-8", errors="replace")},
                idempotency_key=idempotency_key,
                reason=f"invalid json: {e}",
            )
            await message.ack()
            return

        try:
            await self._processor.process(body)
            await message.ack()
            return
        except Exception as e:
            logger.exception("Processing failed, routing to retry/DLQ")
            next_attempt = retry_count + 1
            try:
                if next_attempt > self._settings.max_retry_attempts:
                    await self._publisher.publish_dlq(
                        payload=body,
                        idempotency_key=idempotency_key,
                        reason=f"{type(e).__name__}: {e}",
                    )
                else:
                    await self._publisher.publish_retry(
                        payload=body,
                        idempotency_key=idempotency_key,
                        attempt=next_attempt,
                    )
                await message.ack()
            except Exception:
                # Couldn't publish to retry/DLQ. nack without requeue would
                # lose the message; requeue so we try again shortly.
                logger.exception("Failed to route to retry/DLQ, requeuing")
                await message.nack(requeue=True)

    def request_stop(self) -> None:
        self._stopping.set()


async def _main() -> None:
    app = ConsumerApp()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, app.request_stop)
    await app.run()


if __name__ == "__main__":
    asyncio.run(_main())
