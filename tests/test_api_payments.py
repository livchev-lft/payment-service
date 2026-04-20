from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OutboxStatus, PaymentStatus, WebhookDeliveryStatus
from app.infrastructure.db.models import OutboxEvent, Payment


def _payload(**overrides) -> dict:
    base = {
        "amount": "100.50",
        "currency": "USD",
        "description": "Test order",
        "metadata": {"order_id": "1"},
        "webhook_url": "https://example.com/hook",
    }
    base.update(overrides)
    return base


async def test_health_returns_ok(api_client):
    r = await api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_create_payment_without_api_key_returns_401(api_client):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 401


async def test_create_payment_with_wrong_api_key_returns_401(api_client):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers={"X-API-Key": "wrong", "Idempotency-Key": "k1"},
    )
    assert r.status_code == 401


async def test_create_payment_without_idempotency_key_returns_400(
    api_client, api_key_headers
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers=api_key_headers,
    )
    assert r.status_code == 400


async def test_create_payment_valid_returns_202_with_payment_id(
    api_client, api_key_headers
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers={**api_key_headers, "Idempotency-Key": "k-ok"},
    )
    assert r.status_code == 202
    body = r.json()
    assert "payment_id" in body
    uuid.UUID(body["payment_id"])


async def test_create_payment_response_contains_required_fields(
    api_client, api_key_headers
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers={**api_key_headers, "Idempotency-Key": "k-fields"},
    )
    assert r.status_code == 202
    body = r.json()
    assert set(body.keys()) >= {"payment_id", "status", "created_at"}
    assert body["status"] == PaymentStatus.PENDING.value
    assert body["created_at"]


async def test_create_payment_persists_row_with_pending_status(
    api_client, api_key_headers, db_session: AsyncSession
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(amount="42.00"),
        headers={**api_key_headers, "Idempotency-Key": "k-persist"},
    )
    payment_id = uuid.UUID(r.json()["payment_id"])

    row = await db_session.get(Payment, payment_id)
    assert row is not None
    assert row.status == PaymentStatus.PENDING
    assert row.amount == Decimal("42.00")
    assert row.idempotency_key == "k-persist"


async def test_create_payment_persists_outbox_event(
    api_client, api_key_headers, db_session: AsyncSession
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(),
        headers={**api_key_headers, "Idempotency-Key": "k-outbox"},
    )
    payment_id = uuid.UUID(r.json()["payment_id"])

    stmt = select(OutboxEvent).where(OutboxEvent.aggregate_id == payment_id)
    events = (await db_session.execute(stmt)).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "payment.created"
    assert event.status == OutboxStatus.PENDING
    assert event.payload["payment_id"] == str(payment_id)


async def test_idempotent_replay_returns_same_payment_id(
    api_client, api_key_headers
):
    headers = {**api_key_headers, "Idempotency-Key": "k-replay"}
    payload = _payload()

    r1 = await api_client.post("/api/v1/payments", json=payload, headers=headers)
    r2 = await api_client.post("/api/v1/payments", json=payload, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["payment_id"] == r2.json()["payment_id"]
    assert r2.headers.get("Idempotent-Replayed") == "true"
    assert r1.headers.get("Idempotent-Replayed") is None


async def test_idempotency_conflict_different_body_returns_409(
    api_client, api_key_headers
):
    headers = {**api_key_headers, "Idempotency-Key": "k-conflict"}

    r1 = await api_client.post(
        "/api/v1/payments", json=_payload(amount="100.00"), headers=headers
    )
    assert r1.status_code == 202

    r2 = await api_client.post(
        "/api/v1/payments", json=_payload(amount="999.00"), headers=headers
    )
    assert r2.status_code == 409


async def test_get_payment_returns_full_object(api_client, api_key_headers):
    create = await api_client.post(
        "/api/v1/payments",
        json=_payload(amount="77.77", currency="EUR", description="full get"),
        headers={**api_key_headers, "Idempotency-Key": "k-get"},
    )
    payment_id = create.json()["payment_id"]

    r = await api_client.get(f"/api/v1/payments/{payment_id}", headers=api_key_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == payment_id
    assert body["idempotency_key"] == "k-get"
    assert body["amount"] == "77.77"
    assert body["currency"] == "EUR"
    assert body["description"] == "full get"
    assert body["status"] == PaymentStatus.PENDING.value
    assert body["webhook_delivery_status"] == WebhookDeliveryStatus.PENDING.value
    assert body["processed_at"] is None
    assert body["webhook_delivered_at"] is None
    assert body["webhook_failure_reason"] is None


async def test_get_payment_not_found_returns_404(api_client, api_key_headers):
    missing = uuid.uuid4()
    r = await api_client.get(f"/api/v1/payments/{missing}", headers=api_key_headers)
    assert r.status_code == 404


async def test_get_payment_without_api_key_returns_401(api_client):
    r = await api_client.get(f"/api/v1/payments/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.parametrize("bad_amount", ["-1.00", "0", "0.00"])
async def test_create_payment_rejects_negative_amount(
    api_client, api_key_headers, bad_amount
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(amount=bad_amount),
        headers={**api_key_headers, "Idempotency-Key": f"k-bad-{bad_amount}"},
    )
    assert r.status_code in (400, 422)


async def test_create_payment_rejects_unsupported_currency(
    api_client, api_key_headers
):
    r = await api_client.post(
        "/api/v1/payments",
        json=_payload(currency="XYZ"),
        headers={**api_key_headers, "Idempotency-Key": "k-bad-ccy"},
    )
    assert r.status_code in (400, 422)
