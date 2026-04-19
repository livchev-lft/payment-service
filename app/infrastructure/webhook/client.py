"""HTTP webhook delivery with in-process retry.

Separate from the message-level retry in the consumer: this handles transient
HTTP failures (5xx, network errors, timeouts). A 4xx from the receiver is
treated as non-retryable — the caller considers delivery failed and moves on.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Raised after all retries are exhausted or on a non-retryable status."""


class _RetryableHTTPError(Exception):
    """Internal marker for retry."""


class WebhookClient:
    def __init__(self, timeout_seconds: float = 5.0, max_attempts: int = 3) -> None:
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts

    async def deliver(self, url: str, payload: dict[str, Any]) -> None:
        """Deliver payload to url. Raises WebhookDeliveryError on final failure."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                retry=retry_if_exception_type(_RetryableHTTPError),
                reraise=True,
            ):
                with attempt:
                    await self._send_once(url, payload)
        except _RetryableHTTPError as e:
            raise WebhookDeliveryError(str(e)) from e
        except WebhookDeliveryError:
            raise
        except Exception as e:  # pragma: no cover — defensive
            raise WebhookDeliveryError(f"unexpected: {e}") from e

    async def _send_once(self, url: str, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            raise _RetryableHTTPError(f"network: {e}") from e

        if 500 <= response.status_code < 600:
            raise _RetryableHTTPError(f"server error {response.status_code}")
        if response.status_code >= 400:
            # Non-retryable: receiver rejected us. Log and give up.
            raise WebhookDeliveryError(
                f"webhook rejected with {response.status_code}: {response.text[:200]}"
            )
