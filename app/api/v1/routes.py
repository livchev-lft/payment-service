"""HTTP routes for payments."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.v1.deps import SessionDep, require_api_key, require_idempotency_key
from app.api.v1.schemas import (
    ErrorResponse,
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentResponse,
)
from app.api.v1.services import PaymentService
from app.domain.exceptions import IdempotencyConflictError

router = APIRouter(
    prefix="/api/v1",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    },
)


@router.post(
    "/payments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreateResponse,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Idempotency key conflict"},
    },
)
async def create_payment(
    payload: PaymentCreateRequest,
    session: SessionDep,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    response: Response,
) -> PaymentCreateResponse:
    service = PaymentService(session)
    try:
        payment, created = await service.create(payload, idempotency_key)
    except IdempotencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    # Idempotent replay → 200 OK feels more honest than 202 because we're not
    # accepting new work. But the spec says 202, so we keep 202 for both and
    # just signal via a custom header.
    if not created:
        response.headers["Idempotent-Replayed"] = "true"

    return PaymentCreateResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_payment(payment_id: uuid.UUID, session: SessionDep) -> PaymentResponse:
    service = PaymentService(session)
    payment = await service.get(payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="payment not found"
        )
    return PaymentResponse.model_validate(payment)
