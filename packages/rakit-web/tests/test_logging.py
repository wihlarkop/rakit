import logging

import structlog
from rakit_web.logging import (
    _RakitBridgeHandler,
    bind_request_context,
    clear_request_context,
    configure_logging,
    redact_event,
    reset_request_context,
)


def test_sensitive_values_are_redacted() -> None:
    event = redact_event(
        None,
        None,
        {
            "event": "auth.login",
            "password": "secret",
            "authorization": "Bearer token",
            "user_id": "u-1",
        },
    )
    assert event["password"] == "[REDACTED]"
    assert event["authorization"] == "[REDACTED]"
    assert event["user_id"] == "u-1"


def test_bind_and_clear_request_context() -> None:
    clear_request_context()
    try:
        bind_request_context(
            request_id="req-1",
            operation_id="op-1",
            correlation_id="corr-1",
            admin_id="admin-1",
        )
        bound = structlog.contextvars.get_contextvars()
        assert bound["request_id"] == "req-1"
        assert bound["operation_id"] == "op-1"
        assert bound["correlation_id"] == "corr-1"
        assert bound["admin_id"] == "admin-1"
    finally:
        clear_request_context()

    assert structlog.contextvars.get_contextvars() == {}


async def test_request_context_reaches_log_output_during_real_request(client) -> None:
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        response = await client.get("/")

    assert response.status_code == 200
    request_logs = [entry for entry in captured if "request_id" in entry]
    assert request_logs, f"no log entries carried request_id: {captured}"
    for entry in request_logs:
        assert isinstance(entry["request_id"], str)
        assert entry["request_id"]
        assert entry["admin_id"] == "operations"


def test_reset_request_context_restores_prior_value_for_bound_keys() -> None:
    """bind/reset round-trip must restore the exact prior value of any key it touches."""
    clear_request_context()
    try:
        structlog.contextvars.bind_contextvars(request_id="outer-value")
        tokens = bind_request_context(request_id="inner-value", admin_id="admin-1")
        assert structlog.contextvars.get_contextvars()["request_id"] == "inner-value"

        reset_request_context(tokens)

        bound = structlog.contextvars.get_contextvars()
        assert bound["request_id"] == "outer-value"
        assert "admin_id" not in bound
    finally:
        clear_request_context()


async def test_request_context_does_not_clobber_host_application_context(client) -> None:
    """Finding 5: RequestContextMiddleware must not blanket-clear host structlog context.

    Simulates a host application (e.g. FastAPI mounting Rakit as a
    sub-application) that has already bound its own structlog context before
    Rakit's RequestContextMiddleware ever runs. That host context must
    survive a Rakit request untouched, while Rakit's own request-scoped
    values (request_id, admin_id) must not leak into the ambient context
    after the request completes.
    """
    structlog.contextvars.bind_contextvars(tenant="acme")
    try:
        # 1. Host context exists before the Rakit request.
        assert structlog.contextvars.get_contextvars()["tenant"] == "acme"

        # 2. Rakit's own request context exists during the request.
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars]
        ) as captured:
            response = await client.get("/")
        assert response.status_code == 200
        request_logs = [entry for entry in captured if "request_id" in entry]
        assert request_logs, f"no log entries carried request_id: {captured}"
        for entry in request_logs:
            assert entry["admin_id"] == "operations"
            # Host context was visible alongside Rakit's during the request too.
            assert entry["tenant"] == "acme"

        # 3. Host context remains intact and unmodified after the request.
        bound_after = structlog.contextvars.get_contextvars()
        assert bound_after["tenant"] == "acme"

        # 4. Rakit-only values do not leak into ambient context afterwards.
        assert "request_id" not in bound_after
        assert "admin_id" not in bound_after
    finally:
        structlog.contextvars.unbind_contextvars("tenant")


def test_stdlib_logging_bridges_into_structured_pipeline(capsys) -> None:
    """Finding 8: stdlib logging under rakit_core.* must reach the configured
    structlog pipeline (same renderer + redaction), not Python's unconfigured
    default output.
    """
    configure_logging(debug=False)

    std_logger = logging.getLogger("rakit_core.events")
    std_logger.warning(
        "Post-commit event handler failed for event %s; continuing.",
        "SomeEvent",
        extra={"password": "secret123", "event_id": "evt-1"},
    )

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "Post-commit event handler failed" in output
    assert "warning" in output.lower()
    # Non-sensitive extra field surfaces in the rendered output.
    assert "evt-1" in output
    # Sensitive extra field is redacted.
    assert "secret123" not in output
    assert "[REDACTED]" in output


def test_configure_logging_does_not_duplicate_stdlib_bridge_handlers() -> None:
    """configure_logging() may run more than once in the same process (e.g.
    across tests, or repeated ASGI lifespans); repeated calls must not
    accumulate handlers on the bridged logger and cause duplicate output.
    """
    configure_logging(debug=False)
    configure_logging(debug=False)
    configure_logging(debug=False)

    std_logger = logging.getLogger("rakit_core")
    rakit_handlers = [h for h in std_logger.handlers if isinstance(h, _RakitBridgeHandler)]
    assert len(rakit_handlers) == 1
