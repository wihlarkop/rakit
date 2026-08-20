import io
import logging
import sys
from collections.abc import Mapping
from contextvars import Token
from http import HTTPStatus
from typing import Any, TextIO, cast

import structlog
from rakit_core.errors import ErrorCode, RakitError
from structlog.types import EventDict, Processor

#: Logger namespaces owned by Rakit that should be bridged into the
#: structured logging pipeline. Deliberately scoped -- never the root
#: logger -- so we don't hijack a host application's logging config.
#: Each entry is a package-root namespace; stdlib logging propagation
#: means any child logger (e.g. "rakit_web.lifecycle") is bridged too.
BRIDGED_LOGGER_NAMESPACES = ("rakit_core", "rakit_web", "rakit_server_uvicorn")


class _DynamicStderr(io.TextIOBase):
    """Proxy writes to whichever ``sys.stderr`` is active at emit time.

    Pytest and other hosts may replace standard streams after Rakit logging
    has been configured. Holding the original stream object would then leave
    structlog/stdlib handlers pointing at a closed capture stream.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(sys.stderr, name)


_DYNAMIC_STDERR = _DynamicStderr()


class _RakitBridgeHandler(logging.StreamHandler):
    """Marker subclass so repeated ``configure_logging()`` calls can find and
    replace the handler they previously attached, instead of accumulating
    duplicate handlers on the same logger.
    """


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


#: Beyond this nesting depth, redaction stops recursing and substitutes
#: ``_TRUNCATED_SENTINEL`` instead of the original (possibly still-deep,
#: possibly still secret-bearing) container. Guards against pathologically
#: deep -- but non-cyclic -- structures blowing the call stack.
_MAX_REDACT_DEPTH = 10

#: Substituted for a container that is already on the current recursion
#: ancestor path (i.e. a genuine self-reference), instead of returning the
#: original -- still-cyclic -- object. Returning the original would both
#: leave any secrets nested inside it fully reachable and hand a circular
#: object back to structlog's ``JSONRenderer``, which raises on it.
_CIRCULAR_SENTINEL = "[CIRCULAR]"

#: Substituted for a container at the ``_MAX_REDACT_DEPTH`` boundary,
#: instead of returning the original (unredacted-beyond-this-point)
#: container.
_TRUNCATED_SENTINEL = "[TRUNCATED]"


def redact_event(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Redact sensitive keys anywhere in ``event_dict``, not just its
    top-level keys.

    Recurses into nested ``Mapping`` and ``list``/``tuple`` values so that,
    e.g., ``logger.info("user.updated", user={"password": "..."})`` redacts
    the nested ``password`` too. Bounded by ``_MAX_REDACT_DEPTH`` and guarded
    against self-referential containers via ancestor-path tracking (``seen``
    holds the ids of containers on the current recursion path only, so
    unrelated reuse of the same object in sibling branches is never mistaken
    for a cycle). Fails closed: a detected cycle is replaced with
    ``_CIRCULAR_SENTINEL`` and a container past ``_MAX_REDACT_DEPTH`` is
    replaced with ``_TRUNCATED_SENTINEL`` -- the original object is never
    returned in either case, so no nested secret can leak back out and no
    circular object can reach (and crash) the renderer.
    """
    seen: frozenset[int] = frozenset({id(event_dict)})
    for key in tuple(event_dict):
        event_dict[key] = _redact_field(key, event_dict[key], depth=0, seen=seen)
    return event_dict


def _redact_field(key: object, value: Any, *, depth: int, seen: frozenset[int]) -> Any:
    if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    return _redact_value(value, depth=depth, seen=seen)


def _redact_value(value: Any, *, depth: int, seen: frozenset[int]) -> Any:
    if isinstance(value, Mapping | list | tuple):
        value_id = id(value)
        if value_id in seen:
            # Cycle detected: return a safe scalar sentinel, never the
            # original (still-cyclic) object. Checked before the depth
            # boundary since cycle detection is the more specific case.
            return _CIRCULAR_SENTINEL
        if depth >= _MAX_REDACT_DEPTH:
            # Depth boundary reached: return a safe scalar sentinel, never
            # the original (possibly still-deep, possibly secret-bearing)
            # container.
            return _TRUNCATED_SENTINEL
        child_seen = seen | {value_id}
        if isinstance(value, Mapping):
            return {
                k: _redact_field(k, v, depth=depth + 1, seen=child_seen) for k, v in value.items()
            }
        redacted_items = [_redact_value(item, depth=depth + 1, seen=child_seen) for item in value]
        return tuple(redacted_items) if isinstance(value, tuple) else redacted_items
    return value


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
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _DYNAMIC_STDERR)),
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
    for name in BRIDGED_LOGGER_NAMESPACES:
        _attach_bridge_handler(name, renderer=renderer, level=level)


def _attach_bridge_handler(name: str, *, renderer: Processor, level: int) -> None:
    """Attach (or replace) the structlog bridge handler on a single stdlib
    logger namespace.

    Shared by ``_configure_stdlib_bridge`` (for Rakit-owned namespaces) and
    ``bridge_additional_logger_namespace`` (for opt-in third-party
    namespaces) so there is exactly one implementation of "how to bridge a
    namespace into the structured pipeline." Never touches the root logger --
    an empty or whitespace-only ``name`` is rejected up front, since
    ``logging.getLogger("")`` resolves to the ROOT logger.
    """
    if not name or not name.strip():
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Logger namespace must be a non-empty, non-whitespace string.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={"name": repr(name)},
        )

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
    handler = _RakitBridgeHandler(_DYNAMIC_STDERR)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    std_logger = logging.getLogger(name)
    # configure_logging()/bridge_additional_logger_namespace() may run more
    # than once in the same process (e.g. across tests, or repeated ASGI
    # lifespans); drop any handler we previously attached so they don't
    # accumulate and duplicate output on each subsequent call.
    for existing in list(std_logger.handlers):
        if isinstance(existing, _RakitBridgeHandler):
            std_logger.removeHandler(existing)
    std_logger.addHandler(handler)
    std_logger.setLevel(level)
    std_logger.disabled = False
    std_logger.propagate = False
    for logger_name, existing_logger in logging.root.manager.loggerDict.items():
        if logger_name.startswith(f"{name}.") and isinstance(existing_logger, logging.Logger):
            existing_logger.disabled = False


def bridge_additional_logger_namespace(name: str, *, debug: bool) -> None:
    """Opt an additional (typically third-party) stdlib logger namespace into
    the same structured pipeline that Rakit's own namespaces use.

    Call this AFTER ``configure_logging()`` for namespaces Rakit does not own
    by default but that a specific deployment wants captured through the same
    structured, redacted pipeline -- for example Uvicorn's own ``"uvicorn"``/
    ``"uvicorn.error"``/``"uvicorn.access"`` loggers when running under the
    Uvicorn server adapter, or a future SQLAlchemy engine logger. This never
    touches the root logger and never bridges anything automatically -- the
    caller (e.g. ``rakit_server_uvicorn``'s own server-startup code, once it
    exists) decides which additional namespaces, if any, to opt in.
    """
    renderer = structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer()
    level = logging.DEBUG if debug else logging.INFO
    _attach_bridge_handler(name, renderer=renderer, level=level)


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
