# Payments Service

Асинхронный платёжный сервис. Принимает запросы на оплату, обрабатывает их
через эмуляцию платёжного шлюза, уведомляет клиента через webhook.

## Стек

- Python 3.12
- FastAPI, Pydantic v2
- SQLAlchemy 2.0 (async)
- PostgreSQL 16
- RabbitMQ 3.13, FastStream
- Alembic
- Docker Compose

## Запуск

```bash
cp .env.example .env
docker compose up --build -d
```

Поднимаются postgres, rabbitmq, migrator (one-shot), api,
payment-consumer, outbox-relay, webhook-worker.

После старта:

- API — http://localhost:8000
- Swagger — http://localhost:8000/docs
- RabbitMQ management — http://localhost:15672 (guest/guest)

## API

Полная документация — в Swagger UI: http://localhost:8000/docs.

Аутентификация через заголовок `X-API-Key`. Для создания платежа
дополнительно требуется `Idempotency-Key`.

## Конфигурация

Все параметры — через переменные окружения. Шаблон в `.env.example`.
Важные:

- `API_KEY` — статический ключ для X-API-Key
- `PROCESSING_FAILURE_RATE` — вероятность ошибки при эмуляции (0.1 по умолчанию)
- `MAX_RETRY_ATTEMPTS` — максимум попыток до DLQ
- `RETRY_BASE_DELAY_MS` — базовая задержка retry, задержки умножаются на 1/2/4
