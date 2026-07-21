import structlog
from rakit_web.logging import bind_request_context, clear_request_context, redact_event


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
