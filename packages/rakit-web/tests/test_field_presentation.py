from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import ClassVar

import pytest
from rakit import Admin, SecretValue
from rakit_core.fields import FieldDefinition, FileField
from rakit_web.field_presentation import (
    Autocomplete,
    Checkbox,
    Choice,
    Currency,
    DatePicker,
    DateTimePicker,
    FileUpload,
    MultiAutocomplete,
    NumberInput,
    Percentage,
    Presentation,
    SearchableSelect,
    SegmentedControl,
    Select,
    Switch,
    default_presentation_registry,
    inferred_presentation,
    render_presentation,
    resolve_field_presentation,
)
from rakit_web.resource_presentation import ResourceWebPresentation


def test_core_field_presentation_is_keyword_only_opaque_metadata() -> None:
    signature = inspect.signature(FieldDefinition)
    assert signature.parameters["presentation"].kind is inspect.Parameter.KEYWORD_ONLY

    marker = object()
    field = FieldDefinition(field_id="name", python_type=str, presentation=marker)
    assert field.presentation is marker

    with pytest.raises(TypeError, match="Unsupported field presentation"):
        resolve_field_presentation(field)


def test_presentation_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="page_size"):
        Autocomplete(page_size=0)
    with pytest.raises(ValueError, match="min_query_length"):
        Autocomplete(min_query_length=-1)
    with pytest.raises(ValueError, match="unique"):
        SearchableSelect(choices=(Choice("active", "Active"), Choice("active", "Again")))
    with pytest.raises(ValueError, match="at least two"):
        SegmentedControl(choices=(Choice("one", "One"),))
    assert inspect.signature(Percentage).parameters["scale"].default is inspect.Parameter.empty
    with pytest.raises(ValueError, match="positive"):
        NumberInput(step=Decimal("0"))


def test_resolution_prefers_explicit_presentation_and_keeps_inference_conservative() -> None:
    configured = Currency(currency="IDR", locale="id-ID")
    decimal_field = FieldDefinition(
        field_id="amount",
        python_type=Decimal,
        presentation=configured,
    )
    assert resolve_field_presentation(decimal_field) is configured

    override = Percentage(scale="whole")
    assert resolve_field_presentation(decimal_field, override) is override

    inferred_decimal = inferred_presentation(
        FieldDefinition(field_id="amount", python_type=Decimal)
    )
    assert isinstance(inferred_decimal, NumberInput)
    assert not isinstance(inferred_decimal, Currency)

    assert isinstance(
        inferred_presentation(FieldDefinition(field_id="enabled", python_type=bool)),
        Checkbox,
    )
    assert not isinstance(
        inferred_presentation(FieldDefinition(field_id="enabled", python_type=bool)),
        Switch,
    )
    assert isinstance(
        inferred_presentation(FieldDefinition(field_id="on", python_type=date)),
        DatePicker,
    )
    assert isinstance(
        inferred_presentation(FieldDefinition(field_id="at", python_type=datetime)),
        DateTimePicker,
    )
    assert isinstance(
        inferred_presentation(FileField(field_id="attachment")),
        FileUpload,
    )


def test_resource_web_presentation_normalizes_field_and_relationship_overrides() -> None:
    field = SearchableSelect(choices=(Choice("draft", "Draft"), Choice("live", "Live")))
    relationship = MultiAutocomplete(search_fields=("name",), page_size=25)
    presentation = ResourceWebPresentation(
        fields={"status": field},
        relationships={"participants": relationship},
    )

    assert isinstance(presentation.fields, MappingProxyType)
    assert presentation.fields["status"] is field
    assert presentation.relationships["participants"] is relationship
    with pytest.raises(TypeError):
        presentation.fields["other"] = Select()  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty"):
        ResourceWebPresentation(fields={"": field})
    with pytest.raises(TypeError, match="Presentation"):
        ResourceWebPresentation(fields={"status": object()})  # type: ignore[dict-item]


def test_registry_is_typed_and_each_admin_gets_an_isolated_registry() -> None:
    @dataclass(frozen=True, slots=True)
    class RatingStars(Presentation):
        key: ClassVar[str] = "rating_stars"
        max_stars: int = 5

    registry = default_presentation_registry()

    def renderer(presentation: Presentation, context: Mapping[str, object]) -> Mapping[str, object]:
        assert isinstance(presentation, RatingStars)
        return {
            **context,
            "presentation": presentation,
            "presentation_key": presentation.key,
            "custom_template": "widgets/rating_stars.html",
        }

    registry.register(RatingStars, renderer)
    rendered = render_presentation(RatingStars(), {"name": "rating"}, registry=registry)
    assert rendered["name"] == "rating"
    assert rendered["custom_template"] == "widgets/rating_stars.html"

    with pytest.raises(ValueError, match="already registered"):
        registry.register(RatingStars, renderer)

    first = Admin(title="First", debug=True, secret_key=SecretValue("x" * 32))
    second = Admin(title="Second", debug=True, secret_key=SecretValue("y" * 32))
    assert first.presentations is first.presentations
    assert first.presentations is not second.presentations
