from datetime import date
from typing import cast

import pytest
from rakit_core.fields import FieldDefinition, infer_field_security
from rakit_core.forms import FormSchema


def test_sensitive_field_is_hidden_and_not_writable() -> None:
    field = infer_field_security(FieldDefinition(field_id="password_hash", python_type=str))

    assert not field.readable
    assert not field.writable
    assert not field.searchable
    assert not field.filterable
    assert not field.sortable


def test_unknown_form_field_is_rejected_before_normalization() -> None:
    schema = FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),))

    with pytest.raises(ValueError, match="Unknown form field"):
        schema.parse({"name": "Ada", "is_superuser": "true"})


def test_form_state_has_immutable_typed_normalized_values() -> None:
    schema = FormSchema(
        fields=(
            FieldDefinition(field_id="name", python_type=str, required=True),
            FieldDefinition(field_id="birthday", python_type=date, nullable=True),
        )
    )

    state = schema.parse({"name": "Ada", "birthday": "1815-12-10"})

    assert state.normalized == {"name": "Ada", "birthday": date(1815, 12, 10)}
    with pytest.raises(TypeError):
        cast(dict[str, object], state.normalized)["name"] = "Grace"
