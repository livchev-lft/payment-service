"""ORM models for payments and outbox.

Notes:
- `Payment.idempotency_key` is UNIQUE; it's the primary defense against duplicate charges.
- `Payment.request_hash` stores a hash of the request body so that a second request with
  the same idempotency key but different body can be rejected with 409.
- `Outbox` keeps a FIFO of events to be published. The outbox relay picks them up with
  `SELECT ... FOR UPDATE SKIP LOCKED` so multiple relays can run safely.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import OutboxStatus, PaymentStatus, WebhookDeliveryStatus
from app.infrastructure.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payment_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[PaymentStatus] = mapped_column(
        String(16), nullable=False, default=PaymentStatus.PENDING
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    webhook_delivery_status: Mapped[WebhookDeliveryStatus] = mapped_column(
        String(16), nullable=False, default=WebhookDeliveryStatus.PENDING
    )
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        String(16), nullable=False, default=OutboxStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_outbox_status_created_at", "status", "created_at"),
    )
