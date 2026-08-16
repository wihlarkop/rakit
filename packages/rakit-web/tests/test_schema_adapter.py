import pytest
from pydantic import BaseModel
from rakit_core.schema import SchemaValidationError
from rakit_web.capabilities import STARLETTE_WEB_CAPABILITIES
from rakit_web.schema import PYDANTIC_SCHEMA_CAPABILITIES, PydanticSchemaAdapter


class Payload(BaseModel):
    name: str
    count: int


def test_web_runtime_declares_transport_capabilities() -> None:
    assert STARLETTE_WEB_CAPABILITIES.provider_id == "web.starlette"
    assert STARLETTE_WEB_CAPABILITIES.capabilities.names == (
        "web.asgi",
        "web.http-routing",
        "web.streaming-response",
    )


def test_pydantic_adapter_declares_only_proven_schema_capabilities() -> None:
    assert PYDANTIC_SCHEMA_CAPABILITIES.provider_id == "schema.pydantic"
    assert PYDANTIC_SCHEMA_CAPABILITIES.capabilities.names == (
        "schema.field-introspection",
        "schema.input-validation",
        "schema.output-serialization",
    )
    assert not PYDANTIC_SCHEMA_CAPABILITIES.capabilities.supports("schema.partial-update")


def test_pydantic_adapter_validates_introspects_and_serializes() -> None:
    adapter = PydanticSchemaAdapter()

    assert adapter.field_names(Payload) == ("name", "count")
    validated = adapter.validate_input(Payload, {"name": "rakit", "count": "2"})
    assert isinstance(validated, Payload)
    assert validated.count == 2
    assert adapter.serialize_output(Payload, validated) == {"name": "rakit", "count": 2}


def test_pydantic_adapter_normalizes_validation_errors() -> None:
    adapter = PydanticSchemaAdapter()

    with pytest.raises(SchemaValidationError) as captured:
        adapter.validate_input(Payload, {"name": "rakit", "count": "not-an-int"})

    issue = captured.value.issues[0]
    assert issue.location == ("count",)
    assert issue.code == "int_parsing"


def test_pydantic_adapter_rejects_non_pydantic_schema() -> None:
    with pytest.raises(TypeError, match="BaseModel"):
        PydanticSchemaAdapter().field_names(dict)
