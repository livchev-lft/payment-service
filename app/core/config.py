"""Application configuration loaded from environment."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_key: str = Field(alias="API_KEY")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # PostgreSQL
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(alias="POSTGRES_DB")
    postgres_host: str = Field(alias="POSTGRES_HOST")
    postgres_port: int = Field(alias="POSTGRES_PORT")

    # RabbitMQ
    rabbitmq_host: str = Field(alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field(alias="RABBITMQ_USER")
    rabbitmq_password: str = Field(alias="RABBITMQ_PASSWORD")

    # Processing emulation
    processing_min_seconds: float = Field(default=2.0, alias="PROCESSING_MIN_SECONDS")
    processing_max_seconds: float = Field(default=5.0, alias="PROCESSING_MAX_SECONDS")
    processing_failure_rate: float = Field(default=0.1, alias="PROCESSING_FAILURE_RATE")

    # Retry
    max_retry_attempts: int = Field(default=3, alias="MAX_RETRY_ATTEMPTS")
    retry_base_delay_ms: int = Field(default=1000, alias="RETRY_BASE_DELAY_MS")

    # Outbox
    outbox_poll_interval_seconds: float = Field(default=1.0, alias="OUTBOX_POLL_INTERVAL_SECONDS")
    outbox_batch_size: int = Field(default=50, alias="OUTBOX_BATCH_SIZE")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbitmq_url(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
