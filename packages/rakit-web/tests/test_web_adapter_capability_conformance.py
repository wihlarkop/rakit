from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import BaseModel
from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
    WEB_ASGI,
    WEB_HTTP_ROUTING,
    WEB_STREAMING_RESPONSE,
)
from rakit_core.conformance import conformance_matrix_rows, run_integration_conformance
from rakit_core.testing.capability_conformance import (
    CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    SchemaConformanceHarness,
    WebConformanceHarness,
)
from rakit_web.discovery import PYDANTIC_INTEGRATION, STARLETTE_INTEGRATION
from rakit_web.schema import PydanticSchemaAdapter
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route


class ContactSchema(BaseModel):
    name: str = "Unknown"
    age: int = 0
    nickname: str | None = None


async def _plain_route(_request: object) -> PlainTextResponse:
    return PlainTextResponse("d1-ok")


async def _stream_chunks():
    yield b"chunk-1"
    yield b"chunk-2"


async def _stream_route(_request: object) -> StreamingResponse:
    return StreamingResponse(_stream_chunks())


@pytest.mark.anyio
async def test_pydantic_advertised_capabilities_conform_to_v1_contracts() -> None:
    harness = SchemaConformanceHarness(
        adapter=PydanticSchemaAdapter(),
        schema=ContactSchema,
        expected_field_names=("name", "age", "nickname"),
        valid_input={"name": "Ada", "age": 36, "nickname": None},
        invalid_input={"name": "Ada", "age": "not-an-integer"},
        serializable_input={"name": "Ada", "age": 36, "nickname": "Enchantress"},
        expected_serialized_output={
            "name": "Ada",
            "age": 36,
            "nickname": "Enchantress",
        },
        partial_input={"nickname": "Countess"},
        expected_partial_output={"nickname": "Countess"},
    )
    harnesses = {
        SCHEMA_FIELD_INTROSPECTION.name: harness,
        SCHEMA_INPUT_VALIDATION.name: harness,
        SCHEMA_OUTPUT_SERIALIZATION.name: harness,
        SCHEMA_PARTIAL_UPDATE.name: harness,
    }

    result = await run_integration_conformance(
        descriptor=PYDANTIC_INTEGRATION,
        harnesses=harnesses,
        specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    )

    assert result.passed, result.failures
    rows = conformance_matrix_rows((result,))
    assert len(rows) == 4
    assert all(row.contract_version == 1 and row.passed for row in rows)


@pytest.mark.anyio
async def test_starlette_advertised_capabilities_conform_to_v1_contracts() -> None:
    app = Starlette(
        routes=[
            Route("/contract", _plain_route),
            Route("/stream", _stream_route),
        ]
    )
    harness = WebConformanceHarness(
        app=cast(Any, app),
        route_path="/contract",
        expected_route_status=200,
        expected_route_body=b"d1-ok",
        streaming_path="/stream",
    )
    harnesses = {
        WEB_ASGI.name: harness,
        WEB_HTTP_ROUTING.name: harness,
        WEB_STREAMING_RESPONSE.name: harness,
    }

    result = await run_integration_conformance(
        descriptor=STARLETTE_INTEGRATION,
        harnesses=harnesses,
        specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    )

    assert result.passed, result.failures
    rows = conformance_matrix_rows((result,))
    assert len(rows) == 3
    assert all(row.contract_version == 1 and row.passed for row in rows)
