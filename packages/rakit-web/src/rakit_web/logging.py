import logging
import sys
from collections.abc import Mapping
from contextvars import Token
from typing import Any

import structlog
from structlog.types import EventDict, Processor

#: Logger namespaces owned by Rakit that should be bridged into the
#: structured logging pipeline. Deliberately scoped -- never the root
#: logger -- so we don't hijack a host application's logging config.
BRIDGED_LOGGER_NAMESPACES = ("rakit_core",)


class _RakitBridgeHandler(logging.StreamHandler):
    """Marker subclass so repeated ``configure_logging()`` calls can find and
    replace the handler they previously attached, instead of accumulating
    duplicate handlers on the same logger."""


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


def redact_event(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    for key in tuple(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(*, debug: bool) -> None:
    renderer = structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer()
    level = logging.DEBUG if debug else logging.INFO
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_event,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    _configure_stdlib_bridge(renderer=renderer, level=level)


def _configure_stdlib_bridge(*, renderer: Processor, level: int) -> None:
    """Bridge Rakit-owned stdlib logger namespaces into the structlog pipeline.

    Attaches a handler formatted with ``structlog.stdlib.ProcessorFormatter``
    to a small, explicit list of Rakit-owned loggers (never the root logger),
    so records from ``logging.getLogger("rakit_core...")`` etc. flow through
    the same renderer and redaction as structlog-native logs. Each targeted
    logger has ``propagate`` disabled so the host application's root logger
    handlers (if any) don't also emit the same record a second time.
    """
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            redact_event,
            renderer,
        ],
    )
    handler = _RakitBridgeHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    for name in BRIDGED_LOGGER_NAMESPACES:
        std_logger = logging.getLogger(name)
        # configure_logging() may run more than once in the same process
        # (e.g. across tests, or repeated ASGI lifespans); drop any handler
        # we previously attached so they don't accumulate and duplicate
        # output on each subsequent call.
        for existing in list(std_logger.handlers):
            if isinstance(existing, _RakitBridgeHandler):
                std_logger.removeHandler(existing)
        std_logger.addHandler(handler)
        std_logger.setLevel(level)
        std_logger.propagate = False


def bind_request_context(
    *,
    request_id: str | None = None,
    operation_id: str | None = None,
    correlation_id: str | None = None,
    admin_id: str | None = None,
) -> Mapping[str, Token]:
    values = {
        "request_id": request_id,
        "operation_id": operation_id,
        "correlation_id": correlation_id,
        "admin_id": admin_id,
    }
    return structlog.contextvars.bind_contextvars(
        **{k: v for k, v in values.items() if v is not None}
    )


def reset_request_context(tokens: Mapping[str, Token]) -> None:
    """Reset exactly the contextvars bound by ``bind_request_context``.

    Uses structlog's token-based reset API so only the keys Rakit itself
    bound are restored to their prior value -- any other structlog context
    a host application bound before Rakit's middleware ran (e.g. a FastAPI
    app mounting Rakit as a sub-application) is left completely untouched.
    """
    structlog.contextvars.reset_contextvars(**tokens)


def clear_request_context() -> None:
    """Unconditionally clear ALL bound structlog contextvars.

    This is a blunt, "clear everything" utility. It is destructive to any
    context a host application may have bound and is NOT used by
    ``RequestContextMiddleware`` (which uses the token-based
    ``bind_request_context``/``reset_request_context`` pair instead). Kept
    for callers that genuinely want a full reset (e.g. test teardown).
    """
    structlog.contextvars.clear_contextvars()
