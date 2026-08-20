from collections.abc import Callable

import pytest
from rakit_core.admin_types import ResourceAdmin, ResourceWriteDefinition
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema


def _schema() -> FormSchema:
    return FormSchema(
        fields=(
            FieldDefinition(field_id="name", python_type=str, required=True),
            FieldDefinition(field_id="status", python_type=str, writable=False),
        )
    )


def test_resource_write_definition_preserves_explicit_policy() -> None:
    schema = _schema()

    definition = ResourceWriteDefinition(
        form_schema=schema,
        writable_fields=("name",),
        version_field="version",
        success_message="Saved.",
        htmx_refresh_targets=("rakit:refresh",),
    )

    assert definition.form_schema is schema
    assert definition.writable_fields == ("name",)
    assert definition.version_field == "version"
    assert definition.success_message == "Saved."
    assert definition.htmx_refresh_targets == ("rakit:refresh",)


def test_resource_admin_is_read_only_by_default() -> None:
    assert ResourceAdmin.write is None


def _empty_writable_fields() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(form_schema=_schema(), writable_fields=())


def _duplicate_writable_fields() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=_schema(),
        writable_fields=("name", "name"),
    )


def _unknown_writable_field() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=_schema(),
        writable_fields=("missing",),
    )


def _non_writable_form_field() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=_schema(),
        writable_fields=("status",),
    )


def _blank_version_field() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=_schema(),
        writable_fields=("name",),
        version_field="  ",
    )


def _duplicate_refresh_targets() -> ResourceWriteDefinition:
    return ResourceWriteDefinition(
        form_schema=_schema(),
        writable_fields=("name",),
        htmx_refresh_targets=("rakit:refresh", "rakit:refresh"),
    )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (_empty_writable_fields, "writable_fields must be a non-empty tuple"),
        (_duplicate_writable_fields, "writable_fields must be unique"),
        (_unknown_writable_field, "unknown form fields"),
        (_non_writable_form_field, "non-writable form fields"),
        (_blank_version_field, "version_field must be None or a non-empty string"),
        (
            _duplicate_refresh_targets,
            "htmx_refresh_targets must contain unique non-empty strings",
        ),
    ],
)
def test_resource_write_definition_rejects_unsafe_policy(
    factory: Callable[[], ResourceWriteDefinition], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
