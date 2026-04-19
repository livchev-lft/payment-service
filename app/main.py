"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

from app.api.v1.routes import router as payments_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.broker.declare import declare_topology

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging()
    settings = get_settings()
    await declare_topology(settings.rabbitmq_url)
    logger.info("API starting up")
    yield
    logger.info("API shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Payments Service",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.include_router(payments_router)

    @app.get("/health", tags=["infra"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ARG001
        logger.exception("Unhandled error")
        return ORJSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc)},
        )

    return app


app = create_app()
