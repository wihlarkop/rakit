from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ._immutability import deep_freeze


class FilterOperator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    CONTAINS = "contains"
    IN = "in"
    IS_NULL = "is_null"


class Filter(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    operator: FilterOperator
    value: object

    @field_validator("value")
    @classmethod
    def freeze_value(cls, value: object) -> object:
        return deep_freeze(value)


class FilterControl(StrEnum):
    LEGACY = "legacy"
    CHOICE = "choice"
    BOOLEAN = "boolean"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATE_RANGE = "date_range"


class FilterChoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    label: str

    @model_validator(mode="after")
    def _validate_choice(self) -> FilterChoice:
        if not self.value.strip():
            raise ValueError("Filter choice value must not be empty")
        if not self.label.strip():
            raise ValueError("Filter choice label must not be empty")
        return self


class FilterSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    filter_id: str
    operator: FilterOperator
    value: object

    @field_validator("value")
    @classmethod
    def freeze_value(cls, value: object) -> object:
        return deep_freeze(value)


@dataclass(frozen=True, slots=True)
class ResolvedFilterSelection:
    selection: FilterSelection
    predicates: tuple[Filter, ...]
    display_value: str


class ResourceFilter(BaseModel):
    """Backend-neutral resource filter definition.

    Subclasses may provide semantic controls and translate one submitted
    selection into one or more ordinary ``Filter`` predicates.  Every field a
    custom resolver may emit must be declared in ``predicate_fields`` so data
    source adapters can validate the query surface before runtime.
    """

    model_config = ConfigDict(frozen=True)

    filter_id: str
    label: str
    operators: tuple[FilterOperator, ...] = (FilterOperator.EQ,)
    predicate_fields: tuple[str, ...]
    control: FilterControl = FilterControl.TEXT
    choices: tuple[FilterChoice, ...] = ()

    @model_validator(mode="after")
    def _validate_definition(self) -> ResourceFilter:
        if not self.filter_id.strip():
            raise ValueError("Filter id must not be empty")
        if not self.label.strip():
            raise ValueError("Filter label must not be empty")
        if not self.operators:
            raise ValueError("Filter operators must not be empty")
        if len(set(self.operators)) != len(self.operators):
            raise ValueError("Filter operators must be unique")
        if not self.predicate_fields:
            raise ValueError("Filter predicate fields must not be empty")
        if any(not field.strip() for field in self.predicate_fields):
            raise ValueError("Filter predicate fields must not be empty")
        if len(set(self.predicate_fields)) != len(self.predicate_fields):
            raise ValueError("Filter predicate fields must be unique")
        choice_values = tuple(choice.value for choice in self.choices)
        if len(set(choice_values)) != len(choice_values):
            raise ValueError("Filter choice values must be unique")
        if self.__class__.resolve_predicates is ResourceFilter.resolve_predicates:
            raise ValueError("ResourceFilter subclasses must implement resolve_predicates")
        return self

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        return raw_value

    def resolve_predicates(
        self,
        *,
        operator: FilterOperator,
        value: object,
    ) -> tuple[Filter, ...]:
        raise NotImplementedError

    def serialize_value(self, *, operator: FilterOperator, value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return ",".join(cast(tuple[str, ...], value))
        raise ValueError("Filter value cannot be serialized")

    def display_value(self, *, operator: FilterOperator, value: object) -> str:
        for choice in self.choices:
            if choice.value == value:
                return choice.label
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, tuple):
            return ", ".join(str(item) for item in value)
        return str(value)


class _FieldResourceFilter(ResourceFilter):
    predicate_fields: tuple[str, ...] = ()
    field: str

    @model_validator(mode="before")
    @classmethod
    def _derive_predicate_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and "field" in data and "predicate_fields" not in data:
            normalized = dict(data)
            normalized["predicate_fields"] = (data["field"],)
            return normalized
        return data

    @model_validator(mode="after")
    def _validate_field(self) -> _FieldResourceFilter:
        if not self.field.strip():
            raise ValueError("Filter field must not be empty")
        if self.predicate_fields != (self.field,):
            raise ValueError("Built-in field filters must target exactly their declared field")
        return self

    def resolve_predicates(
        self,
        *,
        operator: FilterOperator,
        value: object,
    ) -> tuple[Filter, ...]:
        return (Filter(field=self.field, operator=operator, value=value),)


class ChoiceFilter(_FieldResourceFilter):
    control: FilterControl = FilterControl.CHOICE
    operators: tuple[FilterOperator, ...] = (FilterOperator.EQ,)

    @model_validator(mode="after")
    def _validate_choices(self) -> ChoiceFilter:
        if not self.choices:
            raise ValueError("ChoiceFilter requires at least one choice")
        return self

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if not isinstance(raw_value, str):
            raise ValueError("Choice filter value must be a string")
        if raw_value not in {choice.value for choice in self.choices}:
            raise ValueError("Choice filter value is not allowed")
        return raw_value


class BooleanFilter(_FieldResourceFilter):
    control: FilterControl = FilterControl.BOOLEAN
    operators: tuple[FilterOperator, ...] = (FilterOperator.EQ,)

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if isinstance(raw_value, bool):
            return raw_value
        if not isinstance(raw_value, str):
            raise ValueError("Boolean filter value must be true or false")
        normalized = raw_value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise ValueError("Boolean filter value must be true or false")


class TextFilter(_FieldResourceFilter):
    control: FilterControl = FilterControl.TEXT
    operators: tuple[FilterOperator, ...] = (
        FilterOperator.EQ,
        FilterOperator.NEQ,
        FilterOperator.CONTAINS,
    )

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if not isinstance(raw_value, str):
            raise ValueError("Text filter value must be a string")
        return raw_value


class NumberFilter(_FieldResourceFilter):
    control: FilterControl = FilterControl.NUMBER
    operators: tuple[FilterOperator, ...] = (
        FilterOperator.EQ,
        FilterOperator.NEQ,
        FilterOperator.LT,
        FilterOperator.LTE,
        FilterOperator.GT,
        FilterOperator.GTE,
    )

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if isinstance(raw_value, bool) or not isinstance(raw_value, str | int | float | Decimal):
            raise ValueError("Number filter value must be numeric")
        canonical = str(raw_value)
        try:
            value = Decimal(canonical)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Number filter value must be numeric") from exc
        if not value.is_finite():
            raise ValueError("Number filter value must be finite")
        return canonical


class DateFilter(_FieldResourceFilter):
    control: FilterControl = FilterControl.DATE
    operators: tuple[FilterOperator, ...] = (
        FilterOperator.EQ,
        FilterOperator.NEQ,
        FilterOperator.LT,
        FilterOperator.LTE,
        FilterOperator.GT,
        FilterOperator.GTE,
    )

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if isinstance(raw_value, date):
            return raw_value.isoformat()
        if not isinstance(raw_value, str):
            raise ValueError("Date filter value must be an ISO date")
        try:
            date.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError("Date filter value must be an ISO date") from exc
        return raw_value


class DateRangeFilter(DateFilter):
    control: FilterControl = FilterControl.DATE_RANGE
    operators: tuple[FilterOperator, ...] = (
        FilterOperator.GTE,
        FilterOperator.LTE,
    )


class LegacyFieldFilter(_FieldResourceFilter):
    """Compatibility definition for ``ResourceFieldPolicy.filter_fields``.

    ``strip_in_values`` preserves generated REST's historical comma-trimming
    behavior for direct ``ApiFilterDefinition`` declarations while Admin Web
    legacy filters keep their existing exact token semantics.
    """

    control: FilterControl = FilterControl.LEGACY
    operators: tuple[FilterOperator, ...] = tuple(FilterOperator)
    strip_in_values: bool = False

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:
        if operator is FilterOperator.IN:
            if isinstance(raw_value, tuple) and all(isinstance(item, str) for item in raw_value):
                values = raw_value
            elif isinstance(raw_value, list) and all(isinstance(item, str) for item in raw_value):
                values = tuple(raw_value)
            elif isinstance(raw_value, str):
                parts = raw_value.split(",")
                if self.strip_in_values:
                    values = tuple(part.strip() for part in parts if part.strip())
                else:
                    values = tuple(part for part in parts if part)
            else:
                raise ValueError("IN filter value must be a string sequence")
            if not values:
                raise ValueError("IN filter value must not be empty")
            return values
        if operator is FilterOperator.IS_NULL:
            if isinstance(raw_value, bool):
                return raw_value
            if not isinstance(raw_value, str):
                raise ValueError("IS NULL filter value must be true or false")
            normalized = raw_value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
            raise ValueError("IS NULL filter value must be true or false")
        if not isinstance(raw_value, str):
            raise ValueError("Legacy filter value must be a string")
        return raw_value


def resolve_filter_selection(
    definition: ResourceFilter,
    *,
    operator: FilterOperator,
    raw_value: object,
) -> ResolvedFilterSelection:
    if operator not in definition.operators:
        raise ValueError(f"Filter operator {operator.value!r} is not allowed")
    value = definition.parse_value(operator=operator, raw_value=raw_value)
    predicates = tuple(definition.resolve_predicates(operator=operator, value=value))
    declared_fields = set(definition.predicate_fields)
    if any(predicate.field not in declared_fields for predicate in predicates):
        raise ValueError("Filter resolver emitted an undeclared predicate field")
    selection = FilterSelection(
        filter_id=definition.filter_id,
        operator=operator,
        value=value,
    )
    return ResolvedFilterSelection(
        selection=selection,
        predicates=predicates,
        display_value=definition.display_value(operator=operator, value=value),
    )


def humanize_filter_id(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def effective_resource_filters(
    explicit: tuple[ResourceFilter, ...],
    legacy_fields: tuple[str, ...],
) -> tuple[ResourceFilter, ...]:
    explicit_ids = {definition.filter_id for definition in explicit}
    legacy = tuple(
        LegacyFieldFilter(
            filter_id=field,
            label=humanize_filter_id(field),
            field=field,
        )
        for field in legacy_fields
        if field not in explicit_ids
    )
    return (*explicit, *legacy)


__all__ = [
    "BooleanFilter",
    "ChoiceFilter",
    "DateFilter",
    "DateRangeFilter",
    "Filter",
    "FilterChoice",
    "FilterControl",
    "FilterOperator",
    "FilterSelection",
    "LegacyFieldFilter",
    "NumberFilter",
    "ResolvedFilterSelection",
    "ResourceFilter",
    "TextFilter",
    "effective_resource_filters",
    "humanize_filter_id",
    "resolve_filter_selection",
]
