from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_RELATIONSHIPS,
    PERSISTENCE_WRITE,
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
    TRANSACTIONS_ROOT_UOW,
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.conformance import (
    CapabilityBehaviorCheck,
    CapabilityConformanceSpec,
    build_conformance_spec_registry,
)
from rakit_core.schema import PartialInputSchemaAdapter, SchemaAdapter, SchemaValidationError


@runtime_checkable
class PersistenceConformanceHarness(Protocol):
    """Behavior-only proof seam for persistence capability implementations.

    Implementations must exercise their real adapter components. These methods
    describe Rakit semantics rather than any ORM-specific API.
    """

    async def assert_read_semantics(self) -> None:
        """Prove list/detail identity, query, ordering, pagination, and portable errors."""
        ...

    async def assert_write_semantics(self) -> None:
        """Prove create/update/delete persistence with explicit mutation semantics."""
        ...

    async def assert_relationship_semantics(self) -> None:
        """Prove relationship reads/mutations preserve neutral relationship semantics."""
        ...

    async def assert_root_uow_semantics(self) -> None:
        """Prove one root unit of work owns commit/rollback for a mutation boundary."""
        ...

    async def assert_atomic_optimistic_semantics(self) -> None:
        """Prove optimistic checks and writes are atomic under the owning transaction."""
        ...


@dataclass(frozen=True, slots=True)
class SchemaConformanceHarness:
    adapter: SchemaAdapter
    schema: type[object]
    expected_field_names: tuple[str, ...]
    valid_input: Mapping[str, object]
    invalid_input: Mapping[str, object]
    serializable_input: object
    expected_serialized_output: object
    partial_input: Mapping[str, object]
    expected_partial_output: Mapping[str, object]


ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WebConformanceHarness:
    app: ASGIApp
    route_path: str
    expected_route_status: int
    expected_route_body: bytes
    streaming_path: str
    expected_stream_status: int = 200


async def _persistence_read(harness: object) -> None:
    assert isinstance(harness, PersistenceConformanceHarness)
    await harness.assert_read_semantics()


async def _persistence_write(harness: object) -> None:
    assert isinstance(harness, PersistenceConformanceHarness)
    await harness.assert_write_semantics()


async def _persistence_relationships(harness: object) -> None:
    assert isinstance(harness, PersistenceConformanceHarness)
    await harness.assert_relationship_semantics()


async def _transactions_root_uow(harness: object) -> None:
    assert isinstance(harness, PersistenceConformanceHarness)
    await harness.assert_root_uow_semantics()


async def _concurrency_atomic_optimistic(harness: object) -> None:
    assert isinstance(harness, PersistenceConformanceHarness)
    await harness.assert_atomic_optimistic_semantics()


async def _schema_field_introspection(harness: object) -> None:
    assert isinstance(harness, SchemaConformanceHarness)
    assert harness.adapter.field_names(harness.schema) == harness.expected_field_names
    assert tuple(field.name for field in harness.adapter.fields(harness.schema)) == (
        harness.expected_field_names
    )


async def _schema_input_validation(harness: object) -> None:
    assert isinstance(harness, SchemaConformanceHarness)
    harness.adapter.validate_input(harness.schema, harness.valid_input)
    try:
        harness.adapter.validate_input(harness.schema, harness.invalid_input)
    except SchemaValidationError as exc:
        assert exc.issues, "invalid input must expose at least one neutral validation issue"
    else:
        raise AssertionError("invalid input must raise SchemaValidationError")


async def _schema_output_serialization(harness: object) -> None:
    assert isinstance(harness, SchemaConformanceHarness)
    assert (
        harness.adapter.serialize_output(harness.schema, harness.serializable_input)
        == harness.expected_serialized_output
    )


async def _schema_partial_update(harness: object) -> None:
    assert isinstance(harness, SchemaConformanceHarness)
    assert isinstance(harness.adapter, PartialInputSchemaAdapter)
    assert dict(
        harness.adapter.validate_partial_input(harness.schema, harness.partial_input)
    ) == dict(harness.expected_partial_output)


async def _asgi_exchange(app: ASGIApp, path: str) -> tuple[dict[str, Any], ...]:
    sent: list[dict[str, Any]] = []
    received_request = False

    async def receive() -> dict[str, Any]:
        nonlocal received_request
        if not received_request:
            received_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(dict(message))

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": (),
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return tuple(sent)


def _response_status(messages: tuple[dict[str, Any], ...]) -> int:
    starts = [message for message in messages if message.get("type") == "http.response.start"]
    assert len(starts) == 1, "ASGI HTTP response must emit exactly one response start"
    return int(starts[0]["status"])


def _response_body(messages: tuple[dict[str, Any], ...]) -> bytes:
    return b"".join(
        bytes(message.get("body", b""))
        for message in messages
        if message.get("type") == "http.response.body"
    )


async def _web_asgi(harness: object) -> None:
    assert isinstance(harness, WebConformanceHarness)
    messages = await _asgi_exchange(harness.app, harness.route_path)
    _response_status(messages)
    assert any(message.get("type") == "http.response.body" for message in messages)


async def _web_http_routing(harness: object) -> None:
    assert isinstance(harness, WebConformanceHarness)
    messages = await _asgi_exchange(harness.app, harness.route_path)
    assert _response_status(messages) == harness.expected_route_status
    assert _response_body(messages) == harness.expected_route_body


async def _web_streaming_response(harness: object) -> None:
    assert isinstance(harness, WebConformanceHarness)
    messages = await _asgi_exchange(harness.app, harness.streaming_path)
    assert _response_status(messages) == harness.expected_stream_status
    bodies = [message for message in messages if message.get("type") == "http.response.body"]
    assert bodies, "streaming response must emit response body messages"
    assert any(message.get("more_body") is True for message in bodies), (
        "streaming response must expose at least one non-terminal body event"
    )
    assert bodies[-1].get("more_body", False) is False, (
        "streaming response must terminate with more_body false"
    )


CANONICAL_CONFORMANCE_SPECS: tuple[CapabilityConformanceSpec, ...] = (
    CapabilityConformanceSpec(
        PERSISTENCE_READ,
        1,
        (CapabilityBehaviorCheck("persistence.read.behavior", _persistence_read),),
    ),
    CapabilityConformanceSpec(
        PERSISTENCE_WRITE,
        1,
        (CapabilityBehaviorCheck("persistence.write.behavior", _persistence_write),),
    ),
    CapabilityConformanceSpec(
        PERSISTENCE_RELATIONSHIPS,
        1,
        (
            CapabilityBehaviorCheck(
                "persistence.relationships.behavior", _persistence_relationships
            ),
        ),
    ),
    CapabilityConformanceSpec(
        TRANSACTIONS_ROOT_UOW,
        1,
        (CapabilityBehaviorCheck("transactions.root-uow.behavior", _transactions_root_uow),),
    ),
    CapabilityConformanceSpec(
        CONCURRENCY_ATOMIC_OPTIMISTIC,
        1,
        (
            CapabilityBehaviorCheck(
                "concurrency.atomic-optimistic.behavior",
                _concurrency_atomic_optimistic,
            ),
        ),
    ),
    CapabilityConformanceSpec(
        SCHEMA_FIELD_INTROSPECTION,
        1,
        (
            CapabilityBehaviorCheck(
                "schema.field-introspection.behavior", _schema_field_introspection
            ),
        ),
    ),
    CapabilityConformanceSpec(
        SCHEMA_INPUT_VALIDATION,
        1,
        (CapabilityBehaviorCheck("schema.input-validation.behavior", _schema_input_validation),),
    ),
    CapabilityConformanceSpec(
        SCHEMA_OUTPUT_SERIALIZATION,
        1,
        (
            CapabilityBehaviorCheck(
                "schema.output-serialization.behavior", _schema_output_serialization
            ),
        ),
    ),
    CapabilityConformanceSpec(
        SCHEMA_PARTIAL_UPDATE,
        1,
        (CapabilityBehaviorCheck("schema.partial-update.behavior", _schema_partial_update),),
    ),
    CapabilityConformanceSpec(
        WEB_ASGI,
        1,
        (CapabilityBehaviorCheck("web.asgi.behavior", _web_asgi),),
    ),
    CapabilityConformanceSpec(
        WEB_HTTP_ROUTING,
        1,
        (CapabilityBehaviorCheck("web.http-routing.behavior", _web_http_routing),),
    ),
    CapabilityConformanceSpec(
        WEB_STREAMING_RESPONSE,
        1,
        (CapabilityBehaviorCheck("web.streaming-response.behavior", _web_streaming_response),),
    ),
)

CANONICAL_CONFORMANCE_SPEC_REGISTRY = build_conformance_spec_registry(CANONICAL_CONFORMANCE_SPECS)


__all__ = [
    "CANONICAL_CONFORMANCE_SPECS",
    "CANONICAL_CONFORMANCE_SPEC_REGISTRY",
    "PersistenceConformanceHarness",
    "SchemaConformanceHarness",
    "WebConformanceHarness",
]
