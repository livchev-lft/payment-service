"""Domain-level exceptions. Mapped to HTTP in the API layer."""


class DomainError(Exception):
    """Base for domain errors."""


class PaymentNotFoundError(DomainError):
    pass


class IdempotencyConflictError(DomainError):
    """Same idempotency key was used with a different request body."""
