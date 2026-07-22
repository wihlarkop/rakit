import logging

import pytest
import structlog
from rakit_core.errors import ErrorCode, RakitError
from rakit_web.logging import (
    _RakitBridgeHandler,
    bind_request_context,
    bridge_additional_logger_namespace,
    clear_request_context,
    configure_logging,
    redact_event,
    reset_request_context,
)


def test_sensitive_values_are_redacted() -> None:
    event = redact_event(
        object(),
        "info",
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


def test_rakit_web_stdlib_logging_bridges_into_structured_pipeline(capsys) -> None:
    """rakit_web's own stdlib loggers (e.g. rakit_web.lifecycle) must be bridged
    into the structured pipeline too, not just rakit_core.
    """
    configure_logging(debug=False)

    std_logger = logging.getLogger("rakit_web.lifecycle")
    std_logger.warning(
        "Health check failed for %s; continuing shutdown.",
        "some-resource",
        extra={"password": "secret123", "resource": "db-pool"},
    )

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "Health check failed" in output
    assert "warning" in output.lower()
    assert "db-pool" in output
    assert "secret123" not in output
    assert "[REDACTED]" in output


def test_bridge_additional_logger_namespace_routes_third_party_logger(capsys) -> None:
    """bridge_additional_logger_namespace() opts a third-party stdlib logger
    namespace into the same structured, redacted pipeline as Rakit-owned ones.
    """
    configure_logging(debug=False)
    bridge_additional_logger_namespace("some_third_party_lib", debug=False)

    std_logger = logging.getLogger("some_third_party_lib")
    std_logger.warning(
        "Connection pool exhausted for %s.",
        "primary",
        extra={"api_key": "secret456", "pool": "primary"},
    )

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "Connection pool exhausted" in output
    assert "warning" in output.lower()
    assert "primary" in output
    assert "secret456" not in output
    assert "[REDACTED]" in output


def test_root_logger_is_never_touched_by_bridging() -> None:
    """Neither configure_logging() nor bridge_additional_logger_namespace() may
    attach a handler to, or otherwise reconfigure, the root logger.
    """
    root_logger = logging.getLogger()
    original_propagate = root_logger.propagate
    original_level = root_logger.level

    configure_logging(debug=False)
    bridge_additional_logger_namespace("another_third_party_lib", debug=False)

    root_handlers = [h for h in root_logger.handlers if isinstance(h, _RakitBridgeHandler)]
    assert root_handlers == []
    assert root_logger.propagate == original_propagate
    assert root_logger.level == original_level


def test_configure_logging_does_not_duplicate_bridge_handlers_for_rakit_web() -> None:
    """Repeated configure_logging() calls must not accumulate handlers on the
    newly-bridged rakit_web namespace either.
    """
    configure_logging(debug=False)
    configure_logging(debug=False)
    configure_logging(debug=False)

    std_logger = logging.getLogger("rakit_web")
    rakit_handlers = [h for h in std_logger.handlers if isinstance(h, _RakitBridgeHandler)]
    assert len(rakit_handlers) == 1


def test_bridge_additional_logger_namespace_does_not_duplicate_handlers() -> None:
    """Repeated calls to bridge_additional_logger_namespace() for the same
    namespace must not accumulate duplicate handlers.
    """
    configure_logging(debug=False)
    bridge_additional_logger_namespace("repeated_third_party_lib", debug=False)
    bridge_additional_logger_namespace("repeated_third_party_lib", debug=False)
    bridge_additional_logger_namespace("repeated_third_party_lib", debug=False)

    std_logger = logging.getLogger("repeated_third_party_lib")
    rakit_handlers = [h for h in std_logger.handlers if isinstance(h, _RakitBridgeHandler)]
    assert len(rakit_handlers) == 1


def test_bridge_additional_logger_namespace_rejects_empty_name() -> None:
    """An empty namespace must never be forwarded to logging.getLogger(), which
    would resolve to the ROOT logger and silently attach the bridge handler
    there.
    """
    with pytest.raises(RakitError) as exc_info:
        bridge_additional_logger_namespace("", debug=False)
    assert exc_info.value.code == ErrorCode.CONFIG_INVALID.value


def test_bridge_additional_logger_namespace_rejects_whitespace_only_name() -> None:
    """A whitespace-only namespace is just as dangerous as an empty string --
    ``"   ".strip()`` is falsy, but the raw string is still truthy, so a naive
    ``if not name`` guard would miss it.
    """
    with pytest.raises(RakitError) as exc_info:
        bridge_additional_logger_namespace("   ", debug=False)
    assert exc_info.value.code == ErrorCode.CONFIG_INVALID.value


def test_bridge_additional_logger_namespace_blank_rejection_never_touches_root() -> None:
    """The guard must reject blank namespaces BEFORE any root-logger mutation
    happens -- not merely raise an exception for an unrelated reason after
    already touching root.
    """
    root_logger = logging.getLogger()
    original_propagate = root_logger.propagate
    original_level = root_logger.level
    original_filters = list(root_logger.filters)

    with pytest.raises(RakitError):
        bridge_additional_logger_namespace("", debug=False)
    with pytest.raises(RakitError):
        bridge_additional_logger_namespace("   ", debug=False)

    root_handlers = [h for h in root_logger.handlers if isinstance(h, _RakitBridgeHandler)]
    assert root_handlers == []
    assert root_logger.propagate == original_propagate
    assert root_logger.level == original_level
    assert list(root_logger.filters) == original_filters


def test_nested_sensitive_keys_are_redacted_through_real_pipeline(capsys) -> None:
    """Finding: redaction must recurse into nested Mapping/sequence values, not
    just event_dict's own top-level keys. Exercises the real configured
    structlog pipeline (JSON renderer + redact_event), not redact_event()
    called in isolation.
    """
    configure_logging(debug=False)

    logger = structlog.get_logger()
    logger.info(
        "user.updated",
        user={"id": 1, "password": "hunter2", "authorization": "Bearer abc123"},
    )

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "user.updated" in output
    assert "[REDACTED]" in output
    assert output.count("[REDACTED]") == 2
    assert "hunter2" not in output
    assert "Bearer abc123" not in output


def test_nested_non_sensitive_values_are_preserved() -> None:
    event = redact_event(
        object(),
        "info",
        {"event": "user.viewed", "user": {"id": 42, "name": "Ada"}},
    )
    assert event["user"]["id"] == 42
    assert event["user"]["name"] == "Ada"


def test_redact_event_handles_self_referential_dict_without_recursion_error() -> None:
    cyclic: dict = {"password": "secret"}
    cyclic["self"] = cyclic

    event = redact_event(object(), "info", {"data": cyclic})

    assert event["data"]["password"] == "[REDACTED]"
    # Fail closed: the cycle is replaced with a scalar sentinel, never the
    # original (still-cyclic) object.
    assert event["data"]["self"] == "[CIRCULAR]"


def test_redact_event_handles_self_referential_list_without_recursion_error() -> None:
    cyclic: list = []
    cyclic.append(cyclic)

    event = redact_event(object(), "info", {"data": cyclic})

    assert isinstance(event["data"], list)
    assert event["data"][0] == "[CIRCULAR]"


def test_redact_event_sibling_reuse_of_same_object_is_not_treated_as_cycle() -> None:
    """The ancestor-path (not global-seen) design must not mistake the SAME
    object appearing twice in unrelated branches for a cycle -- both
    branches must be fully, independently redacted.
    """
    shared = {"password": "secret", "id": 1}

    event = redact_event(object(), "info", {"branch_a": shared, "branch_b": shared})

    assert event["branch_a"]["password"] == "[REDACTED]"
    assert event["branch_a"]["id"] == 1
    assert event["branch_b"]["password"] == "[REDACTED]"
    assert event["branch_b"]["id"] == 1
    # Neither branch was mistaken for a cycle.
    assert event["branch_a"] != "[CIRCULAR]"
    assert event["branch_b"] != "[CIRCULAR]"


def test_redact_event_truncates_structure_deeper_than_max_depth() -> None:
    from rakit_web.logging import _MAX_REDACT_DEPTH

    deep: dict = {"password": "too-deep-secret"}
    for _ in range(_MAX_REDACT_DEPTH + 5):
        deep = {"nested": deep}

    event = redact_event(object(), "info", {"data": deep})

    # Serialize to a string to confirm the deep secret is nowhere present,
    # and the sentinel appears instead of the raw remaining structure.
    rendered = repr(event)
    assert "too-deep-secret" not in rendered
    assert "[TRUNCATED]" in rendered


def test_nested_secret_value_absent_from_rendered_output(capsys) -> None:
    configure_logging(debug=False)

    logger = structlog.get_logger()
    logger.info("user.updated", user={"id": 1, "password": "hunter2-secret-value"})

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "hunter2-secret-value" not in output
    assert "[REDACTED]" in output


def test_self_referential_dict_renders_through_real_json_pipeline(capsys) -> None:
    """A self-referential dict must not crash structlog's real JSONRenderer
    (which raises "Circular reference detected" on a still-cyclic object)
    and must render the "[CIRCULAR]" sentinel instead of the raw object.
    """
    configure_logging(debug=False)

    cyclic: dict = {}
    cyclic["self"] = cyclic

    logger = structlog.get_logger()
    # Must not raise.
    logger.info("cyclic.dict", data=cyclic)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "cyclic.dict" in output
    assert "[CIRCULAR]" in output


def test_self_referential_list_renders_through_real_json_pipeline(capsys) -> None:
    """A self-referential list must not crash structlog's real JSONRenderer
    and must render the "[CIRCULAR]" sentinel instead of the raw object.
    """
    configure_logging(debug=False)

    cyclic: list = []
    cyclic.append(cyclic)

    logger = structlog.get_logger()
    # Must not raise.
    logger.info("cyclic.list", data=cyclic)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "cyclic.list" in output
    assert "[CIRCULAR]" in output


def test_secret_in_cyclic_structure_absent_from_rendered_output(capsys) -> None:
    """A sensitive key alongside a cycle elsewhere in the same structure must
    still be redacted -- the cycle in one branch must not prevent redaction
    of a sibling secret.
    """
    configure_logging(debug=False)

    cyclic: dict = {"password": "hunter2"}
    cyclic["self"] = cyclic

    logger = structlog.get_logger()
    logger.info("cyclic.with_secret", data=cyclic)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "hunter2" not in output
    assert "[REDACTED]" in output
    assert "[CIRCULAR]" in output


def test_structure_deeper_than_max_depth_renders_through_real_pipeline(capsys) -> None:
    """A non-cyclic but pathologically deep structure must not crash the real
    JSONRenderer and must render the "[TRUNCATED]" sentinel instead of the
    raw remaining structure once the depth boundary is hit.
    """
    from rakit_web.logging import _MAX_REDACT_DEPTH

    configure_logging(debug=False)

    deep: dict = {"end": "unreachable-deep-value"}
    for _ in range(_MAX_REDACT_DEPTH + 5):
        deep = {"nested": deep}

    logger = structlog.get_logger()
    # Must not raise.
    logger.info("deep.structure", data=deep)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "deep.structure" in output
    assert "[TRUNCATED]" in output
