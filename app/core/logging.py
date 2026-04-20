"""Structured-ish logging setup. Keeps stdlib logging, single-line output."""
import logging
import sys

_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class _ExtrasFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RECORD_ATTRS and not k.startswith("_")
        }
        if not extras:
            return base
        pairs = " ".join(f"{k}={v}" for k, v in extras.items())
        return f"{base} {pairs}"


def configure_logging(level: int = logging.INFO, json_logs: bool = False) -> None:
    if json_logs:
        # wire up python-json-logger if JSON logs become required
        raise NotImplementedError("JSON log format is not wired up")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _ExtrasFormatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for noisy in ("aio_pika", "aiormq", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
