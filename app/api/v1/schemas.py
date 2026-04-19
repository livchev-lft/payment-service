"""Pydantic schemas for HTTP request/response."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.domain.enums import Currency, PaymentStatus


class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    description: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Keep metadata sane — prevents pathological payloads.
        import json

        if len(json.dumps(v)) > 8192:
            raise ValueError("metadata too large (max 8KB)")
        return v


class PaymentCreateResponse(BaseModel):
    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    currency: str
    description: str
    metadata: dict[str, Any] = Field(alias="payment_metadata")
    webhook_url: str
    status: PaymentStatus
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
