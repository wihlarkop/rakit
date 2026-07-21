import logging
import sys

import structlog

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "client_secret",
    "private_key",
    "secret_key",
}


def redact_event(_, __, event_dict):
    for key in tuple(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(*, debug: bool) -> None:
    renderer = structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_event,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def bind_request_context(
    *,
    request_id: str | None = None,
    operation_id: str | None = None,
    correlation_id: str | None = None,
    admin_id: str | None = None,
) -> None:
    values = {
        "request_id": request_id,
        "operation_id": operation_id,
        "correlation_id": correlation_id,
        "admin_id": admin_id,
    }
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
