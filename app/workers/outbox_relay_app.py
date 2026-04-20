"""Standalone entry point for the outbox relay process."""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.broker.publisher import Publisher
from app.infrastructure.broker.setup import declare_topology, get_broker
from app.infrastructure.db.session import close_engine
from app.workers.outbox_relay import OutboxRelay

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    settings = get_settings()
    broker = get_broker()
    await broker.connect()
    await declare_topology(broker)

    publisher = Publisher(broker)
    relay = OutboxRelay(settings, publisher)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    relay_task = asyncio.create_task(relay.run(), name="outbox-relay")
    logger.info("Outbox relay process started")

    await stop.wait()
    relay.stop()
    try:
        await asyncio.wait_for(relay_task, timeout=5)
    except asyncio.TimeoutError:
        relay_task.cancel()
    await broker.close()
    await close_engine()
    logger.info("Outbox relay process stopped")


if __name__ == "__main__":
    asyncio.run(main())
