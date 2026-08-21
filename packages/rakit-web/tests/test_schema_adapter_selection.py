from __future__ import annotations

import pytest
from rakit_core.errors import RakitError
from rakit_schema_msgspec import MsgspecSchemaAdapter
from rakit_schema_pydantic import PydanticSchemaAdapter
from rakit_web.schema_selection import installed_schema_adapter_ids, resolve_schema_adapter


def test_default_schema_selection_prefers_pydantic() -> None:
    adapter = resolve_schema_adapter(None, schema_integration_id=None)

    assert isinstance(adapter, PydanticSchemaAdapter)


def test_explicit_msgspec_selection_is_deterministic() -> None:
    adapter = resolve_schema_adapter(None, schema_integration_id="schema.msgspec")

    assert isinstance(adapter, MsgspecSchemaAdapter)


def test_installed_schema_adapter_inventory_is_deterministic() -> None:
    assert installed_schema_adapter_ids() == ("schema.msgspec", "schema.pydantic")


def test_unknown_explicit_schema_selection_fails_actionably() -> None:
    with pytest.raises(RakitError) as exc_info:
        resolve_schema_adapter(None, schema_integration_id="schema.unknown")

    assert exc_info.value.details == {
        "reason": "schema_adapter_unavailable",
        "integration_id": "schema.unknown",
        "available": ("schema.msgspec", "schema.pydantic"),
    }


def test_explicit_adapter_and_conflicting_identifier_fail_closed() -> None:
    with pytest.raises(RakitError) as exc_info:
        resolve_schema_adapter(
            PydanticSchemaAdapter(),
            schema_integration_id="schema.msgspec",
        )

    assert exc_info.value.details == {
        "reason": "schema_adapter_selection_conflict",
        "integration_id": "schema.msgspec",
    }
