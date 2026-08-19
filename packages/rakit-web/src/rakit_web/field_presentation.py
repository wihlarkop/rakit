from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import ClassVar, Literal

from rakit_core.fields import FieldDefinition, FileField


class Presentation:
    """Marker for immutable Web-only field and relationship presentation policy."""

    key: ClassVar[str] = "presentation"


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("choice value must be a non-empty string")
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("choice label must be a non-empty string")


@dataclass(frozen=True, slots=True)
class TextInput(Presentation):
    key: ClassVar[str] = "text"
    placeholder: str | None = None
    input_type: str = "text"


@dataclass(frozen=True, slots=True)
class Select(Presentation):
    key: ClassVar[str] = "select"
    choices: tuple[Choice, ...] = ()
    placeholder: str | None = None

    def __post_init__(self) -> None:
        values = tuple(choice.value for choice in self.choices)
        if len(values) != len(set(values)):
            raise ValueError("select choice values must be unique")


@dataclass(frozen=True, slots=True)
class SearchableSelect(Select):
    key: ClassVar[str] = "searchable_select"
    search_placeholder: str = "Search options..."


@dataclass(frozen=True, slots=True)
class Autocomplete(Presentation):
    key: ClassVar[str] = "autocomplete"
    search_fields: tuple[str, ...] = ()
    display_fields: tuple[str, ...] = ()
    placeholder: str | None = None
    min_query_length: int = 2
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.min_query_length < 0:
            raise ValueError("min_query_length must be non-negative")
        if not 1 <= self.page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        if len(self.search_fields) != len(set(self.search_fields)) or any(
            not item for item in self.search_fields
        ):
            raise ValueError("search_fields must contain unique non-empty field ids")
        if len(self.display_fields) != len(set(self.display_fields)) or any(
            not item for item in self.display_fields
        ):
            raise ValueError("display_fields must contain unique non-empty field ids")


@dataclass(frozen=True, slots=True)
class MultiAutocomplete(Autocomplete):
    key: ClassVar[str] = "multi_autocomplete"


@dataclass(frozen=True, slots=True)
class DatePicker(Presentation):
    key: ClassVar[str] = "date"
    min_value: date | None = None
    max_value: date | None = None

    def __post_init__(self) -> None:
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("date minimum cannot exceed maximum")


@dataclass(frozen=True, slots=True)
class TimePicker(Presentation):
    key: ClassVar[str] = "time"
    step_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.step_seconds is not None and self.step_seconds < 1:
            raise ValueError("time step_seconds must be positive")


@dataclass(frozen=True, slots=True)
class DateTimePicker(Presentation):
    key: ClassVar[str] = "datetime"
    timezone: str | None = None
    step_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.timezone is not None and not self.timezone.strip():
            raise ValueError("timezone must be a non-empty string")
        if self.step_seconds is not None and self.step_seconds < 1:
            raise ValueError("datetime step_seconds must be positive")


@dataclass(frozen=True, slots=True)
class DateRangePicker(Presentation):
    key: ClassVar[str] = "date_range"
    placeholder: str = "YYYY-MM-DD – YYYY-MM-DD"


@dataclass(frozen=True, slots=True)
class NumberInput(Presentation):
    key: ClassVar[str] = "number"
    min_value: int | float | Decimal | None = None
    max_value: int | float | Decimal | None = None
    step: int | float | Decimal | None = None
    prefix: str | None = None
    suffix: str | None = None

    def __post_init__(self) -> None:
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("number minimum cannot exceed maximum")
        if self.step is not None and self.step <= 0:
            raise ValueError("number step must be positive")


@dataclass(frozen=True, slots=True)
class Currency(Presentation):
    key: ClassVar[str] = "currency"
    currency: str
    locale: str | None = None
    min_value: int | float | Decimal | None = None
    max_value: int | float | Decimal | None = None
    step: int | float | Decimal | None = None

    def __post_init__(self) -> None:
        if not self.currency or not self.currency.strip():
            raise ValueError("currency must be a non-empty code")
        if self.locale is not None and not self.locale.strip():
            raise ValueError("locale must be a non-empty string")
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("currency minimum cannot exceed maximum")
        if self.step is not None and self.step <= 0:
            raise ValueError("currency step must be positive")


@dataclass(frozen=True, slots=True)
class Percentage(Presentation):
    key: ClassVar[str] = "percentage"
    scale: Literal["whole", "fraction"]
    min_value: int | float | Decimal | None = None
    max_value: int | float | Decimal | None = None
    step: int | float | Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("percentage minimum cannot exceed maximum")
        if self.step is not None and self.step <= 0:
            raise ValueError("percentage step must be positive")


@dataclass(frozen=True, slots=True)
class Checkbox(Presentation):
    key: ClassVar[str] = "checkbox"


@dataclass(frozen=True, slots=True)
class Switch(Presentation):
    key: ClassVar[str] = "switch"
    on_label: str = "On"
    off_label: str = "Off"

    def __post_init__(self) -> None:
        if not self.on_label or not self.off_label:
            raise ValueError("switch labels must be non-empty")


@dataclass(frozen=True, slots=True)
class SegmentedControl(Presentation):
    key: ClassVar[str] = "segmented"
    choices: tuple[Choice, ...]

    def __post_init__(self) -> None:
        if len(self.choices) < 2:
            raise ValueError("segmented controls require at least two choices")
        values = tuple(choice.value for choice in self.choices)
        if len(values) != len(set(values)):
            raise ValueError("segmented choice values must be unique")


@dataclass(frozen=True, slots=True)
class FileUpload(Presentation):
    key: ClassVar[str] = "file_upload"
    drag_drop: bool = True
    preview: bool = True


@dataclass(frozen=True, slots=True)
class ImageUpload(FileUpload):
    key: ClassVar[str] = "image_upload"
    show_dimensions: bool = True


FieldPresentation = Presentation
RelationshipPresentation = Presentation
FieldRenderer = Callable[[Presentation, Mapping[str, object]], Mapping[str, object]]


class PresentationRegistry:
    """Central Web renderer registry keyed by typed presentation class."""

    def __init__(self) -> None:
        self._renderers: dict[type[Presentation], FieldRenderer] = {}

    def register(
        self,
        presentation_type: type[Presentation],
        renderer: FieldRenderer,
        *,
        replace: bool = False,
    ) -> None:
        if not issubclass(presentation_type, Presentation):
            raise TypeError("presentation_type must inherit Presentation")
        if not callable(renderer):
            raise TypeError("renderer must be callable")
        if presentation_type in self._renderers and not replace:
            raise ValueError("presentation renderer is already registered")
        self._renderers[presentation_type] = renderer

    def resolve(self, presentation: Presentation) -> FieldRenderer:
        for candidate in type(presentation).__mro__:
            if candidate in self._renderers:
                return self._renderers[candidate]
        raise KeyError(f"No renderer registered for {type(presentation).__name__}")

    @property
    def renderers(self) -> Mapping[type[Presentation], FieldRenderer]:
        return MappingProxyType(self._renderers)


def _default_renderer(
    presentation: Presentation, context: Mapping[str, object]
) -> Mapping[str, object]:
    return {**context, "presentation": presentation, "presentation_key": presentation.key}


def default_presentation_registry() -> PresentationRegistry:
    registry = PresentationRegistry()
    registry.register(Presentation, _default_renderer)
    return registry


DEFAULT_PRESENTATION_REGISTRY = default_presentation_registry()


def render_presentation(
    presentation: Presentation,
    context: Mapping[str, object],
    *,
    registry: PresentationRegistry = DEFAULT_PRESENTATION_REGISTRY,
) -> Mapping[str, object]:
    return registry.resolve(presentation)(presentation, context)


def enum_choices(python_type: type[object]) -> tuple[Choice, ...]:
    if not issubclass(python_type, Enum):
        return ()
    return tuple(
        Choice(
            value=str(member.value),
            label=member.name.replace("_", " ").title(),
        )
        for member in python_type
    )


def inferred_presentation(field: FieldDefinition) -> Presentation:
    if isinstance(field, FileField):
        return FileUpload(drag_drop=False, preview=True)
    python_type = field.python_type
    if python_type is bool:
        return Checkbox()
    if python_type is datetime:
        return DateTimePicker()
    if python_type is date:
        return DatePicker()
    if python_type is time:
        return TimePicker()
    if python_type in {int, float, Decimal}:
        return NumberInput()
    if isinstance(python_type, type) and issubclass(python_type, Enum):
        return Select(choices=enum_choices(python_type))
    return TextInput()


def legacy_widget_presentation(widget: str) -> Presentation:
    normalized = widget.strip().lower()
    if normalized == "file":
        return FileUpload(drag_drop=False, preview=True)
    if normalized in {"checkbox", "boolean"}:
        return Checkbox()
    if normalized == "select":
        return Select()
    if normalized == "date":
        return DatePicker()
    if normalized in {"datetime", "datetime-local"}:
        return DateTimePicker()
    if normalized == "time":
        return TimePicker()
    if normalized in {"number", "numeric"}:
        return NumberInput()
    return TextInput(input_type=normalized if normalized in {"email", "url", "password"} else "text")


def resolve_field_presentation(
    field: FieldDefinition,
    override: Presentation | None = None,
) -> Presentation:
    if override is not None:
        return override
    if field.presentation is not None:
        if not isinstance(field.presentation, Presentation):
            raise TypeError("Unsupported field presentation")
        return field.presentation
    if field.widget != "text":
        return legacy_widget_presentation(field.widget)
    return inferred_presentation(field)


def resolve_relationship_presentation(
    inline: object | None,
    override: Presentation | None = None,
) -> Presentation | None:
    candidate = override if override is not None else inline
    if candidate is None:
        return None
    if not isinstance(candidate, Presentation):
        raise TypeError("Unsupported relationship presentation")
    return candidate


__all__ = [
    "Autocomplete",
    "Checkbox",
    "Choice",
    "Currency",
    "DatePicker",
    "DateRangePicker",
    "DateTimePicker",
    "DEFAULT_PRESENTATION_REGISTRY",
    "FieldPresentation",
    "FieldRenderer",
    "FileUpload",
    "ImageUpload",
    "MultiAutocomplete",
    "NumberInput",
    "Percentage",
    "Presentation",
    "PresentationRegistry",
    "RelationshipPresentation",
    "SearchableSelect",
    "SegmentedControl",
    "Select",
    "Switch",
    "TextInput",
    "TimePicker",
    "default_presentation_registry",
    "inferred_presentation",
    "legacy_widget_presentation",
    "render_presentation",
    "resolve_field_presentation",
    "resolve_relationship_presentation",
]
