from __future__ import annotations

import asyncio

import msgspec
import pytest
from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
)
from rakit_core.conformance import conformance_matrix_rows, run_integration_conformance
from rakit_core.schema import SchemaValidationError
from rakit_core.testing.capability_conformance import (
    CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    SchemaConformanceHarness,
)
from rakit_schema_msgspec import MsgspecSchemaAdapter
from rakit_schema_msgspec.discovery import MSGSPEC_INTEGRATION


class ContactSchema(msgspec.Struct):
    name: str
    age: int
    nickname: str | None = None


def test_msgspec_schema_adapter_conforms_to_all_advertised_v1_contracts() -> None:
    adapter = MsgspecSchemaAdapter()
    harness = SchemaConformanceHarness(
        adapter=adapter,
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
        partial_input={"nickname": None},
        expected_partial_output={"nickname": None},
    )
    harnesses = {
        SCHEMA_FIELD_INTROSPECTION.name: harness,
        SCHEMA_INPUT_VALIDATION.name: harness,
        SCHEMA_OUTPUT_SERIALIZATION.name: harness,
        SCHEMA_PARTIAL_UPDATE.name: harness,
    }

    result = asyncio.run(
        run_integration_conformance(
            descriptor=MSGSPEC_INTEGRATION,
            harnesses=harnesses,
            specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
        )
    )

    assert result.passed, result.failures
    rows = conformance_matrix_rows((result,))
    assert len(rows) == 4
    assert all(row.contract_version == 1 and row.passed for row in rows)


def test_msgspec_partial_update_is_presence_aware() -> None:
    adapter = MsgspecSchemaAdapter()

    assert adapter.validate_partial_input(ContactSchema, {}) == {}
    assert adapter.validate_partial_input(ContactSchema, {"nickname": None}) == {"nickname": None}
    assert adapter.validate_partial_input(ContactSchema, {"name": "Ada"}) == {"name": "Ada"}


def test_msgspec_partial_update_rejects_invalid_present_and_unknown_fields() -> None:
    adapter = MsgspecSchemaAdapter()

    with pytest.raises(SchemaValidationError):
        adapter.validate_partial_input(ContactSchema, {"age": "bad"})

    with pytest.raises(SchemaValidationError):
        adapter.validate_partial_input(ContactSchema, {"unknown": "value"})


def test_msgspec_rejects_non_struct_schema_types() -> None:
    adapter = MsgspecSchemaAdapter()

    with pytest.raises(TypeError, match="msgspec.Struct"):
        adapter.fields(dict)
    with pytest.raises(TypeError, match="msgspec.Struct"):
        adapter.validate_input(dict, {})
    with pytest.raises(TypeError, match="msgspec.Struct"):
        adapter.validate_partial_input(dict, {})


def test_msgspec_validation_errors_are_translated_to_rakit_issues() -> None:
    adapter = MsgspecSchemaAdapter()

    with pytest.raises(SchemaValidationError) as exc_info:
        adapter.validate_input(ContactSchema, {"name": "Ada", "age": "bad"})

    assert exc_info.value.issues
    issue = exc_info.value.issues[0]
    assert issue.location
    assert issue.code == "validation_error"
    assert issue.message
