from datetime import date
from typing import cast

import pytest
from rakit_core.fields import FieldDefinition, infer_field_security
from rakit_core.forms import (
    CollapsibleGroup,
    Column,
    CustomBlock,
    FieldLayout,
    FormLayout,
    FormSchema,
    FormValidationError,
    RelationshipPanel,
    Row,
    Section,
    Tab,
    Tabs,
)


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


def test_parser_formatter_and_typed_layout_are_applied_without_bypassing_validation() -> None:
    schema = FormSchema(
        fields=(
            FieldDefinition(
                field_id="name",
                python_type=str,
                parser=lambda value: str(value).strip().title(),
                formatter=lambda value: f"User: {value}",
            ),
        ),
        layout=FormLayout(
            children=(
                Section(
                    layout_id="profile",
                    title="Profile",
                    children=(Row(children=(Column(children=(FieldLayout("name"),)),)),),
                ),
                Tabs(
                    layout_id="extra",
                    tabs=(
                        Tab(
                            layout_id="advanced",
                            label="Advanced",
                            children=(
                                CollapsibleGroup(
                                    layout_id="more",
                                    label="More",
                                    children=(RelationshipPanel("relations", "teams"),),
                                ),
                            ),
                        ),
                    ),
                ),
                CustomBlock(layout_id="help", block_id="profile-help"),
            )
        ),
    )

    state = schema.parse({"name": "  ada  "})

    assert state.normalized == {"name": "Ada"}
    assert schema.format_value("name", "Ada") == "User: Ada"
    first = schema.resolved_layout().children[0]
    assert isinstance(first, Section)
    assert first.layout_id == "profile"


def test_parser_errors_become_field_issues_and_layout_rejects_bad_references() -> None:
    schema = FormSchema(
        fields=(
            FieldDefinition(
                field_id="count",
                python_type=int,
                parser=lambda _value: (_ for _ in ()).throw(ValueError()),
            ),
        )
    )
    with pytest.raises(FormValidationError) as caught:
        schema.parse({"count": "not-a-number"})
    assert caught.value.state.issues[0].field_id == "count"

    with pytest.raises(ValueError, match="unknown field"):
        FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str),),
            layout=FormLayout(children=(FieldLayout("missing"),)),
        )
    with pytest.raises(ValueError, match="more than once"):
        FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str),),
            layout=FormLayout(children=(FieldLayout("name"), FieldLayout("name"))),
        )
    with pytest.raises(ValueError, match="ids must be unique"):
        FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str),),
            layout=FormLayout(
                children=(
                    Section(layout_id="duplicate", title="One", children=()),
                    CustomBlock(layout_id="duplicate", block_id="two"),
                )
            ),
        )


def test_formatter_cannot_expose_sensitive_field() -> None:
    schema = FormSchema(
        fields=(
            FieldDefinition(
                field_id="password_hash",
                python_type=str,
                formatter=lambda _value: "leaked",
            ),
        )
    )
    assert schema.format_value("password_hash", "secret") == ""
