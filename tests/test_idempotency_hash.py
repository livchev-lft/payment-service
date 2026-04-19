"""Pure-logic tests that run without Postgres/RabbitMQ.

For full integration coverage you'd spin up testcontainers — out of scope
for the test task. These cover the bits most likely to regress: the
request-hash canonicalization and the Pydantic schema validation.
"""
from decimal import Decimal

import pytest

from app.api.v1.schemas import PaymentCreateRequest
from app.api.v1.services import _hash_request
from app.domain.enums import Currency


def _req(**overrides):
    base = dict(
        amount=Decimal("199.99"),
        currency=Currency.RUB,
        description="Order #1",
        metadata={"order_id": "1"},
        webhook_url="https://example.com/hook",
    )
    base.update(overrides)
    return PaymentCreateRequest(**base)


def test_hash_is_stable_across_metadata_key_order():
    a = _req(metadata={"a": 1, "b": 2})
    b = _req(metadata={"b": 2, "a": 1})
    assert _hash_request(a) == _hash_request(b)


def test_hash_changes_on_amount():
    a = _req(amount=Decimal("100.00"))
    b = _req(amount=Decimal("100.01"))
    assert _hash_request(a) != _hash_request(b)


def test_hash_changes_on_webhook_url():
    a = _req(webhook_url="https://example.com/a")
    b = _req(webhook_url="https://example.com/b")
    assert _hash_request(a) != _hash_request(b)


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        _req(amount=Decimal("-1.00"))


def test_zero_amount_rejected():
    with pytest.raises(ValueError):
        _req(amount=Decimal("0"))


def test_oversized_metadata_rejected():
    huge = {"k": "x" * 10000}
    with pytest.raises(ValueError):
        _req(metadata=huge)
