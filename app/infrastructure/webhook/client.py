"""HTTP webhook delivery — single attempt.

Retry is owned by the webhooks broker chain; this client raises on any
non-2xx / network error and lets the worker decide whether to republish.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Raised when a single webhook delivery attempt fails."""


class WebhookClient:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout = timeout_seconds

    async def deliver_once(self, url: str, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            raise WebhookDeliveryError(f"network: {e}") from e

        if response.status_code >= 400:
            raise WebhookDeliveryError(
                f"webhook returned {response.status_code}: {response.text[:200]}"
            )
